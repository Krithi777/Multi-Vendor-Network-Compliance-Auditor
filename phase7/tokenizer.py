"""Vendor-aware, quote-preserving CLI tokenization without implementing a parser."""
from __future__ import annotations
import shlex
import re

def tokenize_cli(line: str, vendor: str | None = None) -> list[str]:
    """Tokenize while preserving quoted values as one logical token.

    shlex is used only for lexical tokenization; vendor parsing remains in the
    existing deterministic parser. A fallback scanner preserves malformed quotes.
    """
    if line is None:
        return []
    try:
        return shlex.split(line.strip(), posix=True)
    except ValueError:
        # Do not crash on an unmatched quote in an audit input.
        return re.findall(r'"[^"]*"|\'[^\']*\'|\S+', line.strip())

def normalize_tokens(tokens: list[str]) -> list[str]:
    """Safe normalization only: trim surrounding whitespace and quote wrappers."""
    return [t.strip() for t in tokens if t.strip()]
