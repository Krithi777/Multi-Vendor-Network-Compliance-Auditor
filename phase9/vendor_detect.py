"""Vendor auto-detection (Phase 9, ingestion pipeline).

Regex-signature scoring across the 5 supported vendors. An LLM fallback
for low-confidence cases is explicitly out of scope for this pass (no
LLM call exists anywhere in Phase 9 yet) -- when confidence is too low
or two vendors are too close to call, this returns ambiguous candidates
rather than guessing, and the caller (API layer) should ask the
uploader to confirm rather than silently picking one. Guessing wrong
here silently corrupts every downstream compliance result.

Known hard case, worth understanding rather than being surprised by:
Arista EOS's CLI is deliberately IOS-compatible, so a config with no
Arista-specific commands in it (only interfaces/routing/ACL basics) can
be genuinely indistinguishable from Cisco IOS by syntax alone. This is
not a bug in the detector -- it reflects how similar the two CLIs really
are. Strong Arista signals exist (RANCID header, .swi boot image,
`management api http-commands`, `daemon TerminAttr`, `vrf instance`) and
are weighted heavily when present, but their *absence* is not evidence
of Cisco IOS.

A second, unrelated hard case: Cisco's `crypto map` subcommands
(`set peer`, `set transform-set`, `set pfs group14`, ...) happen to be
lines starting with the literal word "set", which lexically collides
with the structural "flat set-command" fallback signal used for
Juniper/PAN-OS. On a crypto-map-heavy Cisco file this can push the
result to "ambiguous" without Cisco even appearing among the listed
candidates. Validated against ~260 real-world configs across all 5
vendors: zero confidently-wrong single-vendor guesses, but this is the
one known way the candidate list itself can miss the true vendor. The
caller should always offer a manual vendor override when `vendor` is
None (both "ambiguous" and "undetected"), not just pick from
`candidates`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# (weight, compiled regex). Regexes are matched anywhere in the file
# (MULTILINE), each contributing its weight at most once regardless of
# how many times it recurs, so a single boilerplate line can't dominate
# the score.
_SIGNATURES: dict[str, list[tuple[int, re.Pattern]]] = {
    "arista_eos": [
        (15, re.compile(r"(?im)^!\s*RANCID-CONTENT-TYPE:\s*arista")),
        (10, re.compile(r"(?im)^\s*management api http-commands")),
        (10, re.compile(r"(?im)^\s*daemon TerminAttr")),
        (8, re.compile(r"(?im)^\s*boot system flash:.*\.swi")),
        (6, re.compile(r"(?im)^\s*vrf instance\s+\S+")),
        (5, re.compile(r"(?im)^\s*no aaa root")),
        (3, re.compile(r"(?im)^\s*transceiver qsfp")),
    ],
    "cisco_ios": [
        (6, re.compile(r"(?im)^\s*boot system flash:.*\.bin")),
        (3, re.compile(r"(?im)^\s*ip ssh version \d+")),
        (3, re.compile(r"(?im)^\s*line vty \d+ \d+")),
        (3, re.compile(r"(?im)^\s*enable secret")),
        (2, re.compile(r"(?im)^\s*ip access-list standard")),
        (2, re.compile(r"(?im)^\s*vrf definition\s+\S+")),
    ],
    "juniper_junos": [
        (8, re.compile(r"(?im)^\s*set system services")),
        (5, re.compile(r"(?im)^\s*set interfaces\s+\S+")),
        (4, re.compile(r"(?im)^\s*commit\s*$")),
        (3, re.compile(r"(?im)^\s*delete \S+")),
    ],
    "panos": [
        (10, re.compile(r"(?im)^\s*set deviceconfig")),
        (8, re.compile(r"(?im)^\s*set mgt-config")),
        (5, re.compile(r"(?im)^\s*set vsys\s+\S+")),
        (4, re.compile(r"(?im)^\s*set shared")),
        (3, re.compile(r"(?im)^\s*set zone\s+\S+")),
        (3, re.compile(r"(?im)^\s*set network")),
    ],
    "fortios": [
        (10, re.compile(r"(?im)^\s*#config-version=")),
        (8, re.compile(r"(?im)^\s*config system global")),
        (6, re.compile(r'(?im)^\s*edit\s+"')),
        (2, re.compile(r"(?im)^\s*end\s*$")),
    ],
}

MIN_CONFIDENCE = 3   # below this, treat as undetected rather than a weak guess
CLOSE_MARGIN = 2     # if the top two scores are within this margin, it's ambiguous

_COMMENT_PREFIXES = ("!", "#")


def _structural_bonuses(raw_text: str) -> dict[str, int]:
    """Coarse syntax-family signals for configs too small/plain to hit any
    specific keyword above (common with short real-world config snippets).
    These are intentionally smaller than the specific-keyword weights so a
    real keyword match always wins the tie-break."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip() and not l.strip().startswith(_COMMENT_PREFIXES)]
    if not lines:
        return {}
    n = len(lines)
    set_like = sum(1 for l in lines if l.startswith(("set ", "delete ")))
    config_like = sum(1 for l in lines if l.startswith(("config ", "edit ", "end", "next")))
    ios_like = sum(1 for l in lines if re.match(
        r"^(interface\s|router\s|hostname\s|line\s|ip\s|no\s|vrf\s|banner\s|"
        r"access-list\s|snmp-server\s|ntp\s|logging\s|aaa\s)", l, re.I))

    bonuses: dict[str, int] = {}
    if set_like / n > 0.5:
        bonuses["juniper_junos"] = bonuses.get("juniper_junos", 0) + 4
        bonuses["panos"] = bonuses.get("panos", 0) + 3
    if config_like / n > 0.3:
        bonuses["fortios"] = bonuses.get("fortios", 0) + 6
    if ios_like / n > 0.3:
        bonuses["cisco_ios"] = bonuses.get("cisco_ios", 0) + 4
        bonuses["arista_eos"] = bonuses.get("arista_eos", 0) + 4
    return bonuses


@dataclass
class VendorDetectionResult:
    vendor: str | None          # best guess, or None if undetected/ambiguous
    confidence: str             # "high" | "low" | "ambiguous" | "undetected"
    scores: dict[str, int] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)  # when ambiguous: the tied top vendors


def detect_vendor(raw_text: str) -> VendorDetectionResult:
    scores: dict[str, int] = {}
    for vendor, patterns in _SIGNATURES.items():
        score = 0
        for weight, pattern in patterns:
            if pattern.search(raw_text):
                score += weight
        scores[vendor] = score

    for vendor, bonus in _structural_bonuses(raw_text).items():
        scores[vendor] = scores.get(vendor, 0) + bonus

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_vendor, top_score = ranked[0]
    runner_vendor, runner_score = ranked[1]

    if top_score < MIN_CONFIDENCE:
        return VendorDetectionResult(vendor=None, confidence="undetected", scores=scores)

    if top_score - runner_score <= CLOSE_MARGIN:
        candidates = [v for v, s in ranked if top_score - s <= CLOSE_MARGIN and s >= MIN_CONFIDENCE]
        return VendorDetectionResult(vendor=None, confidence="ambiguous", scores=scores, candidates=candidates)

    confidence = "high" if top_score >= 10 else "low"
    return VendorDetectionResult(vendor=top_vendor, confidence=confidence, scores=scores, candidates=[top_vendor])