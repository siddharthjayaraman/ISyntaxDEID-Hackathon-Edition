#!/usr/bin/env python
# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Benchmark the per-slide iSyntax -> zarr.zip conversion.

This is the number the hackathon is about: wall-clock seconds to convert one
slide. It runs the conversion several times, drops warmup runs, and reports
per-stage and total timing plus throughput.

    PYTHONPATH=src python scripts/benchmark.py /path/to/slide.isyntax --runs 5

Tune the knobs you are optimising via --threads / --tile-size and compare runs.
QA visuals are skipped so the measurement reflects pure conversion cost.
"""

import argparse
import logging
import statistics
from collections import defaultdict
from pathlib import Path

from isyntax_deid.banner import print_banner
from isyntax_deid.config import ISyntaxConfig
from isyntax_deid.isyntax_deid import ISyntaxDeID


def _read_zarr_stats(zarr_path: Path) -> dict:
	"""Pull slide size + tissue-tile count from the produced archive."""
	import imagecodecs.numcodecs as _ic
	_ic.register_codecs()
	import zarr

	store = zarr.storage.ZipStore(str(zarr_path), mode="r")
	try:
		z = zarr.open(store=store, mode="r")
		attrs = dict(z.attrs)
	finally:
		store.close()
	return {
		"slide_width": int(attrs.get("slide_width", 0)),
		"slide_height": int(attrs.get("slide_height", 0)),
		"n_tissue_tiles": int(attrs.get("n_tissue_tiles", 0)),
	}


def _fmt_table(rows: list[tuple[str, list[float]]]) -> str:
	header = f"{'stage':<16}{'median':>10}{'mean':>10}{'min':>10}{'max':>10}"
	lines = [header, "-" * len(header)]
	for name, samples in rows:
		lines.append(
			f"{name:<16}"
			f"{statistics.median(samples):>10.2f}"
			f"{statistics.fmean(samples):>10.2f}"
			f"{min(samples):>10.2f}"
			f"{max(samples):>10.2f}"
		)
	return "\n".join(lines)


def main():
	parser = argparse.ArgumentParser(description="Benchmark single-slide conversion")
	parser.add_argument("slide", type=Path, help="Path to the .isyntax file")
	parser.add_argument("--runs", type=int, default=5, help="Measured runs (after warmup)")
	parser.add_argument("--warmup", type=int, default=1, help="Warmup runs to discard")
	parser.add_argument("--out", type=Path, default=Path("./bench_output"))
	parser.add_argument("--threads", type=int, default=None, help="Encode workers (default: all cores)")
	parser.add_argument("--tile-size", type=int, default=224)
	parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
	args = parser.parse_args()

	print_banner()

	# Keep the pipeline's own logging quiet; the benchmark prints its own report.
	logging.basicConfig(level=logging.WARNING)

	if not args.slide.is_file():
		parser.error(f"Slide not found: {args.slide}")

	config = ISyntaxConfig(tile_size=args.tile_size, thumbnail_mpp=args.thumbnail_mpp)
	if args.threads is not None:
		config.threads_per_slide = args.threads

	processor = ISyntaxDeID(config)
	slide_id = args.slide.stem

	stage_samples: dict[str, list[float]] = defaultdict(list)
	zarr_stats = None

	total_runs = args.warmup + args.runs
	print(f"Benchmarking {args.slide.name} | threads={config.threads_per_slide} "
		  f"tile_size={config.tile_size} | {args.warmup} warmup + {args.runs} measured runs\n")

	for i in range(total_runs):
		phase = "warmup" if i < args.warmup else "measure"
		zarr_path = processor.process_slide(
			args.slide, slide_id, args.out, save_visuals=False,
		)
		if zarr_path is None:
			raise SystemExit("Conversion failed -- see traceback above.")
		t = processor.timings
		print(f"  run {i + 1}/{total_runs} [{phase}]  total={t['total']:.2f}s")
		if phase == "measure":
			for stage, secs in t.items():
				stage_samples[stage].append(secs)
		if zarr_stats is None:
			zarr_stats = _read_zarr_stats(zarr_path)

	# Order stages with total last.
	ordered = [k for k in stage_samples if k != "total"] + ["total"]
	rows = [(k, stage_samples[k]) for k in ordered if k in stage_samples]

	print("\n" + _fmt_table(rows))

	total_med = statistics.median(stage_samples["total"])
	if zarr_stats:
		megapixels = (zarr_stats["slide_width"] * zarr_stats["slide_height"]) / 1e6
		print(
			f"\nSlide: {zarr_stats['slide_width']}x{zarr_stats['slide_height']} px "
			f"({megapixels:,.0f} MP), {zarr_stats['n_tissue_tiles']:,} tissue tiles encoded"
		)
		print(f"Throughput: {megapixels / total_med:,.0f} MP/s, "
			  f"{zarr_stats['n_tissue_tiles'] / total_med:,.0f} tissue-tiles/s "
			  f"(median total {total_med:.2f}s)")


if __name__ == "__main__":
	main()
