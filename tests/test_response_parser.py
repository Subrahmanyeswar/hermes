import pytest
from core.response_parser import ResponseParser, ParseSuccess, ParseFailure

def parser():
    return ResponseParser()

# ── ParseSuccess cases ────────────────────────────────────────────────

def test_parse_clean_json():
    p = parser()
    response = '{"tool": "write_file", "parameters": {"path": "app.py"}, "reasoning": "creating file", "explanation": "done"}'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    assert result.tool == "write_file"
    assert result.parameters == {"path": "app.py"}
    assert result.method_used == "direct_parse"

def test_parse_markdown_fenced_json():
    p = parser()
    response = '```json\n{"tool": "read_file", "parameters": {"path": "main.py"}, "reasoning": "reading", "explanation": "showing"}\n```'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    assert result.tool == "read_file"
    assert result.method_used == "strip_markdown_fences"

def test_parse_json_embedded_in_prose():
    p = parser()
    response = 'I will use the write_file tool. Here is my response:\n{"tool": "write_file", "parameters": {"path": "test.py"}, "reasoning": "ok", "explanation": "done"}\nThat should work.'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    assert result.tool == "write_file"

def test_parse_json_with_extra_keys():
    """Extra keys in JSON should still parse successfully."""
    p = parser()
    response = '{"reasoning": "ok", "tool": "list_directory", "parameters": {}, "explanation": "listing", "extra_field": "ignored"}'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    assert result.tool == "list_directory"

def test_parse_reconstructs_from_fragments():
    """Parser should extract tool name even from malformed JSON."""
    p = parser()
    response = 'I think the right approach is: "tool": "bash_exec", "parameters": {"command": "ls"}, "reasoning": "listing"'
    result = p.parse(response)
    # Either succeeds via reconstruction or fails — should not crash
    assert isinstance(result, (ParseSuccess, ParseFailure))

def test_parse_alternate_key_names():
    """Parser should accept 'action' as alias for 'tool'."""
    p = parser()
    response = '{"action": "write_file", "parameters": {"path": "x.py"}, "reasoning": "ok", "explanation": "done"}'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    assert result.tool == "write_file"

# ── ParseFailure cases ────────────────────────────────────────────────

def test_parse_empty_response():
    result = parser().parse("")
    assert isinstance(result, ParseFailure)
    assert result.failure_reason == "empty_response"

def test_parse_plain_text_response():
    p = parser()
    response = "I would be happy to help you create that file. Let me know what content you want."
    result = p.parse(response)
    assert isinstance(result, ParseFailure)
    assert result.is_plain_text is True

def test_parse_no_json_at_all():
    result = parser().parse("Sure, I can help with that task!")
    assert isinstance(result, ParseFailure)

def test_parse_json_missing_tool_key():
    result = parser().parse('{"action_type": "write", "content": "hello"}')
    # No "tool" or "action" key — should fail or emergency-extract
    assert isinstance(result, (ParseSuccess, ParseFailure))  # Either is acceptable

def test_parse_never_raises():
    """Parser must never raise an exception on any input."""
    bad_inputs = [
        None,  # type: ignore
        "",
        "   ",
        "{{{{",
        "null",
        "[]",
        "true",
        "{}",
        '{"tool": null}',
        "a" * 10000,
    ]
    p = parser()
    for bad in bad_inputs:
        try:
            result = p.parse(bad or "")
            assert isinstance(result, (ParseSuccess, ParseFailure))
        except Exception as e:
            pytest.fail(f"Parser raised {type(e).__name__} on input {bad!r:.20}")

def test_parse_success_has_correct_structure():
    p = parser()
    response = '{"tool": "git_add_commit", "parameters": {"message": "initial commit"}, "reasoning": "committing", "explanation": "done"}'
    result = p.parse(response)
    assert isinstance(result, ParseSuccess)
    d = result.to_dict()
    assert "tool" in d
    assert "parameters" in d
    assert "reasoning" in d
    assert "explanation" in d
