import re

def count_tokens(text: str) -> int:
    """
    Approximate token count (fallback).
    Works with any text format.
    """
    # Tách theo word + punctuation
    tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
    return len(tokens)