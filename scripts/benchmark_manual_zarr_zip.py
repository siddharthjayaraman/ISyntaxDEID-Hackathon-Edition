#!/usr/bin/env python
"""Manual valid Zarr ZIP writer PoC.

This is an architecture benchmark, not a merge-ready replacement.

It keeps the same high-level output contract:
    .zarr.zip
    Zarr v2 group
    sparse RGB pixels array
    candidate_coords
    tissue_status
    tile_coords
    tissue_mask_chunks
    thumbnail

The deliberate change is that pixel chunks are written directly as chunk files
instead of using pixels[y:y+ts, x:x+ts, :] = rgb.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import json
import multiprocessing as mp
import os
import shutil
import statistics
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import zarr

from imagecodecs.numcodecs import Jpegxl

from isyntax_deid.coordinates import generate_tile_coordinates
from isyntax_deid.metadata.extractor import extract_metadata, flatten_metadata
from isyntax_deid.thumbnail_extractor import extract_thumbnail
from isyntax_deid.tissue_detection import detect_tissue, tissue_region_mask, tile_envelope_status
from isyntax_deid.zarr_writer import FILL_VALUE, ZARR_SCHEMA_VERSION, _make_pixel_compressor


_MW_WSI_CM = None
_MW_WSI = None
_MW_TILE_SIZE = None
_MW_SCRATCH_ROOT = None
_MW_CHUNK_SEPARATOR = "."
_MW_COMPRESSOR = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def _chunk_key(chunk_indices: tuple[int, int, int], separator: str) -> str:
    if separator == "/":
        return "/".join(str(x) for x in chunk_indices)
    return separator.join(str(x) for x in chunk_indices)


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir).as_posix())


def _worker_cleanup() -> None:
    global _MW_WSI_CM, _MW_WSI

    if _MW_WSI_CM is not None:
        try:
            _MW_WSI_CM.__exit__(None, None, None)
        except Exception:
            pass

    _MW_WSI_CM = None
    _MW_WSI = None


def _worker_init(
    slide_path: str,
    scratch_root: str,
    tile_size: int,
    chunk_separator: str,
    pixel_codec: str,
    jpegxl_distance: float,
    jpegxl_effort: int,
) -> None:
    global _MW_WSI_CM, _MW_WSI, _MW_TILE_SIZE, _MW_SCRATCH_ROOT, _MW_CHUNK_SEPARATOR, _MW_COMPRESSOR

    from tile_pyisyntax import ISyntaxWSI

    _MW_WSI_CM = ISyntaxWSI(slide_path)
    _MW_WSI = _MW_WSI_CM.__enter__()
    _MW_TILE_SIZE = int(tile_size)
    _MW_SCRATCH_ROOT = Path(scratch_root)
    _MW_CHUNK_SEPARATOR = chunk_separator
    _MW_COMPRESSOR = _make_pixel_compressor(pixel_codec, jpegxl_distance, jpegxl_effort)

    atexit.register(_worker_cleanup)


def _worker_write_manual_chunk(coord: tuple[int, int]) -> dict[str, float]:
    x, y = int(coord[0]), int(coord[1])
    ts = int(_MW_TILE_SIZE)

    t0 = time.perf_counter()
    region = _MW_WSI.read_region(0, x, y, ts, ts)
    read_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    rgb = np.ascontiguousarray(region[:, :, :3])
    rgb_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    if _MW_COMPRESSOR is None:
        payload = rgb.tobytes(order="C")
    else:
        payload = _MW_COMPRESSOR.encode(rgb)
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
    encode_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    chunk_indices = (y // ts, x // ts, 0)
    key = _chunk_key(chunk_indices, _MW_CHUNK_SEPARATOR)
    chunk_path = _MW_SCRATCH_ROOT / "pixels" / key
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    with chunk_path.open("wb") as handle:
        handle.write(payload)
    write_seconds = time.perf_counter() - t0

    del region, rgb, payload

    return {
        "read_region": read_seconds,
        "rgba_to_rgb": rgb_seconds,
        "manual_encode": encode_seconds,
        "manual_chunk_file_write": write_seconds,
    }


def _prepare_inputs(slide: Path, *, tile_size: int, thumbnail_mpp: float) -> dict[str, Any]:
    t0 = time.perf_counter()

    raw_metadata = extract_metadata(
        slide,
        pipeline_version="manual-zarr-zip-poc",
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

    return {
        "raw_metadata": raw_metadata,
        "flat_metadata": metadata,
        "thumbnail": thumbnail,
        "thumbnail_mpp": resolved_thumbnail_mpp,
        "coords": coords,
        "status": np.asarray(status, dtype=bool),
        "prep_seconds": time.perf_counter() - t0,
    }


def _create_metadata_arrays(
    *,
    scratch_root: Path,
    prepared: dict[str, Any],
    slide_id: str,
    tile_size: int,
    jpegxl_distance: float,
    jpegxl_effort: int,
    pixel_codec: str,
) -> dict[str, Any]:
    flat = prepared["flat_metadata"]
    coords = np.asarray(prepared["coords"])
    status = np.asarray(prepared["status"], dtype=bool)

    slide_width = int(flat["width"])
    slide_height = int(flat["height"])

    fits = (
        status
        & (coords[:, 0] >= 0)
        & (coords[:, 1] >= 0)
        & ((coords[:, 0] + tile_size) <= slide_width)
        & ((coords[:, 1] + tile_size) <= slide_height)
    )

    tile_coords = np.asarray(coords[fits], dtype=np.int64)

    if tile_coords.size:
        bad = tile_coords[(tile_coords[:, 0] % tile_size != 0) | (tile_coords[:, 1] % tile_size != 0)]
        if bad.size:
            raise ValueError("manual writer requires chunk-aligned tile coordinates")

    n_chunk_y = (slide_height + tile_size - 1) // tile_size
    n_chunk_x = (slide_width + tile_size - 1) // tile_size
    tissue_mask_chunks = np.zeros((n_chunk_y, n_chunk_x), dtype=bool)

    for x, y in tile_coords:
        tissue_mask_chunks[int(y) // tile_size, int(x) // tile_size] = True

    root_attrs = {
        "zarr_schema_version": ZARR_SCHEMA_VERSION,
        "slide_id": slide_id,
        "mpp_x": _jsonable(flat.get("mpp_x")),
        "mpp_y": _jsonable(flat.get("mpp_y")),
        "slide_width": slide_width,
        "slide_height": slide_height,
        "tile_size": int(tile_size),
        "pixel_format": "RGB",
        "pixel_codec": pixel_codec,
        "fill_value": int(FILL_VALUE),
        "jpegxl_distance": float(jpegxl_distance),
        "jpegxl_effort": int(jpegxl_effort),
        "thumbnail_mpp": float(prepared["thumbnail_mpp"]),
        "pipeline_version": "manual-zarr-zip-poc",
        "libisyntax_version": "unknown",
        "n_candidate_tiles": int(coords.shape[0]),
        "n_tissue_tiles": int(tile_coords.shape[0]),
    }

    store = zarr.storage.LocalStore(str(scratch_root))
    root = zarr.create_group(store=store, zarr_format=2, attributes=root_attrs)

    root.create_dataset(
        "candidate_coords",
        data=np.asarray(coords, dtype=np.int64),
        shape=coords.shape,
        chunks=coords.shape,
        dtype=np.int64,
        compressor=None,
    )

    root.create_dataset(
        "tissue_status",
        data=status,
        shape=status.shape,
        chunks=status.shape,
        dtype=bool,
        compressor=None,
    )

    root.create_dataset(
        "tile_coords",
        data=tile_coords,
        shape=tile_coords.shape,
        chunks=tile_coords.shape if tile_coords.size else (1, 2),
        dtype=np.int64,
        compressor=None,
    )

    root.create_dataset(
        "tissue_mask_chunks",
        data=tissue_mask_chunks,
        shape=tissue_mask_chunks.shape,
        chunks=tissue_mask_chunks.shape,
        dtype=bool,
        compressor=None,
    )

    thumbnail_rgb = np.asarray(prepared["thumbnail"].convert("RGB"), dtype=np.uint8)
    root.create_dataset(
        "thumbnail",
        data=thumbnail_rgb,
        shape=thumbnail_rgb.shape,
        chunks=thumbnail_rgb.shape,
        dtype=np.uint8,
        compressor=Jpegxl(distance=jpegxl_distance, effort=jpegxl_effort, lossless=False),
    )

    pixel_compressor = _make_pixel_compressor(pixel_codec, jpegxl_distance, jpegxl_effort)

    root.create_dataset(
        "pixels",
        shape=(slide_height, slide_width, 3),
        chunks=(tile_size, tile_size, 3),
        dtype=np.uint8,
        fill_value=int(FILL_VALUE),
        compressor=pixel_compressor,
    )

    zarray_path = scratch_root / "pixels" / ".zarray"
    zarray = json.loads(zarray_path.read_text())
    chunk_separator = zarray.get("dimension_separator", ".")

    return {
        "tile_coords": tile_coords,
        "chunk_separator": chunk_separator,
        "n_candidate_tiles": int(coords.shape[0]),
        "n_tissue_tiles": int(tile_coords.shape[0]),
        "slide_width": slide_width,
        "slide_height": slide_height,
    }


def _summarise_worker_timings(worker_rows: list[dict[str, float]]) -> list[dict[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)

    for row in worker_rows:
        for key, value in row.items():
            grouped[key].append(float(value))

    out = []
    for key, values in sorted(grouped.items()):
        out.append(
            {
                "event": key,
                "count": len(values),
                "total_seconds": sum(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": statistics.median(values),
                "max_seconds": max(values),
            }
        )
    return out


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event",
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


def manual_zarr_zip_write(
    *,
    slide: Path,
    output_dir: Path,
    prepared: dict[str, Any],
    slide_id: str,
    tile_size: int,
    threads: int,
    jpegxl_distance: float,
    jpegxl_effort: int,
    pixel_codec: str,
) -> dict[str, Any]:
    slide_out = output_dir / slide_id
    slide_out.mkdir(parents=True, exist_ok=True)

    scratch_root = slide_out / f"{slide_id}.manual_scratch.zarr"
    final_zip = slide_out / f"{slide_id}.zarr.zip"
    tmp_zip = slide_out / f"{slide_id}.zarr.zip.tmp"

    if scratch_root.exists():
        shutil.rmtree(scratch_root)
    if final_zip.exists():
        final_zip.unlink()
    if tmp_zip.exists():
        tmp_zip.unlink()

    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    meta = _create_metadata_arrays(
        scratch_root=scratch_root,
        prepared=prepared,
        slide_id=slide_id,
        tile_size=tile_size,
        jpegxl_distance=jpegxl_distance,
        jpegxl_effort=jpegxl_effort,
        pixel_codec=pixel_codec,
    )
    timings["metadata_arrays_seconds"] = time.perf_counter() - t0

    tile_coords = [tuple(map(int, row)) for row in np.asarray(meta["tile_coords"])]

    t0 = time.perf_counter()
    worker_rows: list[dict[str, float]] = []
    if tile_coords:
        ctx = mp.get_context("spawn")
        chunksize = max(1, min(64, (len(tile_coords) // (max(1, threads) * 8)) or 1))
        with ctx.Pool(
            processes=threads,
            initializer=_worker_init,
            initargs=(
                str(slide),
                str(scratch_root),
                tile_size,
                str(meta["chunk_separator"]),
                pixel_codec,
                jpegxl_distance,
                jpegxl_effort,
            ),
            maxtasksperchild=None,
        ) as pool:
            for worker_row in pool.imap_unordered(_worker_write_manual_chunk, tile_coords, chunksize=chunksize):
                worker_rows.append(worker_row)
    timings["manual_pixels_parallel_seconds"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    _zip_directory(scratch_root, tmp_zip)
    timings["zip_directory_seconds"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    os.replace(tmp_zip, final_zip)
    timings["atomic_replace_seconds"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    shutil.rmtree(scratch_root, ignore_errors=True)
    timings["cleanup_seconds"] = time.perf_counter() - t0

    return {
        "zarr_path": final_zip,
        "timings": timings,
        "worker_summary": _summarise_worker_timings(worker_rows),
        "n_candidate_tiles": meta["n_candidate_tiles"],
        "n_tissue_tiles": meta["n_tissue_tiles"],
        "slide_width": meta["slide_width"],
        "slide_height": meta["slide_height"],
        "output_size_mb": final_zip.stat().st_size / (1024 * 1024),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark manual valid Zarr ZIP writer PoC")
    parser.add_argument("slide", type=Path)
    parser.add_argument("--out", type=Path, default=Path("./bench_manual_zarr_zip"))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
    parser.add_argument("--jpegxl-distance", type=float, default=1.0)
    parser.add_argument("--jpegxl-effort", type=int, default=3)
    parser.add_argument("--pixel-codec", default="jpegxl", choices=["jpegxl", "raw", "blosc_lz4", "blosc_zstd"])
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    slide_id = f"{args.slide.stem}_manual_{args.pixel_codec}"

    t0 = time.perf_counter()
    prepared = _prepare_inputs(
        args.slide,
        tile_size=args.tile_size,
        thumbnail_mpp=args.thumbnail_mpp,
    )
    prep_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = manual_zarr_zip_write(
        slide=args.slide,
        output_dir=args.out,
        prepared=prepared,
        slide_id=slide_id,
        tile_size=args.tile_size,
        threads=args.threads,
        jpegxl_distance=args.jpegxl_distance,
        jpegxl_effort=args.jpegxl_effort,
        pixel_codec=args.pixel_codec,
    )
    writer_seconds = time.perf_counter() - t0

    total_seconds = prep_seconds + writer_seconds

    summary_csv = args.out / "manual_zarr_zip_summary.csv"
    worker_csv = args.out / "manual_zarr_zip_worker_summary.csv"
    summary_md = args.out / "manual_zarr_zip_summary.md"

    with summary_csv.open("w", newline="") as handle:
        fieldnames = [
            "writer_mode",
            "pixel_codec",
            "threads",
            "prep_seconds",
            "writer_seconds",
            "total_seconds",
            "metadata_arrays_seconds",
            "manual_pixels_parallel_seconds",
            "zip_directory_seconds",
            "atomic_replace_seconds",
            "cleanup_seconds",
            "output_size_mb",
            "n_candidate_tiles",
            "n_tissue_tiles",
            "zarr_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        row = {
            "writer_mode": "manual_zarr_zip",
            "pixel_codec": args.pixel_codec,
            "threads": args.threads,
            "prep_seconds": prep_seconds,
            "writer_seconds": writer_seconds,
            "total_seconds": total_seconds,
            "output_size_mb": result["output_size_mb"],
            "n_candidate_tiles": result["n_candidate_tiles"],
            "n_tissue_tiles": result["n_tissue_tiles"],
            "zarr_path": str(result["zarr_path"]),
        }
        row.update(result["timings"])
        writer.writerow(row)

    _write_summary_csv(worker_csv, result["worker_summary"])

    with summary_md.open("w") as handle:
        handle.write("# Manual valid Zarr ZIP writer PoC\n\n")
        handle.write(f"Zarr path: `{result['zarr_path']}`\n\n")
        handle.write("| Metric | Value |\n")
        handle.write("|---|---:|\n")
        handle.write(f"| prep_seconds | {prep_seconds:.3f} |\n")
        handle.write(f"| writer_seconds | {writer_seconds:.3f} |\n")
        handle.write(f"| total_seconds | {total_seconds:.3f} |\n")
        for key, value in result["timings"].items():
            handle.write(f"| {key} | {value:.3f} |\n")
        handle.write(f"| output_size_mb | {result['output_size_mb']:.3f} |\n")
        handle.write(f"| n_candidate_tiles | {result['n_candidate_tiles']} |\n")
        handle.write(f"| n_tissue_tiles | {result['n_tissue_tiles']} |\n\n")
        handle.write("## Worker event summary\n\n")
        handle.write("| Event | Count | Total s | Mean s | Median s | Max s |\n")
        handle.write("|---|---:|---:|---:|---:|---:|\n")
        for row in sorted(result["worker_summary"], key=lambda x: x["total_seconds"], reverse=True):
            handle.write(
                f"| {row['event']} | {row['count']} | "
                f"{row['total_seconds']:.3f} | "
                f"{row['mean_seconds']:.6f} | "
                f"{row['median_seconds']:.6f} | "
                f"{row['max_seconds']:.6f} |\n"
            )

    print(f"Zarr path: {result['zarr_path']}")
    print(f"Summary CSV: {summary_csv}")
    print(f"Worker CSV: {worker_csv}")
    print(f"Summary MD: {summary_md}")
    print()
    print("| Metric | Value |")
    print("|---|---:|")
    print(f"| prep_seconds | {prep_seconds:.3f} |")
    print(f"| writer_seconds | {writer_seconds:.3f} |")
    print(f"| total_seconds | {total_seconds:.3f} |")
    for key, value in result["timings"].items():
        print(f"| {key} | {value:.3f} |")
    print(f"| output_size_mb | {result['output_size_mb']:.3f} |")
    print(f"| n_candidate_tiles | {result['n_candidate_tiles']} |")
    print(f"| n_tissue_tiles | {result['n_tissue_tiles']} |")
    print()
    print("| Worker event | Count | Total s | Mean s |")
    print("|---|---:|---:|---:|")
    for row in sorted(result["worker_summary"], key=lambda x: x["total_seconds"], reverse=True):
        print(
            f"| {row['event']} | {row['count']} | "
            f"{row['total_seconds']:.3f} | {row['mean_seconds']:.6f} |"
        )


if __name__ == "__main__":
    main()
