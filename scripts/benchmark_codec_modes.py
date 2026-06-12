#!/usr/bin/env python
"""Benchmark valid Zarr writer codec modes.

This script keeps the same pipeline inputs, tissue selection and sparse Zarr v2
layout, then compares only the pixel compressor used by write_slide_zarr.

It is intended for quick Day 3 evidence:
    jpegxl
    raw
    blosc_lz4
    blosc_zstd

Example:
    PYTHONPATH=src python scripts/benchmark_codec_modes.py ~/run_report/data/testslide.isyntax \
        --threads 8 \
        --runs 1 \
        --out ~/run_report/benchmarks/codec_modes
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time
from pathlib import Path

import numpy as np
import zarr

from isyntax_deid.coordinates import generate_tile_coordinates
from isyntax_deid.metadata.extractor import extract_metadata, flatten_metadata
from isyntax_deid.thumbnail_extractor import extract_thumbnail
from isyntax_deid.tissue_detection import detect_tissue, tissue_region_mask, tile_envelope_status
from isyntax_deid.zarr_writer import write_slide_zarr


EXPECTED_ARRAYS = (
    "pixels",
    "thumbnail",
    "candidate_coords",
    "tissue_status",
    "tile_coords",
    "tissue_mask_chunks",
)


def _prepare_inputs(slide: Path, *, tile_size: int, thumbnail_mpp: float) -> dict:
    t0 = time.perf_counter()

    raw_metadata = extract_metadata(
        slide,
        pipeline_version="codec-mode-benchmark",
        libisyntax_version="unknown",
        slide_id=slide.stem,
    )
    metadata = flatten_metadata(raw_metadata)

    thumbnail = extract_thumbnail(str(slide), target_mpp=thumbnail_mpp)
    resolved_thumbnail_mpp = float(thumbnail.info.get("mpp_x", thumbnail_mpp))

    coords = generate_tile_coordinates(
        int(metadata["width"]),
        int(metadata["height"]),
        tile_size=tile_size,
    )

    mask = tissue_region_mask(detect_tissue(thumbnail))
    status = tile_envelope_status(
        coords,
        tile_size,
        mask,
        resolved_thumbnail_mpp,
        float(metadata["mpp_x"]),
    )

    prep_seconds = time.perf_counter() - t0

    return {
        "raw_metadata": raw_metadata,
        "thumbnail": thumbnail,
        "thumbnail_mpp": resolved_thumbnail_mpp,
        "coords": coords,
        "status": status,
        "prep_seconds": prep_seconds,
    }


def _inspect_zarr(zarr_path: Path) -> dict:
    store = zarr.storage.ZipStore(str(zarr_path), mode="r")
    try:
        root = zarr.open(store=store, mode="r")
        attrs = dict(root.attrs)

        missing = [name for name in EXPECTED_ARRAYS if name not in root]
        if missing:
            raise ValueError(f"missing arrays: {', '.join(missing)}")

        pixels = root["pixels"]
        tile_coords = np.asarray(root["tile_coords"][...])
        tissue_status = np.asarray(root["tissue_status"][...])

        return {
            "inspect_status": "pass",
            "error_message": "",
            "slide_width": int(attrs.get("slide_width", 0)),
            "slide_height": int(attrs.get("slide_height", 0)),
            "n_candidate_tiles": int(attrs.get("n_candidate_tiles", tissue_status.size)),
            "n_tissue_tiles": int(attrs.get("n_tissue_tiles", tile_coords.shape[0])),
            "pixel_codec_attr": str(attrs.get("pixel_codec", "")),
            "pixels_shape": "x".join(str(x) for x in pixels.shape),
            "pixels_chunks": "x".join(str(x) for x in pixels.chunks),
        }
    finally:
        store.close()


def _run_one_mode(
    *,
    slide: Path,
    output_root: Path,
    mode: str,
    run_index: int,
    prepared: dict,
    tile_size: int,
    threads: int,
    jpegxl_distance: float,
    jpegxl_effort: int,
) -> dict:
    pseudonym = f"{slide.stem}_{mode}_run{run_index}"
    mode_out = output_root / mode
    mode_out.mkdir(parents=True, exist_ok=True)

    row = {
        "writer_mode": mode,
        "pixel_codec": mode,
        "threads": threads,
        "run_index": run_index,
        "prep_seconds": f"{prepared['prep_seconds']:.6f}",
        "zarr_write_seconds": "",
        "total_seconds": "",
        "output_size_mb": "",
        "n_candidate_tiles": "",
        "n_tissue_tiles": "",
        "inspect_status": "fail",
        "error_message": "",
        "zarr_path": "",
    }

    t0 = time.perf_counter()
    try:
        zarr_path = write_slide_zarr(
            slide_metadata=prepared["raw_metadata"],
            candidate_coords=prepared["coords"],
            tissue_status=prepared["status"],
            thumbnail=prepared["thumbnail"],
            thumbnail_mpp=prepared["thumbnail_mpp"],
            output_dir=mode_out,
            pseudonym=pseudonym,
            tile_size=tile_size,
            jpegxl_distance=jpegxl_distance,
            jpegxl_effort=jpegxl_effort,
            pixel_codec=mode,
            n_workers=threads,
            manual_slide_path=slide,
        )
        write_seconds = time.perf_counter() - t0
        inspect = _inspect_zarr(zarr_path)

        row.update(inspect)
        row["zarr_write_seconds"] = f"{write_seconds:.6f}"
        row["total_seconds"] = f"{prepared['prep_seconds'] + write_seconds:.6f}"
        row["output_size_mb"] = f"{zarr_path.stat().st_size / (1024 * 1024):.6f}"
        row["zarr_path"] = str(zarr_path)

    except Exception as exc:
        write_seconds = time.perf_counter() - t0
        row["zarr_write_seconds"] = f"{write_seconds:.6f}"
        row["total_seconds"] = f"{prepared['prep_seconds'] + write_seconds:.6f}"
        row["error_message"] = f"{type(exc).__name__}: {exc}"

    return row


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return

    preferred = [
        "writer_mode",
        "pixel_codec",
        "threads",
        "run_index",
        "prep_seconds",
        "zarr_write_seconds",
        "total_seconds",
        "output_size_mb",
        "n_candidate_tiles",
        "n_tissue_tiles",
        "inspect_status",
        "error_message",
        "pixel_codec_attr",
        "pixels_shape",
        "pixels_chunks",
        "slide_width",
        "slide_height",
        "zarr_path",
    ]

    extra = sorted({key for row in rows for key in row} - set(preferred))
    fieldnames = preferred + extra

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _print_summary(rows: list[dict]) -> None:
    measured = [row for row in rows if row["inspect_status"] == "pass"]
    if not measured:
        print("No passing writer modes.")
        return

    by_mode: dict[str, list[float]] = {}
    by_mode_size: dict[str, list[float]] = {}

    for row in measured:
        by_mode.setdefault(row["writer_mode"], []).append(float(row["zarr_write_seconds"]))
        by_mode_size.setdefault(row["writer_mode"], []).append(float(row["output_size_mb"]))

    baseline = statistics.median(by_mode["jpegxl"]) if "jpegxl" in by_mode else None

    print()
    print("| Writer mode | Median write s | Output MB | Speedup vs jpegxl |")
    print("|---|---:|---:|---:|")
    for mode in sorted(by_mode):
        median_write = statistics.median(by_mode[mode])
        median_size = statistics.median(by_mode_size[mode])
        speedup = baseline / median_write if baseline and median_write > 0 else 0.0
        print(f"| {mode} | {median_write:.2f} | {median_size:.2f} | {speedup:.3f}x |")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark valid Zarr pixel codec modes")
    parser.add_argument("slide", type=Path, help="Input .isyntax slide")
    parser.add_argument("--out", type=Path, default=Path("./bench_codec_modes"))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
    parser.add_argument("--jpegxl-distance", type=float, default=1.0)
    parser.add_argument("--jpegxl-effort", type=int, default=3)
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["jpegxl", "raw", "blosc_lz4", "blosc_zstd"],
        choices=["jpegxl", "raw", "blosc_lz4", "blosc_zstd"],
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Preparing shared inputs for {args.slide}")
    prepared = _prepare_inputs(
        args.slide,
        tile_size=args.tile_size,
        thumbnail_mpp=args.thumbnail_mpp,
    )

    print(
        f"Shared prep completed in {prepared['prep_seconds']:.2f}s | "
        f"candidate tiles={prepared['coords'].shape[0]:,} | "
        f"tissue status count={int(np.asarray(prepared['status']).sum()):,}"
    )

    rows: list[dict] = []

    for run_index in range(1, args.runs + 1):
        for mode in args.modes:
            print(f"Running mode={mode} run={run_index}/{args.runs}")
            row = _run_one_mode(
                slide=args.slide,
                output_root=args.out,
                mode=mode,
                run_index=run_index,
                prepared=prepared,
                tile_size=args.tile_size,
                threads=args.threads,
                jpegxl_distance=args.jpegxl_distance,
                jpegxl_effort=args.jpegxl_effort,
            )
            rows.append(row)
            print(
                f"  status={row['inspect_status']} "
                f"write={row['zarr_write_seconds']}s "
                f"size={row['output_size_mb']}MB "
                f"error={row['error_message']}"
            )

    csv_path = args.out / "codec_mode_benchmark_summary.csv"
    _write_csv(csv_path, rows)
    print(f"\nWrote {csv_path}")

    _print_summary(rows)


if __name__ == "__main__":
    main()
