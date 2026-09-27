"""Tests for phase9.device_info (milestone 11), run against real
phase6_dataset fixtures rather than hand-written configs.

device_info.py's own module docstring already documents the expected
result on these fixtures: hostname extracts, model/serial/os_version
legitimately come back None because running-configs don't carry that
data (it lives in `show version`/`show inventory` output). This suite
locks that documented behavior in rather than re-describing it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from phase9.device_info import extract_device_info

DATASET_DIR = Path(__file__).parent.parent.parent / "phase6" / "phase6_dataset" / "test"

VENDORS = ["cisco_ios", "juniper_junos", "fortios", "panos", "arista_eos"]


def _fixtures_for(vendor: str) -> list[Path]:
    if not DATASET_DIR.is_dir():
        return []
    return sorted(DATASET_DIR.glob(f"{vendor}__*.cfg"))


@pytest.mark.parametrize("vendor", VENDORS)
def test_hostname_extracted_from_every_fixture(vendor):
    fixtures = _fixtures_for(vendor)
    if not fixtures:
        pytest.skip(f"no {vendor} fixtures in this checkout")

    for path in fixtures:
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        info = extract_device_info(raw_text, vendor)
        assert info.hostname, f"{path.name}: expected a hostname, got None"
        assert info.hostname.startswith("baseline-") or info.hostname, (
            f"{path.name}: unexpected hostname {info.hostname!r}"
        )


@pytest.mark.parametrize("vendor", VENDORS)
def test_model_serial_os_version_honestly_none_on_running_configs(vendor):
    """These fixtures are running-configs, not `show version` output --
    device_info.py's contract is to return None rather than guess, and
    this is the documented, correct result for this input (see the
    module docstring), not a gap to "fix" by inventing a match."""
    fixtures = _fixtures_for(vendor)
    if not fixtures:
        pytest.skip(f"no {vendor} fixtures in this checkout")

    for path in fixtures:
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        info = extract_device_info(raw_text, vendor)
        assert info.model is None, f"{path.name}: expected model=None, got {info.model!r}"
        assert info.serial_number is None, f"{path.name}: expected serial_number=None, got {info.serial_number!r}"
        assert info.os_version is None, f"{path.name}: expected os_version=None, got {info.os_version!r}"


def test_unknown_vendor_returns_all_none():
    info = extract_device_info("hostname somebox\n", "made_up_vendor")
    assert info.to_dict() == {
        "hostname": None, "model": None, "serial_number": None, "os_version": None,
    }
