"""Adapter for the existing deterministic parser/normalization output.

Phase 7 does not parse configurations. The adapter accepts parser records and
selects only records already marked unmatched, preserving the original line.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Any

@dataclass(frozen=True)
class UnmatchedLine:
    raw_line: str
    vendor: str
    context_path: str | None = None
    line_number: int | None = None
    source_metadata: dict[str, Any] | None = None

def collect_unmatched(parser_records: Iterable[dict[str, Any]]) -> list[UnmatchedLine]:
    out=[]
    for record in parser_records:
        if record.get("matched", False) or record.get("recognized", False):
            continue
        raw=record.get("raw_line", record.get("line"))
        if raw is None:
            continue
        out.append(UnmatchedLine(raw, record["vendor"], record.get("context_path"),
                                  record.get("line_number"), record.get("source_metadata", {})))
    return out
