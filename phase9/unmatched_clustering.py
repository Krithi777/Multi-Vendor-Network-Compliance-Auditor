"""Groups unmatched config lines into teachable clusters (Phase 9, milestone 10).

Phase 7's teaching loop wants 3-4 examples of the *same* canonical_field so
it can induce one syntax template -- handing the admin a flat, unordered
list of unmatched lines (the old `/api/unmatched` shape) makes them do that
grouping by eye. This module does it for them, deterministically, with no
model involved: same idea as `phase7.template_induction.induce_template`,
just run in reverse (group first, teach second) and without requiring 3
confirmed examples up front.

Clustering key is (context_category, skeleton) -- NOT skeleton alone. This
is deliberate and mirrors the FortiOS gotcha called out in the Phase 9 plan
(Section 6): `set server \\S+` matches both syslog and NTP server lines, so
two lines with an identical skeleton in different config blocks must land
in different clusters, or teaching one would silently "generalize" over
the other.

A line is masked to `{V}` in the skeleton if it looks like a value rather
than syntax: contains a digit, is an ALL-CAPS identifier (the vendor's
convention for named ACLs/VLANs/policies -- see SentinelGrid's own
`VLAN-MGMT` / `CORE-RESTRICT` example), or contains IPv6-style colons.
Everything else (keywords like `ip`, `access-group`, `in`, `lacp`) is
treated as fixed syntax and drives the grouping.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from phase7.tokenizer import normalize_tokens, tokenize_cli

_HEX_COLON = re.compile(r"^[0-9a-fA-F:]+$")


def _looks_like_value(token: str) -> bool:
    if any(ch.isdigit() for ch in token):
        return True
    if ":" in token and _HEX_COLON.match(token):
        return True
    letters = [c for c in token if c.isalpha()]
    if letters and token == token.upper() and len(letters) >= 2:
        return True
    return False


def skeleton_of(raw_line: str) -> str:
    """Deterministic structural signature used to group similar lines."""
    tokens = normalize_tokens(tokenize_cli(raw_line))
    masked: list[str] = []
    for tok in tokens:
        masked.append("{V}" if _looks_like_value(tok) else tok.lower())
    collapsed: list[str] = []
    for tok in masked:
        if tok == "{V}" and collapsed and collapsed[-1] == "{V}":
            continue
        collapsed.append(tok)
    return " ".join(collapsed)


@dataclass
class UnmatchedMember:
    raw_line: str
    line_number: int | None
    context_path: str | None


@dataclass
class ClusterInfo:
    cluster_id: str
    context_category: str
    skeleton: str
    representative_line: str
    members: list[UnmatchedMember] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.members)


def _cluster_id(context_category: str, skeleton: str) -> str:
    digest = hashlib.sha256(f"{context_category}\x1f{skeleton}".encode("utf-8")).hexdigest()
    return digest[:12]


def cluster_unmatched_lines(unmatched: list[dict]) -> list[ClusterInfo]:
    """Groups Phase 9 normalizer `unmatched` dicts (raw_line/line_number/
    context_path) into ClusterInfo buckets, largest first. Ties break by
    the lowest line_number seen, so the ordering is stable across calls
    for the same input (important since this is recomputed on demand,
    not cached -- see phase9.api._get_clusters_for_scan)."""
    buckets: dict[str, ClusterInfo] = {}
    for entry in unmatched:
        raw_line = entry.get("raw_line") or entry.get("line") or ""
        if not raw_line.strip():
            continue
        context_category = entry.get("context_path") or "global"
        skeleton = skeleton_of(raw_line)
        cid = _cluster_id(context_category, skeleton)
        member = UnmatchedMember(
            raw_line=raw_line,
            line_number=entry.get("line_number"),
            context_path=entry.get("context_path"),
        )
        if cid not in buckets:
            buckets[cid] = ClusterInfo(
                cluster_id=cid,
                context_category=context_category,
                skeleton=skeleton,
                representative_line=raw_line,
                members=[member],
            )
        else:
            buckets[cid].members.append(member)

    def _sort_key(c: ClusterInfo):
        line_numbers = [m.line_number for m in c.members if m.line_number is not None]
        first_seen = min(line_numbers) if line_numbers else 0
        return (-c.count, first_seen)

    return sorted(buckets.values(), key=_sort_key)


def find_cluster_for_line(clusters: list[ClusterInfo], raw_line: str) -> ClusterInfo | None:
    for c in clusters:
        if any(m.raw_line == raw_line for m in c.members):
            return c
    return None


def context_breakdown(clusters: list[ClusterInfo]) -> dict[str, int]:
    """Real counts, not a hardcoded legend -- used by the frontend to
    label the coverage bar with what kind of config sections are still
    unresolved (e.g. '14 interfaces · 6 management')."""
    counts: Counter[str] = Counter()
    for c in clusters:
        counts[c.context_category] += c.count
    return dict(counts)
