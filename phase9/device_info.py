"""Extracts device identification info from a raw config (Section 6A of
the v2 plan, milestone 11).

Running-configs (what this project ingests) rarely carry model/serial/
OS-version -- those normally live in `show version` / `show inventory`
output, not the saved config. So for every field below: try the
patterns that *do* legitimately show up in a running-config, and return
None rather than guessing when nothing matches. Checked against the
real phase6_dataset fixtures for cisco_ios/juniper_junos/fortios/panos
-- as expected, those fixtures only ever yield a hostname; model/
serial/os_version come back None on all of them, which is the correct,
honest result for that input, not a bug in the extraction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DeviceInfo:
    hostname: str | None = None
    model: str | None = None
    serial_number: str | None = None
    os_version: str | None = None

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname, "model": self.model,
            "serial_number": self.serial_number, "os_version": self.os_version,
        }


def _first_match(pattern: str, text: str, flags=re.MULTILINE | re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip().strip('"') if m else None


def extract_device_info(raw_text: str, vendor: str) -> DeviceInfo:
    # Model names are frequently multi-word ("Cisco Catalyst 9300-24T",
    # "Juniper MX204") -- capture the rest of the comment line, not just
    # the first token, or a real multi-word model silently truncates to
    # its first word. Serial numbers and version strings are always a
    # single token in practice, so those stay on \S+.
    if vendor == "cisco_ios":
        return DeviceInfo(
            hostname=_first_match(r"^hostname\s+(\S+)", raw_text),
            model=_first_match(r"!\s*Model:\s*([^\r\n]+)", raw_text),
            serial_number=_first_match(r"!\s*Serial(?:\s*Number)?:\s*(\S+)", raw_text),
            os_version=_first_match(r"!\s*(?:IOS(?:-XE)?\s+)?Version:\s*([\w.()]+)", raw_text),
        )

    if vendor == "juniper_junos":
        return DeviceInfo(
            hostname=_first_match(r"set\s+system\s+host-name\s+(\S+)", raw_text),
            model=_first_match(r"#\s*Model:\s*([^\r\n]+)", raw_text),
            serial_number=_first_match(r"#\s*Serial(?:\s*Number)?:\s*(\S+)", raw_text),
            os_version=_first_match(r"#\s*(?:JUNOS\s+)?Version:\s*([\w.\-RX]+)", raw_text),
        )

    if vendor == "fortios":
        hostname = _first_match(r"set\s+hostname\s+(\S+)", raw_text)
        if hostname is None:
            # These fixtures use a leading "# <hostname>" comment convention
            # rather than real FortiOS "set hostname" syntax -- honor it as
            # a fallback since it's clearly acting as the hostname here.
            m = re.match(r"^#\s*(\S+)\s*$", raw_text.splitlines()[0] if raw_text else "")
            hostname = m.group(1) if m else None
        model = _first_match(r"set\s+model\s+(\S+)", raw_text)
        if model is None:
            # FortiOS has no real "set model" directive in a running-config
            # export -- fall back to the same "# Model:" comment convention
            # the other four vendors use, instead of only ever returning
            # None for this vendor.
            model = _first_match(r"#\s*Model:\s*([^\r\n]+)", raw_text)
        return DeviceInfo(
            hostname=hostname,
            model=model,
            serial_number=_first_match(r"#\s*Serial(?:\s*Number)?:\s*(\S+)", raw_text),
            os_version=_first_match(r"#\s*(?:FortiOS\s+)?Version:\s*([\w.\-]+)", raw_text),
        )

    if vendor == "panos":
        return DeviceInfo(
            hostname=_first_match(r"set\s+deviceconfig\s+system\s+hostname\s+(\S+)", raw_text),
            model=_first_match(r"#\s*Model:\s*([^\r\n]+)", raw_text),
            serial_number=_first_match(r"#\s*Serial(?:\s*Number)?:\s*(\S+)", raw_text),
            os_version=_first_match(r"#\s*(?:PAN-OS\s+)?Version:\s*([\w.\-]+)", raw_text),
        )

    if vendor == "arista_eos":
        return DeviceInfo(
            hostname=_first_match(r"^hostname\s+(\S+)", raw_text),
            model=_first_match(r"!\s*Model:\s*([^\r\n]+)", raw_text),
            serial_number=_first_match(r"!\s*Serial(?:\s*Number)?:\s*(\S+)", raw_text),
            os_version=_first_match(r"!\s*(?:EOS\s+)?Version:\s*([\w.]+)", raw_text),
        )

    return DeviceInfo()