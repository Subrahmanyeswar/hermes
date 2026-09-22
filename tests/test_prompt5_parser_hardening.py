import pytest
import json
from core.response_parser import ResponseParser, ParseSuccess, ParseFailure


@pytest.fixture
def parser():
    return ResponseParser()


# ── Clean & Structured Outputs ───────────────────────────────────────────────

def test_parse_clean_direct_json(parser):
    payload = '{"tool": "write_file", "parameters": {"path": "main.py", "content": "print(1)"}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_file"
    assert res.parameters["path"] == "main.py"
    assert res.method_used == "direct_parse"


def test_parse_markdown_fenced_json(parser):
    payload = '```json\n{"tool": "read_file", "parameters": {"path": "config.json"}}\n```'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "read_file"
    assert res.method_used == "strip_markdown_fences"


def test_parse_json_embedded_in_prose(parser):
    payload = 'Sure, here is the command:\n{"tool": "list_directory", "parameters": {"path": "."}}\nHope this helps!'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "list_directory"
    assert res.method_used == "extract_first_json_object"


def test_parse_single_quotes_json(parser):
    payload = "{'tool': 'read_file', 'parameters': {'path': 'test.txt'}}"
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "read_file"
    assert res.parameters["path"] == "test.txt"


def test_parse_with_think_tags(parser):
    payload = '<think>Planning to write file</think>\n{"tool": "write_file", "parameters": {"path": "a.py", "content": "x=1"}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_file"
    assert res.reasoning == "Planning to write file"


# ── Unknown Tool Rejection (Hardening) ─────────────────────────────────────────

def test_reject_unknown_tool_hallucination(parser):
    payload = '{"tool": "teleport_to_mars", "parameters": {"speed": 100}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)
    assert "unknown_tool_rejected" in res.failure_reason


def test_reject_hallucinated_action_name(parser):
    payload = '{"action": "destroy_all_humans", "parameters": {}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


def test_allow_registered_tool_aliases(parser):
    # list_files is an accepted historical alias in ResponseParser
    payload = '{"tool": "list_files", "parameters": {"path": "."}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "list_files"


def test_allow_action_alias(parser):
    payload = '{"action": "write_file", "parameters": {"path": "test.py", "content": "pass"}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_file"


# ── JSON-in-Content Injection Defense ────────────────────────────────────────

def test_json_in_file_content_preserved_as_string(parser):
    # File content itself contains a fake tool call payload
    inner_json = json.dumps({"tool": "delete_file", "parameters": {"path": "passwords.txt"}})
    payload = f'{{"tool": "write_file", "parameters": {{"path": "sample.json", "content": {json.dumps(inner_json)}}}}}'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_file"
    assert res.parameters["path"] == "sample.json"
    assert res.parameters["content"] == inner_json


def test_nested_braces_in_code_content_not_breaking_parser(parser):
    code = "function test() {\n    if (true) {\n        return { a: 1, b: 2 };\n    }\n}"
    payload = f'I will write this code:\n{{"tool": "write_file", "parameters": {{"path": "script.js", "content": {json.dumps(code)}}}}}\nDone.'
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_file"
    assert res.parameters["content"] == code


# ── Placeholder Content Rejection ────────────────────────────────────────────

def test_reject_write_file_demo_placeholders(parser):
    for ph in ("full content here", "the code string", "# full content here", "// full content here"):
        payload = f'{{"tool": "write_file", "parameters": {{"path": "foo.py", "content": "{ph}"}}}}'
        res = parser.parse(payload)
        assert isinstance(res, ParseFailure)


# ── write_files_batch Parser Validation ──────────────────────────────────────

def test_parse_write_files_batch_single_file(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "index.html", "content": "<h1>Hello</h1>"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_files_batch"
    assert len(res.parameters["files"]) == 1


def test_parse_write_files_batch_two_files(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "index.html", "content": "<h1>Hello</h1>"},
                {"path": "style.css", "content": "body { margin: 0; }"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_files_batch"
    assert len(res.parameters["files"]) == 2


def test_parse_write_files_batch_three_files(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "index.html", "content": "<h1>Hello</h1>"},
                {"path": "style.css", "content": "body { margin: 0; }"},
                {"path": "app.js", "content": "console.log(1);"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseSuccess)
    assert res.tool == "write_files_batch"
    assert len(res.parameters["files"]) == 3


def test_reject_write_files_batch_zero_files(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": []
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


def test_reject_write_files_batch_four_files(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "f1.txt", "content": "1"},
                {"path": "f2.txt", "content": "2"},
                {"path": "f3.txt", "content": "3"},
                {"path": "f4.txt", "content": "4"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


def test_reject_write_files_batch_duplicate_paths(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "app.py", "content": "print(1)"},
                {"path": "./app.py", "content": "print(2)"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


def test_reject_write_files_batch_placeholder_content(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "app.py", "content": "print(1)"},
                {"path": "util.py", "content": "# full content here"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


def test_reject_write_files_batch_missing_path(parser):
    payload = json.dumps({
        "tool": "write_files_batch",
        "parameters": {
            "files": [
                {"path": "", "content": "print(1)"}
            ]
        }
    })
    res = parser.parse(payload)
    assert isinstance(res, ParseFailure)


# ── Adversarial & Robustness Checks ──────────────────────────────────────────

def test_parser_never_crashes_on_adversarial_inputs(parser):
    adversarial = [
        "",
        "    ",
        None,
        "{{{{",
        "}}}}",
        '{"tool": ',
        '{"tool": "write_file"',
        '{"tool": "write_file", "parameters": {',
        "\x00\x01\x02",
        "null",
        "[]",
        "12345",
        "true",
        "NaN",
        "{'unclosed quote: 123}",
    ]
    for adv in adversarial:
        res = parser.parse(adv)
        assert isinstance(res, (ParseSuccess, ParseFailure))
        if isinstance(res, ParseFailure):
            assert res.failure_reason != ""
