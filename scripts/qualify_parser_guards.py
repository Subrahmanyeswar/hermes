import asyncio
import os
import sys
import json
import shutil
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from core.response_parser import ResponseParser, ParseSuccess, ParseFailure
from core.agent_loop.actions import ActionExecutor, ActionEnvelope
from core.workspace import WorkspaceManager
from models.provider import NormalizedModelResponse

PARSER_TEST_WS = Path(os.getenv("TEMP", "C:/Users/SUBBU/AppData/Local/Temp")) / "hermes_parser_guard_test_ws"
if PARSER_TEST_WS.exists():
    shutil.rmtree(PARSER_TEST_WS, ignore_errors=True)
PARSER_TEST_WS.mkdir(parents=True, exist_ok=True)

def test_parser_adversarial_bash_instructions():
    print("======================================================================")
    print("STEP 2.1: PARSER REGRESSION — ADVERSARIAL BASH INSTRUCTIONS IN PROSE")
    print("======================================================================")
    
    parser = ResponseParser()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(PARSER_TEST_WS))
    
    # Text mentioning index.html and Three.js with bash instructions
    adversarial_responses = [
        # Case 1: bash block mentioning Three.js and index.html
        (
            "To install the dependencies in Three.js and index.html, run the following setup commands:\n"
            "```bash\n"
            "mkdir -p rocket-app\n"
            "cd rocket-app\n"
            "npm install three\n"
            "```\n"
            "Once Three.js is installed, you can start building index.html."
        ),
        # Case 2: sh block with 'in index.html'
        (
            "First initialize the project in index.html:\n"
            "```sh\n"
            "mkdir -p src\n"
            "cd src\n"
            "npm install three\n"
            "```\n"
        ),
        # Case 3: generic block starting with mkdir
        (
            "Create the directory structure for Three.js:\n"
            "```\n"
            "mkdir -p assets components\n"
            "cd assets\n"
            "npm install three\n"
            "```\n"
        )
    ]
    
    for idx, raw_text in enumerate(adversarial_responses, 1):
        print(f"\n--- Testing Adversarial Case {idx} ---")
        print(f"Input text snippet:\n{raw_text[:120]}...\n")
        resp = NormalizedModelResponse(
            text=raw_text,
            model="test-adversarial",
            provider="test",
            success=True
        )
        res = parser.parse(resp)
        print(f"Parser Result Type: {type(res).__name__}")
        
        if isinstance(res, ParseSuccess):
            print(f"Extracted Tool: {res.tool}")
            print(f"Parameters: {res.parameters}")
            # Ensure it NEVER extracted write_file targeting Three.js or index.html with bash code!
            assert res.tool != "write_file" or (
                res.parameters.get("path") not in ("Three.js", "index.html")
                and "mkdir" not in res.parameters.get("content", "")
            ), f"CRITICAL LEAK: Parser synthesized write_file for {res.parameters.get('path')} with bash content!"
        else:
            print(f"Parse correctly failed or rejected: {getattr(res, 'failure_reason', 'rejected')}")
            
    print("\n[VERIFIED] Zero fake write_file calls generated for adversarial bash instructions.")

def test_parser_legitimate_structured_write_file():
    print("\n======================================================================")
    print("STEP 2.2: PARSER REGRESSION — VALID STRUCTURED WRITE_FILE VERIFICATION")
    print("======================================================================")
    
    parser = ResponseParser()
    ws_mgr = WorkspaceManager()
    ws_mgr.lock(str(PARSER_TEST_WS))
    
    legit_html = "<!DOCTYPE html>\n<html>\n<head><title>Rocket Sim</title></head>\n<body><h1>Mission Control</h1></body>\n</html>"
    
    # Case A: JSON structured block
    json_block = f"""
I will now create index.html for the application.

```json
{{
  "tool": "write_file",
  "parameters": {{
    "path": "index.html",
    "content": {json.dumps(legit_html)}
  }}
}}
```
"""
    resp_a = NormalizedModelResponse(text=json_block, model="test-legit", provider="test", success=True)
    res_a = parser.parse(resp_a)
    print(f"Case A (JSON block) Result: {type(res_a).__name__} | tool={getattr(res_a, 'tool', None)}")
    assert isinstance(res_a, ParseSuccess), f"Failed to parse legitimate JSON write_file block: {res_a}"
    assert res_a.tool == "write_file"
    assert res_a.parameters["path"] == "index.html"
    assert "Mission Control" in res_a.parameters["content"]
    
    # Case B: Native tool call
    native_tc = [{
        "id": "tc_12345",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({
                "path": "app.js",
                "content": "console.log('App initialized');"
            })
        }
    }]
    resp_b = NormalizedModelResponse(
        text="Creating app.js...",
        tool_calls=native_tc,
        model="test-native",
        provider="test",
        success=True
    )
    res_b = parser.parse(resp_b)
    print(f"Case B (Native tool call) Result: {type(res_b).__name__} | tool={getattr(res_b, 'tool', None)}")
    assert isinstance(res_b, ParseSuccess), f"Failed to parse legitimate native tool call: {res_b}"
    assert res_b.tool == "write_file"
    assert res_b.parameters["path"] == "app.js"
    assert "console.log" in res_b.parameters["content"]

    # Verify real disk write for legitimate files
    executor = ActionExecutor()
    env_a = ActionEnvelope(action_id="act_legit_a", tool_name=res_a.tool, arguments=res_a.parameters)
    obs_a = asyncio.run(executor.execute_action(env_a, workspace=ws_mgr))
    assert obs_a.success, f"Disk write failed: {obs_a.error}"

    env_b = ActionEnvelope(action_id="act_legit_b", tool_name=res_b.tool, arguments=res_b.parameters)
    obs_b = asyncio.run(executor.execute_action(env_b, workspace=ws_mgr))
    assert obs_b.success, f"Disk write failed: {obs_b.error}"

    # Verify files on disk
    created_files = [f.name for f in PARSER_TEST_WS.iterdir()]
    print(f"Files created on test workspace disk: {created_files}")
    assert "index.html" in created_files
    assert "app.js" in created_files
    assert "Three.js" not in created_files, "ERROR: Three.js was created on disk!"

    # Verify file content
    index_content = (PARSER_TEST_WS / "index.html").read_text(encoding="utf-8")
    assert "mkdir" not in index_content
    assert "npm install" not in index_content
    assert "Mission Control" in index_content
    print("Verified index.html content clean: zero bash commands, valid HTML structure.")
    print("\n[PASS] STEP 2 QUALIFICATION COMPLETE: Anti-corrupt parser guards and valid write_file confirmed!")

if __name__ == "__main__":
    test_parser_adversarial_bash_instructions()
    test_parser_legitimate_structured_write_file()
