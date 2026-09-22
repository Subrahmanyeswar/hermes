import json
from core.response_parser import ResponseParser, ParseSuccess

def test_parser_baseline_nested_structures():
    parser = ResponseParser()
    cases = [
        ("Direct target probe", '{"tool": "write_file", "parameters": {"path": "test.js", "content": "const x = { a: 1, b: 2 };"}}'),
        ("Nested braces code", json.dumps({"tool": "write_file", "parameters": {"path": "nested.json", "content": '{"a": {"b": {"c": 123}}}'}})),
        ("Array in code", json.dumps({"tool": "write_file", "parameters": {"path": "arr.json", "content": '[1, 2, [3, 4], {"k": [5, 6]}]'}})),
        ("Escaped quotes in code", json.dumps({"tool": "write_file", "parameters": {"path": "quotes.py", "content": 's = "hello \\"world\\""'}})),
        ("Multiline string in code", json.dumps({"tool": "write_file", "parameters": {"path": "multi.py", "content": "def foo():\n    # line 1\n    x = 1\n    return x\n"}})),
        ("Literal braces in code", json.dumps({"tool": "write_file", "parameters": {"path": "fstring.py", "content": 'msg = f"{val}: {status}"'}})),
        ("Python dict in code", json.dumps({"tool": "write_file", "parameters": {"path": "dict.py", "content": 'd = {"key": {"nested": [1, 2, 3]}}'}})),
        ("JS objects in markdown", '```json\n' + json.dumps({"tool": "write_file", "parameters": {"path": "app.js", "content": 'const config = { api: { url: "http://localhost", port: 8080 } };'}}, indent=2) + '\n```'),
        ("Single-quote style Python dict response", "{'tool': 'write_file', 'parameters': {'path': 'sq.py', 'content': 'x = 1'}}")
    ]
    for name, raw in cases:
        res = parser.parse(raw)
        assert isinstance(res, ParseSuccess), f"Failed on {name}: {res}"
        assert res.tool == "write_file"
        assert "content" in res.parameters

if __name__ == "__main__":
    test_parser_baseline_nested_structures()
    print("PARSER_BASELINE = PASS")
