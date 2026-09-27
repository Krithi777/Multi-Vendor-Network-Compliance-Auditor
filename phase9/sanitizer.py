"""Sanitizer (Phase 9, decision step 2 -- ingestion pipeline).

Two distinct jobs, kept deliberately separate:

1. `sanitize_config()` -- produces a redacted copy of a whole config file
   for storage/display/download. This is what gets persisted to
   `device_configs.sanitized_text` and offered as a download; the
   original raw text is never stored unredacted at rest.

2. `redact_line()` -- redacts a *single* line. This exists because the
   normalizer/compliance-diff engine MUST run against the real,
   unredacted config (a compliance check on "***REDACTED***" instead of
   the actual SSH version number is meaningless) -- but a handful of
   controls' evidence lines legitimately contain a real secret in the
   matched line itself (e.g. CTRL-006 TACACS+ key, CTRL-012 NTP MD5 key,
   CTRL-013 SNMP auth/priv passwords). Before an EvidenceResult's
   `evidence_line` is persisted or returned by the API, run it through
   `redact_line()` -- parse first with the real value, then redact only
   at the point of storage/display.

Report shape intentionally matches the existing Phase 3
`_sanitize_reports/<vendor>/<file>.sanitize_report.json` convention
(source_file, sanitized_file, vendor, sha256_original, sha256_sanitized,
redactions, clean) so tooling built against that shape keeps working.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

REDACTED = "***REDACTED***"

# (label, compiled regex). Each regex has exactly one capture group: the
# sensitive token to redact. Deliberately generic across all 5 vendors
# (keyword-based, not vendor-specific syntax) so it also catches secret
# directives that aren't part of the 20-control schema at all -- a
# sanitizer's job is broader than a compliance checker's.
_LINE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("enable_secret", re.compile(r"(?i)^(\s*enable\s+secret(?:\s+\d+)?\s+)(\S+)")),
    ("enable_password", re.compile(r"(?i)^(\s*enable\s+password\s+)(\S+)")),
    ("user_password", re.compile(r"(?i)^(\s*username\s+\S+\s+(?:secret|password)(?:\s+\d+)?\s+)(\S+)")),
    ("generic_password", re.compile(r"(?i)^(\s*(?:set\s+)?(?:passwd|password|priv-pwd|auth-pwd)\s+)(\S+)")),
    ("psk", re.compile(r"(?i)^(\s*set\s+(?:psksecret|preshared-key|pre-shared-key)\s+)(\S+)")),
    ("snmp_community", re.compile(r"(?i)^(\s*snmp-server\s+community\s+)(\S+)")),
    ("tacacs_radius_key", re.compile(r"(?i)^(\s*(?:tacacs-server|radius-server)\s+(?:key|host\s+\S+\s+key)\s+)(\S+)")),
    ("tacacs_key_fortios", re.compile(r"(?i)^(\s*set\s+key\s+)(\S+)")),
    ("ntp_auth_key", re.compile(r"(?i)^(\s*ntp\s+authentication-key\s+\d+\s+md5\s+)(\S+)")),
    ("root_auth_password", re.compile(r"(?i)^(\s*set\s+system\s+root-authentication\s+(?:encrypted-)?password\s+)(\S+)")),
    ("password_hash", re.compile(r"(?i)^(\s*set\s+mgt-config\s+users\s+\S+\s+password-hash\s+)(\S+)")),
    ("secret_generic_key", re.compile(r"(?i)^(\s*set\s+.*\bsecret\s+)(\S+)")),
]

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
    re.DOTALL,
)


@dataclass
class Redaction:
    line_number: int
    label: str
    original_length: int


@dataclass
class SanitizeResult:
    sanitized_text: str
    vendor: str
    sha256_original: str
    sha256_sanitized: str
    redactions: list[Redaction] = field(default_factory=list)
    clean: bool = True

    def to_report(self, source_file: str = "", sanitized_file: str = "") -> dict:
        return {
            "source_file": source_file,
            "sanitized_file": sanitized_file,
            "vendor": self.vendor,
            "sha256_original": self.sha256_original,
            "sha256_sanitized": self.sha256_sanitized,
            "redactions": [r.__dict__ for r in self.redactions],
            "clean": self.clean,
        }


def redact_line(raw_line: str) -> tuple[str, str | None]:
    """Redacts one line if it matches a known secret pattern.
    Returns (possibly-redacted line, label or None if untouched)."""
    for label, pattern in _LINE_PATTERNS:
        m = pattern.match(raw_line)
        if m:
            return raw_line[:m.end(1)] + REDACTED + raw_line[m.end(2):], label
    return raw_line, None


def sanitize_config(raw_text: str, vendor: str) -> SanitizeResult:
    sha256_original = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    # PEM certificate/private-key blocks span multiple lines and must be
    # collapsed before line-by-line redaction, or their contents (which
    # don't look like "password X") would pass straight through.
    pem_hits = 0

    def _pem_sub(m: re.Match) -> str:
        nonlocal pem_hits
        pem_hits += 1
        return f"***REDACTED PEM BLOCK ({pem_hits})***"

    text_no_pem = _PEM_BLOCK_RE.sub(_pem_sub, raw_text)

    redactions: list[Redaction] = []
    out_lines = []
    for i, line in enumerate(text_no_pem.splitlines(), start=1):
        if line.startswith("***REDACTED PEM BLOCK"):
            redactions.append(Redaction(line_number=i, label="pem_block", original_length=len(line)))
            out_lines.append(line)
            continue
        redacted_line, label = redact_line(line)
        if label:
            redactions.append(Redaction(line_number=i, label=label, original_length=len(line)))
        out_lines.append(redacted_line)

    sanitized_text = "\n".join(out_lines)
    sha256_sanitized = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()

    return SanitizeResult(
        sanitized_text=sanitized_text,
        vendor=vendor,
        sha256_original=sha256_original,
        sha256_sanitized=sha256_sanitized,
        redactions=redactions,
        clean=(len(redactions) == 0),
    )