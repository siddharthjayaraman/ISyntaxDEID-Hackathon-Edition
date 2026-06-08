# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Pydantic schemas for slide deidentification pipeline."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

# ============================================================
# Pseudonymised (non-identifying) metadata
# ============================================================

class PseudonymisedMetadata(BaseModel):
    """Metadata stored alongside the pseudonymised image file."""
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    slide_id: str
    stain: Optional[str] = None
    mpp_x: float
    mpp_y: float
    width: int
    height: int

# ============================================================
# Map file entry (held securely inside the TRE)
# ============================================================

class ScannerInfo(BaseModel):
    manufacturer: str
    model: str
    serial_number: str
    software_versions: list[str]
    rack_number: Optional[int] = None
    slot_number: Optional[int] = None
    calibration_status: str
    last_calibration_date: Optional[date] = None
    last_calibration_time: Optional[str] = None

class CompressionInfo(BaseModel):
    derivation_description: str
    quality_level: Optional[int] = None
    dwt_level: Optional[int] = None
    compressor_version: Optional[int] = None
    lossy_compression: bool
    lossy_compression_method: str
    lossy_compression_ratio: Optional[int] = None
    block_compression_method: int
    wavelet_deadzone: int
    wavelet_quantizer: int

class PixelFormat(BaseModel):
    bits_allocated: int
    bits_stored: int
    high_bit: int
    pixel_representation: int
    samples_per_pixel: int
    image_type: Literal["WSI"]

class PostProcessing(BaseModel):
    sharpness_gain_rgb24: int
    clahe_clip_limit_y16: float
    clahe_context_dimension_y16: int
    clahe_nr_bins_y16: int

class ImageGeometry(BaseModel):
    width: int
    height: int
    mpp_x: float
    mpp_y: float
    tile_width: int
    tile_height: int

class DimensionInfo(BaseModel):
    unit: str
    scale_factor: float
    discrete_values: list[str]
    type: str

class Provenance(BaseModel):
    processing_date: date
    pipeline_version: str
    libisyntax_version: str

class MapFileEntry(BaseModel):
    """Complete slide metadata held in the secure map file.
    
    Contains identifying information. Must remain within the TRE.
    """
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    
    slide_id: str
    accession_number: str
    case_id: str
    block: Optional[str] = None
    level: Optional[str] = None
    source_filename: str = Field(..., description="Basename of the .isyntax file")
    source_path: str = Field(..., description="Absolute path to the .isyntax file")    
    scan_date: date
    
    scanner: ScannerInfo
    compression: CompressionInfo
    pixel_format: PixelFormat
    post_processing: PostProcessing
    geometry: ImageGeometry
    dimensions: DimensionInfo
    icc_profile: Optional[str] = None
    provenance: Provenance
    
    pim_dp_ufs_interface_version: str