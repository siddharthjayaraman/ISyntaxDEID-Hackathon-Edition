# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Per-file metadata extraction from iSyntax files.

This module is DB-free so it can be called in parallel worker processes.
"""

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from tile_pyisyntax import ISyntaxWSI
from isyntax_deid.metadata.schemas import (
	CompressionInfo, DimensionInfo, ImageGeometry, MapFileEntry,
	PixelFormat, PostProcessing, Provenance, ScannerInfo,
)
from isyntax_deid.metadata import parsers

def _read_xml_header(path: Path, max_bytes: int = 100_000_000) -> str:
	"""Read the raw XML header from an iSyntax file."""
	with open(path, "rb") as f:
		data = f.read(max_bytes)
	
	start = data.find(b"<?xml")
	if start == -1:
		raise ValueError(f"No XML header found in {path}")
	
	end_tag = b"</DataObject>"
	end = data.rfind(end_tag)
	if end == -1:
		raise ValueError(
			f"XML header end not found in first {max_bytes} bytes of {path}"
		)
	end += len(end_tag)
	return data[start:end].decode("utf-8", errors="replace")

def _get_xml_attrs(path: Path) -> dict[str, str]:
	"""Parse iSyntax XML header into a flat attribute dict."""
	xml_str = _read_xml_header(path)
	root = ET.fromstring(xml_str)
	
	attrs: dict[str, str] = {}
	for attr in root.iter("Attribute"):
		name = attr.get("Name")
		if name and attr.text and name not in attrs:
			attrs[name] = attr.text.strip()
	return attrs

def extract_metadata(slide_path: Path, pipeline_version: str, libisyntax_version: str, slide_id: str) -> MapFileEntry:
	"""Extract all metadata from one iSyntax file into a MapFileEntry.

	Args:
		slide_path: path to the .isyntax file
		pipeline_version: version tag of this pipeline (for provenance)
		libisyntax_version: version of the libisyntax .so in use
		slide_id: identifier for the slide, supplied by the caller (e.g. the
			output stem). Not derived from the slide itself.

	Returns:
		A fully-populated MapFileEntry (geometry + scanner/compression metadata
		parsed from the XML header). Label-image OCR is not part of this build.
	"""
	slide_path = Path(slide_path).resolve()
	if not slide_path.is_file():
		raise FileNotFoundError(f"Slide not found: {slide_path}")

	# XML attributes
	attrs = _get_xml_attrs(slide_path)

	# libisyntax-derived info
	with ISyntaxWSI(str(slide_path)) as wsi:
		# Public/research slides often carry no barcode; treat it as optional.
		barcode = wsi.get_barcode() or ""
		case_id, block, level_suffix = parsers.parse_case_id_and_block(barcode)

		geometry = ImageGeometry(
			width=wsi.get_level_width(0),
			height=wsi.get_level_height(0),
			mpp_x=wsi.get_level_mpp_x(0),
			mpp_y=wsi.get_level_mpp_y(0),
			tile_width=wsi.get_tile_width(),
			tile_height=wsi.get_tile_height(),
		)

	# Parse derived fields
	derivation = attrs.get("DICOM_DERIVATION_DESCRIPTION", "")
	derivation_parts = parsers.parse_derivation_description(derivation)
	
	scanner = ScannerInfo(
		manufacturer=attrs.get("DICOM_MANUFACTURER", "unknown"),
		model=attrs.get("DICOM_MANUFACTURERS_MODEL_NAME", "unknown"),
		serial_number=attrs.get("DICOM_DEVICE_SERIAL_NUMBER", "unknown"),
		software_versions=parsers.parse_software_versions(
			attrs.get("DICOM_SOFTWARE_VERSIONS")
		),
		rack_number=parsers.safe_int(attrs.get("PIIM_DP_SCANNER_RACK_NUMBER")),
		slot_number=parsers.safe_int(attrs.get("PIIM_DP_SCANNER_SLOT_NUMBER")),
		calibration_status=attrs.get("PIIM_DP_SCANNER_CALIBRATION_STATUS", "unknown"),
		last_calibration_date=parsers.parse_calibration_date(
			attrs.get("DICOM_DATE_OF_LAST_CALIBRATION")
		),
		last_calibration_time=attrs.get(
			"DICOM_TIME_OF_LAST_CALIBRATION", ""
		).strip().strip('"') or None,
	)
	
	compression = CompressionInfo(
		derivation_description=derivation,
		quality_level=derivation_parts["quality_level"],
		dwt_level=derivation_parts["dwt_level"],
		compressor_version=derivation_parts["compressor_version"],
		lossy_compression=parsers.safe_bool_from_01(
			attrs.get("DICOM_LOSSY_IMAGE_COMPRESSION")
		),
		lossy_compression_method=attrs.get(
			"DICOM_LOSSY_IMAGE_COMPRESSION_METHOD", ""
		).strip().strip('"'),
		lossy_compression_ratio=parsers.safe_int(
			attrs.get("DICOM_LOSSY_IMAGE_COMPRESSION_RATIO")
		),
		block_compression_method=parsers.safe_int(
			attrs.get("UFS_IMAGE_BLOCK_COMPRESSION_METHOD")
		) or 0,
		wavelet_deadzone=parsers.safe_int(attrs.get("DP_WAVELET_DEADZONE")) or 0,
		wavelet_quantizer=parsers.safe_int(attrs.get("DP_WAVELET_QUANTIZER")) or 0,
	)
	
	pixel_format = PixelFormat(
		bits_allocated=parsers.safe_int(attrs.get("DICOM_BITS_ALLOCATED")) or 0,
		bits_stored=parsers.safe_int(attrs.get("DICOM_BITS_STORED")) or 0,
		high_bit=parsers.safe_int(attrs.get("DICOM_HIGH_BIT")) or 0,
		pixel_representation=parsers.safe_int(
			attrs.get("DICOM_PIXEL_REPRESENTATION")
		) or 0,
		samples_per_pixel=parsers.safe_int(attrs.get("DICOM_SAMPLES_PER_PIXEL")) or 0,
		image_type="WSI",
	)
	
	post_processing = PostProcessing(
		sharpness_gain_rgb24=parsers.safe_int(attrs.get("DP_SHARPNESS_GAIN_RGB24")) or 0,
		clahe_clip_limit_y16=parsers.safe_float(
			attrs.get("DP_CLAHE_CLIP_LIMIT_Y16")
		) or 0.0,
		clahe_context_dimension_y16=parsers.safe_int(
			attrs.get("DP_CLAHE_CONTEXT_DIMENSION_Y16")
		) or 0,
		clahe_nr_bins_y16=parsers.safe_int(attrs.get("DP_CLAHE_NR_BINS_Y16")) or 0,
	)
	
	dimensions = DimensionInfo(
		unit=attrs.get("UFS_IMAGE_DIMENSION_UNIT", "unknown"),
		scale_factor=parsers.safe_float(
			attrs.get("UFS_IMAGE_DIMENSION_SCALE_FACTOR")
		) or 0.0,
		discrete_values=parsers.parse_discrete_values(
			attrs.get("UFS_IMAGE_DIMENSION_DISCRETE_VALUES_STRING")
		),
		type=attrs.get("UFS_IMAGE_DIMENSION_TYPE", "unknown"),
	)
	
	provenance = Provenance(
		processing_date=date.today(),
		pipeline_version=pipeline_version,
		libisyntax_version=libisyntax_version,
	)
	
	return MapFileEntry(
		slide_id=slide_id,
		accession_number=barcode,
		case_id=case_id or barcode,
		block=block,
		level=level_suffix,
		source_filename=slide_path.name,
		source_path=str(slide_path),
		scan_date=parsers.parse_scan_date(
			attrs.get("DICOM_ACQUISITION_DATETIME")
		) or date.today(),
		scanner=scanner,
		compression=compression,
		pixel_format=pixel_format,
		post_processing=post_processing,
		geometry=geometry,
		dimensions=dimensions,
		icc_profile=attrs.get("DICOM_ICCPROFILE"),
		provenance=provenance,
		pim_dp_ufs_interface_version=attrs.get(
			"PIM_DP_UFS_INTERFACE_VERSION", "unknown"
		),
	)

def sanitize(value):
	"""Coerces values to serializable types and cleans string noise."""
	if value is None:
		return ""
	# Handle dates
	if hasattr(value, 'isoformat'):
		return value.isoformat()
	# Clean strings of newlines, tabs, and carriage returns for CSV safety
	if isinstance(value, str):
		return " ".join(value.split())
	return value

def flatten_metadata(metadata: MapFileEntry) -> dict:
    """Returns a flat, sanitized dictionary ready for Parquet, JSON, or CSV export."""

    return {
        # Identity & Linkage
        "slide_id": sanitize(metadata.slide_id),
        "source_filename": sanitize(metadata.source_filename),
        "accession_number": sanitize(metadata.accession_number),
        "case_id": sanitize(metadata.case_id),
        "block": sanitize(metadata.block),
        "level": sanitize(metadata.level),

        "scan_date": sanitize(metadata.scan_date),

        # Batch Effect Tracking
        "scanner_serial": sanitize(metadata.scanner.serial_number),

        # Spatial / ML Geometry
        "width": sanitize(metadata.geometry.width),
        "height": sanitize(metadata.geometry.height),
        "mpp_x": sanitize(metadata.geometry.mpp_x),
        "mpp_y": sanitize(metadata.geometry.mpp_y),

        # Provenance
        "pipeline_version": sanitize(metadata.provenance.pipeline_version),
        "processing_date": sanitize(metadata.provenance.processing_date),
    }
