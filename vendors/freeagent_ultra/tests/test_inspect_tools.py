from freeagent.tools.inspect_tools import inspect_errors


def test_inspect_errors_extracts_summary_and_hints():
    text = """
Traceback (most recent call last):
  File "tests/test_auth.py", line 10, in test_login
AssertionError: expected 401
"""
    result = inspect_errors(text)
    assert "AssertionError" in result["summary"] or "Traceback" in result["summary"]
    assert result["hints"]

