import sys
sys.path.insert(0, ".")
from core.response_parser import ResponseParser

parser = ResponseParser()

# Case A: Standard response only
resA = parser.parse('{"tool": "write_file", "parameters": {"path": "a.py", "content": "print(1)"}}')
print("Case A:", type(resA).__name__, getattr(resA, "tool", None) or getattr(resA, "failure_reason", None))

# Case B: Thinking only containing JSON tool call
thinking_content = 'Let me create a.py\n{"tool": "write_file", "parameters": {"path": "a.py", "content": "print(1)"}}'
resB = parser.parse(f"<think>\n{thinking_content}\n</think>")
print("Case B:", type(resB).__name__, getattr(resB, "tool", None) or getattr(resB, "failure_reason", None), "Reasoning:", bool(getattr(resB, "reasoning", None)))

# Case C: Thinking + Response
resC = parser.parse('<think>\nLet us analyze the problem\n</think>\n{"tool": "write_file", "parameters": {"path": "a.py", "content": "print(1)"}}')
print("Case C:", type(resC).__name__, getattr(resC, "tool", None) or getattr(resC, "failure_reason", None), "Reasoning:", getattr(resC, "reasoning", None))

# Case D: Empty thinking + non-empty response
resD = parser.parse('{"tool": "write_file", "parameters": {"path": "a.py", "content": "print(1)"}}')
print("Case D:", type(resD).__name__, getattr(resD, "tool", None) or getattr(resD, "failure_reason", None))

# Case G: Both empty
resG = parser.parse("")
print("Case G:", type(resG).__name__, getattr(resG, "failure_reason", None))
