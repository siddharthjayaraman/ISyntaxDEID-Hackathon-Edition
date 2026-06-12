#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from isyntax_deid.banner import print_banner
from isyntax_deid.config import ISyntaxConfig
from isyntax_deid.isyntax_deid import ISyntaxDeID


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def replace_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(
        description="Run the existing iSyntax pipeline through RAM backed /dev/shm storage."
    )
    parser.add_argument("slide", type=Path)
    parser.add_argument("--out", type=Path, default=Path("./output"))
    parser.add_argument("--id", type=str, default=None)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--thumbnail-mpp", type=float, default=8.0)
    parser.add_argument("--ram-root", type=Path, default=Path("/dev/shm"))
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-ram-workdir", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    slide_disk = args.slide.expanduser().resolve()
    final_out_root = args.out.expanduser().resolve()
    ram_root = args.ram_root.expanduser().resolve()

    if not slide_disk.is_file():
        parser.error(f"Slide not found: {slide_disk}")

    if not ram_root.is_dir() or not os.access(ram_root, os.W_OK):
        parser.error(f"RAM root is not writable: {ram_root}")

    slide_id = args.id or slide_disk.stem
    final_slide_dir = final_out_root / slide_id

    if final_slide_dir.exists() and not args.force:
        parser.error(f"Output exists, use --force: {final_slide_dir}")

    ram_workdir = Path(tempfile.mkdtemp(prefix=f"isyntax_ramdisk_{slide_id}_", dir=ram_root))
    ram_slide = ram_workdir / "input" / slide_disk.name
    ram_out_root = ram_workdir / "output"

    try:
        t0 = time.perf_counter()
        copy_file(slide_disk, ram_slide)
        copy_input_seconds = time.perf_counter() - t0

        config = ISyntaxConfig(
            tile_size=args.tile_size,
            thumbnail_mpp=args.thumbnail_mpp,
        )
        config.threads_per_slide = args.threads

        processor = ISyntaxDeID(config)

        t1 = time.perf_counter()
        zarr_path = processor.process_slide(
            ram_slide,
            slide_id,
            ram_out_root,
            save_visuals=not args.no_visuals,
        )
        convert_seconds = time.perf_counter() - t1

        if zarr_path is None:
            raise SystemExit("Conversion failed. See log above.")

        t2 = time.perf_counter()
        replace_dir(ram_out_root / slide_id, final_slide_dir)
        copy_output_seconds = time.perf_counter() - t2

        final_zip = final_slide_dir / f"{slide_id}.zarr.zip"

        print(f"\nWrote {final_zip}")
        print(f"RAM workdir: {ram_workdir}")

        print("Pipeline timings (s):")
        for stage, seconds in processor.timings.items():
            print(f"  {stage:<18} {seconds:8.2f}")

        print("RAM wrapper timings (s):")
        print(f"  copy_input_to_ram {copy_input_seconds:8.2f}")
        print(f"  convert_in_ram    {convert_seconds:8.2f}")
        print(f"  copy_output_disk  {copy_output_seconds:8.2f}")

    finally:
        if args.keep_ram_workdir:
            print(f"Kept RAM workdir: {ram_workdir}")
        else:
            shutil.rmtree(ram_workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
