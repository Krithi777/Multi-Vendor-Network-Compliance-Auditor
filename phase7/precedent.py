"""Precedent lookup and scoring."""
from __future__ import annotations
import math
from collections import defaultdict
from dataclasses import dataclass

@dataclass(frozen=True)
class Precedent:
    vendor: str
    canonical_field: str
    template_signature: str
    count: int = 1

class PrecedentStore:
    def __init__(self):
        self._counts = defaultdict(int)
    def add(self, vendor, canonical_field, signature, count=1):
        self._counts[(vendor, canonical_field, signature)] += count
    def count(self, vendor, canonical_field, signature):
        return self._counts.get((vendor, canonical_field, signature), 0)
    def score(self, vendor, canonical_field, signature):
        count = self.count(vendor, canonical_field, signature)
        if not count: return 0.0
        max_count = max(
            [v for (ven, field, _), v in self._counts.items()
             if ven == vendor and field == canonical_field] or [count]
        )
        return math.log1p(count) / math.log1p(max_count)
