#!/usr/bin/env python
# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Convert a single local .isyntax slide into a de-identified {id}.zarr.zip.

    PYTHONPATH=src python scripts/convert_slide.py /path/to/slide.isyntax

By default the output stem is the slide's filename; override with --id.
Outputs land in {out}/{id}/{id}.zarr.zip plus QA PNGs and a metadata CSV.
"""

import argparse
import logging
from pathlib import Path

from isyntax_deid.banner import print_banner
from isyntax_deid.config import ISyntaxConfig
from isyntax_deid.isyntax_deid import ISyntaxDeID


def main():
	print_banner()
	parser = argparse.ArgumentParser(description="Local iSyntax -> zarr.zip conversion")
	parser.add_argument("slide", type=Path, help="Path to the .isyntax file")
	parser.add_argument("--out", type=Path, default=Path("./output"), help="Output root directory")
	parser.add_argument("--id", type=str, default=None, help="Output stem (default: slide filename stem)")
	parser.add_argument("--threads", type=int, default=8, help="Encode workers per slide (default: all cores)")
	parser.add_argument("--tile-size", type=int, default=224)
	parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
	parser.add_argument("--no-visuals", action="store_true", help="Skip QA PNG output")
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

	if not args.slide.is_file():
		parser.error(f"Slide not found: {args.slide}")

	slide_id = args.id or args.slide.stem
	config = ISyntaxConfig(tile_size=args.tile_size, thumbnail_mpp=args.thumbnail_mpp)
	if args.threads is not None:
		config.threads_per_slide = args.threads

	processor = ISyntaxDeID(config)
	zarr_path = processor.process_slide(
		args.slide, slide_id, args.out, save_visuals=not args.no_visuals,
	)

	if zarr_path is None:
		raise SystemExit("Conversion failed -- see the logged traceback above.")

	print(f"\nWrote {zarr_path}")
	print("Per-stage timings (s):")
	for stage, secs in processor.timings.items():
		print(f"  {stage:<16} {secs:7.2f}")


if __name__ == "__main__":
	main()
