"""Context signal using the existing parser hierarchy/tree output."""
from __future__ import annotations

def _parts(path: str | None) -> list[str]:
    return [p for p in (path or "").strip().split(".") if p]

def context_score(candidate_path: str | None, example_paths: list[str | None]) -> float | None:
    paths = [p for p in example_paths if p]
    if not candidate_path or not paths:
        return None
    c = _parts(candidate_path)
    if not c:
        return None
    best = 0.0
    for p in paths:
        e = _parts(p)
        common = 0
        for a,b in zip(c,e):
            if a != b: break
            common += 1
        best = max(best, common / max(len(c), len(e), 1))
        if c == e:
            best = 1.0
    return best
