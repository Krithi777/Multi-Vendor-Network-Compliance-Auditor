"""Bulk multi-file ingestion orchestration (Phase 9, milestone 11,
Section 6B of the v2 plan).

Every file in a batch goes through the *exact same* per-scan pipeline as
a single /api/ingest upload -- vendor detect -> sanitize -> normalize ->
diff -> device info. There is no separate "bulk" code path inside the
pipeline itself; this module only handles what's genuinely different
about receiving several files in one request:

- validating the batch as a whole (file count, non-empty, each file
  decodes as UTF-8) before committing to processing any of it
- decoding each upload's bytes once, up front, so a bad file fails loud
  and early instead of surfacing as a mystery "error" status three
  files into a background task queue

api.py still owns allocating scan_ids and scheduling the background
work (it already has that machinery from milestone 4) -- this module
just gives it a clean, pre-validated list to iterate over.
"""
from __future__ import annotations

from dataclasses import dataclass

# Generous for a hackathon-length demo; exists only to stop an
# accidental 500-file drop from wedging the background task queue behind
# one giant batch. Not a hard product requirement.
MAX_BULK_FILES = 25


class BulkValidationError(Exception):
    """Raised for problems with the batch as a whole or an individual
    file in it -- callers should turn this into a 400, not a 500."""


@dataclass
class DecodedUpload:
    filename: str
    raw_text: str


def validate_batch_size(file_count: int) -> None:
    if file_count == 0:
        raise BulkValidationError("No files provided.")
    if file_count > MAX_BULK_FILES:
        raise BulkValidationError(
            f"Too many files in one batch ({file_count}); max is {MAX_BULK_FILES}."
        )


def decode_upload(filename: str | None, raw_bytes: bytes) -> DecodedUpload:
    """Decodes one upload's bytes as UTF-8 text. Raised errors carry the
    filename so a bad file in a batch of 10 is reported by name, not as
    an anonymous 400."""
    name = filename or "unknown"
    try:
        return DecodedUpload(filename=name, raw_text=raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise BulkValidationError(f"{name} is not valid UTF-8 text.") from exc


def decode_batch(files: list[tuple[str | None, bytes]]) -> list[DecodedUpload]:
    """Validates batch size, then decodes every file. Raises on the
    first problem found (size or decode) rather than partially
    processing a batch that's already known to be invalid -- consistent
    with /api/ingest's existing behavior of rejecting a bad file before
    creating a scan row for it."""
    validate_batch_size(len(files))
    return [decode_upload(filename, raw_bytes) for filename, raw_bytes in files]
