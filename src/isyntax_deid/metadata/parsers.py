# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Helpers for parsing iSyntax XML header values into typed fields."""

import re
from datetime import date
from typing import Optional


def parse_scan_date(datetime_str: Optional[str]) -> Optional[date]:
    """Parse DICOM_ACQUISITION_DATETIME (YYYYMMDDHHMMSS.ffffff) to a date.
    
    The time component is deliberately dropped.
    """
    if not datetime_str:
        return None
    try:
        return date(
            int(datetime_str[0:4]),
            int(datetime_str[4:6]),
            int(datetime_str[6:8]),
        )
    except (ValueError, IndexError):
        return None


def parse_calibration_date(date_str: Optional[str]) -> Optional[date]:
    """Parse DICOM_DATE_OF_LAST_CALIBRATION (YYYYMMDD, possibly quoted)."""
    if not date_str:
        return None
    cleaned = date_str.strip().strip('"').strip()
    try:
        return date(
            int(cleaned[0:4]),
            int(cleaned[4:6]),
            int(cleaned[6:8]),
        )
    except (ValueError, IndexError):
        return None


def parse_derivation_description(description: str) -> dict[str, Optional[int]]:
    """Extract Quality, DWT, Compressor from DICOM_DERIVATION_DESCRIPTION."""
    def _extract_int(key: str) -> Optional[int]:
        match = re.search(rf"{key}\s*=\s*(\d+)", description)
        return int(match.group(1)) if match else None
    
    return {
        "quality_level": _extract_int("Quality"),
        "dwt_level": _extract_int("DWT"),
        "compressor_version": _extract_int("Compressor"),
    }


def parse_software_versions(value: Optional[str]) -> list[str]:
    """Parse '"1.8.6614" "20180906_R51"' into a list."""
    if not value:
        return []
    return re.findall(r'"([^"]+)"', value)


def parse_discrete_values(value: Optional[str]) -> list[str]:
    """Parse space-separated quoted values like '"Y" "Co" "Cg"'."""
    if not value:
        return []
    return re.findall(r'"([^"]+)"', value)


def parse_case_id_and_block(
    barcode: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Split a barcode like 'H.22.0001179.P.A.3.8' into (case_id, block, level)."""
    if not barcode:
        return None, None, None
    
    parts = barcode.split(".")
    if len(parts) < 4:
        return barcode, None, None
    
    case_id = ".".join(parts[:4])
    block = parts[4] if len(parts) > 4 else None
    level = ".".join(parts[5:]) if len(parts) > 5 else None
    return case_id, block, level


def safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value.strip().strip('"'))
    except (ValueError, AttributeError):
        return None


def safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value.strip().strip('"'))
    except (ValueError, AttributeError):
        return None


def safe_bool_from_01(value: Optional[str]) -> bool:
    """Parse '00'/'01' style boolean."""
    if not value:
        return False
    return value.strip().strip('"') == "01"