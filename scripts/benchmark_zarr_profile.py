#!/usr/bin/env python
"""Run one conversion with fine grained Zarr writer profiling."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import time
from collections import defaultdict
from pathlib import Path

from isyntax_deid.config import ISyntaxConfig
from isyntax_deid.isyntax_deid import ISyntaxDeID
import isyntax_deid.zarr_writer as zarr_writer


def _read_events(profile_dir: Path) -> list[dict]:
    events = []
    for path in sorted(profile_dir.glob("zarr_profile_events.*.jsonl")):
        with path.open() as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    return events


def _summarise(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[float]] = defaultdict(list)

    for event in events:
        grouped[event["name"]].append(float(event.get("seconds", 0.0)))

    rows = []
    for name, values in sorted(grouped.items()):
        rows.append(
            {
                "name": name,
                "count": len(values),
                "total_seconds": sum(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": statistics.median(values),
                "max_seconds": max(values),
            }
        )
    return rows


def _write_summary_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "name",
        "count",
        "total_seconds",
        "mean_seconds",
        "median_seconds",
        "max_seconds",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_md(path: Path, rows: list[dict], *, total_seconds: float) -> None:
    with path.open("w") as handle:
        handle.write("# Fine grained Zarr writer profile\n\n")
        handle.write(f"Total conversion seconds: {total_seconds:.3f}\n\n")
        handle.write("| Event | Count | Total s | Mean s | Median s | Max s |\n")
        handle.write("|---|---:|---:|---:|---:|---:|\n")
        for row in sorted(rows, key=lambda x: x["total_seconds"], reverse=True):
            handle.write(
                f"| {row['name']} | {row['count']} | "
                f"{row['total_seconds']:.3f} | "
                f"{row['mean_seconds']:.6f} | "
                f"{row['median_seconds']:.6f} | "
                f"{row['max_seconds']:.6f} |\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile the Zarr write hot path")
    parser.add_argument("slide", type=Path)
    parser.add_argument("--out", type=Path, default=Path("./bench_zarr_profile"))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
    parser.add_argument("--pixel-codec", default="jpegxl", choices=["jpegxl", "raw", "blosc_lz4", "blosc_zstd"])
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    profile_dir = args.out / "zarr_profile_events"
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    original_write_slide_zarr = zarr_writer.write_slide_zarr

    def profiled_write_slide_zarr(*call_args, **kwargs):
        kwargs["profile_dir"] = profile_dir
        kwargs["pixel_codec"] = args.pixel_codec
        return original_write_slide_zarr(*call_args, **kwargs)

    zarr_writer.write_slide_zarr = profiled_write_slide_zarr

    config = ISyntaxConfig(tile_size=args.tile_size, thumbnail_mpp=args.thumbnail_mpp)
    config.threads_per_slide = args.threads

    processor = ISyntaxDeID(config)
    slide_id = f"{args.slide.stem}_profile_{args.pixel_codec}"

    t0 = time.perf_counter()
    zarr_path = processor.process_slide(
        args.slide,
        slide_id,
        args.out,
        save_visuals=False,
    )
    total_seconds = time.perf_counter() - t0

    if zarr_path is None:
        print("Conversion failed")
        return

    events = _read_events(profile_dir)
    rows = _summarise(events)

    csv_path = args.out / "zarr_profile_summary.csv"
    md_path = args.out / "zarr_profile_summary.md"

    _write_summary_csv(csv_path, rows)
    _write_summary_md(md_path, rows, total_seconds=total_seconds)

    print(f"Zarr path: {zarr_path}")
    print(f"Event files: {profile_dir}")
    print(f"Summary CSV: {csv_path}")
    print(f"Summary MD: {md_path}")
    print()
    print("| Event | Count | Total s | Mean s |")
    print("|---|---:|---:|---:|")
    for row in sorted(rows, key=lambda x: x["total_seconds"], reverse=True):
        print(
            f"| {row['name']} | {row['count']} | "
            f"{row['total_seconds']:.3f} | {row['mean_seconds']:.6f} |"
        )


if __name__ == "__main__":
    main()
