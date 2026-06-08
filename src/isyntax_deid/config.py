"""Configuration for the barebones local iSyntax -> zarr.zip conversion.

The full TRE pipeline (Azure transfer, multi-VM sharding, pseudonym maps,
label-image OCR) lives under ``archive/full_pipeline/``. This config only
carries the knobs that affect a single local conversion -- which is exactly
what the hackathon is about optimising.
"""

import os
from dataclasses import dataclass


@dataclass
class ISyntaxConfig:
    # How a single slide is converted. These are the tunables.
    threads_per_slide: int = max(1, (os.cpu_count() or 2))
    thumbnail_mpp: float = 8.0
    tile_size: int = 224

    # Stamped into the output's provenance metadata.
    pipeline_version: str = "v0.1.2-hackathon"
    libisyntax_version: str = "unknown"
