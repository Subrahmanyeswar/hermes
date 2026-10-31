import re
from pathlib import Path
from typing import Tuple, Optional

def is_placeholder_js(content: str) -> Tuple[bool, str]:
    pattern_func_stub = re.compile(
        r'(?:function\s+([a-zA-Z0-9_$]+)|([a-zA-Z0-9_$]+)\s*\([^)]*\)|class\s+([a-zA-Z0-9_$]+)|(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>)\s*\{\s*(?:\.\.\.|/\*\s*\.\.\.\s*\*/|//\s*(?:\.\.\.|TODO[^\n]*)\s*)\s*\}',
        re.MULTILINE
    )
    m = pattern_func_stub.search(content)
    if m:
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4) or "anonymous"
        return True, f"Incomplete implementation: Function/class '{name}' contains placeholder stub body '{{ ... }}'"

    pattern_block_stub = re.compile(r'\{\s*(?:\.\.\.|/\*\s*\.\.\.\s*\*/)\s*\}')
    m2 = pattern_block_stub.search(content)
    if m2:
        return True, "Incomplete implementation: Contains placeholder block '{ ... }'"
    
    pattern_multiline_stub = re.compile(
        r'(?:function\s+([a-zA-Z0-9_$]+)|([a-zA-Z0-9_$]+)\s*\([^)]*\))\s*\{\s*(?:\r?\n\s*)+(?:\.\.\.|/\*\s*\.\.\.\s*\*/|//\s*\.\.\.)\s*(?:\r?\n\s*)+\}',
        re.MULTILINE
    )
    m3 = pattern_multiline_stub.search(content)
    if m3:
        name = m3.group(1) or m3.group(2) or "anonymous"
        return True, f"Incomplete implementation: Function '{name}' contains multi-line placeholder body '{{ ... }}'"

    return False, ""


def validate_implementation_completeness(content: str, filename: str) -> Tuple[bool, Optional[str]]:
    norm_fn = Path(filename).name.lower()
    is_code = norm_fn.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
    if not is_code:
        return True, None
    
    is_stub, reason = is_placeholder_js(content)
    if is_stub:
        return False, reason
        
    clean_lines = []
    in_block_comment = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
                stripped = stripped.split("*/", 1)[1].strip()
            else:
                continue
        if stripped.startswith("/*"):
            if "*/" in stripped:
                stripped = stripped.split("*/", 1)[1].strip()
            else:
                in_block_comment = True
                continue
        if stripped.startswith("//"):
            continue
        if stripped:
            clean_lines.append(stripped)
            
    if not clean_lines:
        return False, f"Incomplete implementation: File '{norm_fn}' contains only comments or whitespace with no executable statements."

    return True, None

# Test comment only
res, err = validate_implementation_completeness("// Just a comment\n/* Another comment */", "main.js")
print("Comment only test:", res, err)
assert res is False

# Test real code
real_code = "import * as THREE from 'three';\nconst scene = new THREE.Scene();\nexport { scene };"
res, err = validate_implementation_completeness(real_code, "main.js")
print("Real code test:", res, err)
assert res is True
print("validate_implementation_completeness tests passed!")
