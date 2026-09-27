"""Vendor-agnostic normalization layer (Phase 9, decision step 1).

Every other Phase 9 feature (compliance diff, evidence pass/fail,
remediation, unmatched detection) reads from the NormalizedConfig this
module produces rather than touching raw vendor syntax directly.

Design notes (see build conversation for the full reasoning):
- Juniper Junos and PAN-OS configs are already "flat" -- each line is a
  fully-qualified `set a b c ...` command, so the vendor_mappings
  match_regex alone is sufficient; no block/indent tracking is needed.
- Cisco IOS / Arista EOS use indentation to nest lines under a block
  header (`interface X`, `line vty 0 4`, ...).
- FortiOS uses explicit `config ... end` blocks, with `edit ... next`
  sub-blocks that iterate instances of the same category (e.g. multiple
  interfaces) without changing the category itself.
- Rather than requiring an exact string match between the derived block
  category and vendor_mappings' free-text `context_path` label, labels are
  normalized first (stripping `<unused>`/`(mgmt)`-style annotations and
  expanding "a / b" alternatives), then matched exactly against the
  category derived from the real config structure. If a rule's category
  genuinely doesn't occur in a file, that is treated as the field being
  absent (MISSING) -- it is not widened to "any nested block", because
  doing so re-introduces false positives across unrelated nested blocks
  (verified against the Phase 6 labeled fixtures). If category tracking
  ever misses a real-world config's structure, the affected line simply
  surfaces in `unmatched` for the Phase 7 human-in-the-loop teaching
  loop, rather than being silently misattributed.
"""
from __future__ import annotations

import hashlib
import re as _re
from dataclasses import dataclass, field
from typing import Any

from .mapping_loader import FieldRule, RuleTables, get_default_tables, FLAT_VENDORS, BLOCK_VENDORS

GLOBAL_CATEGORY = "global"


def _normalize_labels(context_path: str | None) -> list[str]:
    """Turns a vendor_mappings context_path into one or more concrete,
    comparable block-category labels.

    - "global" / "system" (top-level scope)          -> [GLOBAL_CATEGORY]
    - "interface <unused>" / "interface <routed>"    -> ["interface"]
    - "system interface (mgmt)"                       -> ["system interface"]
    - "system snmp user / community"                 -> ["system snmp user",
                                                           "system snmp community"]
    - "log syslogd setting" (already concrete)        -> ["log syslogd setting"]
    """
    if not context_path:
        return [GLOBAL_CATEGORY]
    s = context_path.strip().lower()
    if s in ("global", "system"):
        return [GLOBAL_CATEGORY]
    s = _re.sub(r"<[^>]*>", "", s)
    s = _re.sub(r"\([^)]*\)", "", s)
    s = " ".join(s.split())
    if "/" in s:
        parts = [p.strip() for p in s.split("/") if p.strip()]
        if not parts:
            return [GLOBAL_CATEGORY]
        prefix_tokens = parts[0].split()
        labels = [parts[0]]
        if len(prefix_tokens) > 1:
            common_prefix = " ".join(prefix_tokens[:-1])
            labels.extend(f"{common_prefix} {extra}".strip() for extra in parts[1:])
        else:
            labels.extend(parts[1:])
        return labels
    return [s] if s else [GLOBAL_CATEGORY]


@dataclass(frozen=True)
class LineCtx:
    line_number: int
    raw_line: str
    category: str  # GLOBAL_CATEGORY or a derived nested-block token


@dataclass
class MatchedField:
    canonical_field: str
    control_id: str
    vendor: str
    raw_line: str
    line_number: int
    context_category: str
    matched_pass_literal: bool   # raw line == known pass_line exactly
    matched_fail_literal: bool   # raw line == known fail_line exactly
    extracted_value: Any = None  # best-effort captured value, or None


@dataclass
class NormalizedConfig:
    vendor: str
    sha256: str
    # canonical_field -> MatchedField. Only one match kept per field
    # (first match wins; duplicate/conflicting lines are rare in a single
    # device config and, if present, the earliest wins deterministically).
    fields: dict[str, MatchedField] = field(default_factory=dict)
    # Lines the deterministic matcher could not tie to any canonical_field.
    # Shape matches what phase7.parser_adapter.collect_unmatched expects.
    unmatched: list[dict] = field(default_factory=list)
    total_lines: int = 0


def _scope_kind(context_path: str | None) -> str:
    """Coarse global-vs-nested classification of a vendor_mappings context_path."""
    if not context_path:
        return GLOBAL_CATEGORY
    base = context_path.strip().lower()
    if base in ("global", "system"):
        return GLOBAL_CATEGORY
    return "nested"


def _header_category_cisco(line: str) -> str | None:
    """Returns a block category for an unindented Cisco/Arista header line,
    or None if the line is not a recognized block opener (i.e. stays global)."""
    s = line.strip()
    if s.startswith("interface "):
        return "interface"
    if s.startswith("line "):
        return s  # e.g. "line vty 0 4", "line con 0" -- kept verbatim
    if s.startswith("router "):
        return s
    if s.startswith("ip access-list") or s.startswith("ipv6 access-list"):
        return s
    return None


def _iter_cisco_style(text: str) -> list[LineCtx]:
    out: list[LineCtx] = []
    current_category = GLOBAL_CATEGORY
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        if raw[0] not in (" ", "\t"):
            stripped = raw.strip()
            if stripped in ("end", "exit"):
                current_category = GLOBAL_CATEGORY
                continue
            opened = _header_category_cisco(stripped)
            if opened is not None:
                current_category = opened
                out.append(LineCtx(i, raw, GLOBAL_CATEGORY))
                continue
            current_category = GLOBAL_CATEGORY
            out.append(LineCtx(i, raw, GLOBAL_CATEGORY))
            continue
        out.append(LineCtx(i, raw, current_category if current_category != GLOBAL_CATEGORY else "nested-unlabeled"))
    return out


def _iter_fortios(text: str) -> list[LineCtx]:
    out: list[LineCtx] = []
    stack: list[str] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("config "):
            stack.append(s[len("config "):].strip())
            continue
        if s == "end":
            if stack:
                stack.pop()
            continue
        if s.startswith("edit ") or s == "next":
            continue
        category = " ".join(stack) if stack else GLOBAL_CATEGORY
        out.append(LineCtx(i, raw, category))
    return out


def _iter_flat(text: str) -> list[LineCtx]:
    # Juniper / PAN-OS: every line is self-contained; category is irrelevant
    # to matching (kept as GLOBAL_CATEGORY so the scope gate never blocks it).
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        out.append(LineCtx(i, raw, GLOBAL_CATEGORY))
    return out


def _tokenize(vendor: str, text: str) -> list[LineCtx]:
    if vendor in FLAT_VENDORS:
        return _iter_flat(text)
    if vendor == "fortios":
        return _iter_fortios(text)
    if vendor in ("cisco_ios", "arista_eos"):
        return _iter_cisco_style(text)
    raise KeyError(f"No tokenizer for vendor: {vendor!r}")


def _extract_value(raw_line: str, rule: FieldRule) -> Any:
    """Best-effort value extraction for lines that matched the regex but
    are not an exact literal match to the known pass_line/fail_line.
    Uses the regex's own capture group when the vendor_mappings author
    provided one; otherwise returns None (caller falls back to flagging
    the line for review rather than guessing)."""
    if rule.match_regex is None:
        return None
    m = rule.match_regex.match(raw_line.strip())
    if m and m.lastindex is not None:
        return m.group(m.lastindex)
    return None


def normalize_config(raw_text: str, vendor: str, tables: RuleTables | None = None) -> NormalizedConfig:
    tables = tables or get_default_tables()
    rules = tables.rules_for_vendor(vendor)
    lines = _tokenize(vendor, raw_text)

    fields: dict[str, MatchedField] = {}
    matched_line_numbers: set[int] = set()

    for rule in rules:
        if rule.match_regex is None or rule.always_compliant:
            continue
        labels = _normalize_labels(rule.context_path)
        is_global_rule = labels == [GLOBAL_CATEGORY]

        def _label_ok(ctx: LineCtx) -> bool:
            if vendor not in BLOCK_VENDORS:
                return True
            if is_global_rule:
                return ctx.category == GLOBAL_CATEGORY
            return ctx.category.lower() in labels

        candidates = [ctx for ctx in lines if _label_ok(ctx)]

        for ctx in candidates:
            candidate = ctx.raw_line.strip()
            if not rule.match_regex.match(candidate):
                continue
            if rule.canonical_field in fields:
                break  # first match wins for this field
            stripped_pass = (rule.pass_line or "").strip()
            stripped_fail = (rule.fail_line or "").strip()
            fields[rule.canonical_field] = MatchedField(
                canonical_field=rule.canonical_field,
                control_id=rule.control_id,
                vendor=vendor,
                raw_line=ctx.raw_line,
                line_number=ctx.line_number,
                context_category=ctx.category,
                matched_pass_literal=(candidate == stripped_pass and bool(stripped_pass)),
                matched_fail_literal=(candidate == stripped_fail and bool(stripped_fail)),
                extracted_value=_extract_value(ctx.raw_line, rule),
            )
            matched_line_numbers.add(ctx.line_number)
            break

    unmatched = []
    for ctx in lines:
        if ctx.line_number in matched_line_numbers:
            continue
        unmatched.append({
            "raw_line": ctx.raw_line,
            "line": ctx.raw_line,
            "vendor": vendor,
            "matched": False,
            "recognized": False,
            "context_path": ctx.category,
            "line_number": ctx.line_number,
            "source_metadata": {},
        })

    return NormalizedConfig(
        vendor=vendor,
        sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        fields=fields,
        unmatched=unmatched,
        total_lines=len(lines),
    )