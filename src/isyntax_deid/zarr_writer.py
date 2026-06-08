# Copyright © 2026 TileBio Ltd.
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Licensed for non-commercial research use only. See the LICENSE file
# at the repository root for the full terms.
"""Export de-identified WSI tissue pixels + coordinates to a sparse zarr v2 zip.

Sparse full-slide layout: one array covers the whole level-0 canvas,
but only chunks containing tissue are materialised. Empty chunks don't
exist in the final archive; reads of non-tissue regions return the
fill value (white) through zarr's normal missing-chunk semantics.

Build strategy: **directory first, zip at the end**
---------------------------------------------------
This version builds into a *scratch directory* on local disk.
Workers read from libisyntax and write directly to the Zarr array 
using standard slicing (e.g. array[y1:y2, x1:x2] = rgb). Because the slices 
perfectly align with the chunk grid, Zarr handles the JPEG XL compression 
and sparse chunk writing natively without read-modify-write overhead.

Finally, the whole directory is packed into a single
`{pseudonym}.zarr.zip` as a last sequential pass with `compression=ZIP_STORED`.
"""
from __future__ import annotations

import atexit
import multiprocessing
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import zarr

# Register imagecodecs' numcodecs codecs (JPEG XL etc.) with numcodecs
# so zarr can resolve them by name on read and write. 
import imagecodecs.numcodecs as _imagecodecs_numcodecs
_imagecodecs_numcodecs.register_codecs()

from imagecodecs.numcodecs import Jpegxl  # noqa: E402 — must come after register
from isyntax_deid.metadata.schemas import MapFileEntry

ZARR_SCHEMA_VERSION = "2.0"
FILL_VALUE: int = 255
_MP_START_METHOD = "spawn"

def write_slide_zarr(
	slide_metadata: MapFileEntry,
	candidate_coords: np.ndarray,
	tissue_status: np.ndarray,
	thumbnail,
	thumbnail_mpp: float,
	output_dir: Path,
	pseudonym: str,
	*,
	tile_size: int = 224,
	jpegxl_distance: float = 1.0,
	jpegxl_effort: int = 5,
	n_workers: int = 8,
	scratch_dir: Optional[Path] = None,
	manual_slide_path: Optional[Path] = None,
) -> Path:
	"""Write tissue pixels into a sparse zarr-v2 zip with parallel encode."""
	
	# --- Validation ---------------------------------------------------
	candidate_coords = np.asarray(candidate_coords)
	tissue_status = np.asarray(tissue_status, dtype=bool)

	if candidate_coords.ndim != 2 or candidate_coords.shape[1] != 2:
		raise ValueError(f"candidate_coords must be shape (N, 2), got {candidate_coords.shape}")
	n_total = candidate_coords.shape[0]
	
	if tissue_status.shape != (n_total,):
		raise ValueError(f"tissue_status shape {tissue_status.shape} does not align with coords")
	if tile_size <= 0:
		raise ValueError(f"tile_size must be positive, got {tile_size}")
	if jpegxl_distance < 0:
		raise ValueError(f"jpegxl_distance must be non-negative, got {jpegxl_distance}")
	if not 3 <= jpegxl_effort <= 9:
		raise ValueError(f"jpegxl_effort must be in [3, 9], got {jpegxl_effort}")
	if thumbnail_mpp <= 0:
		raise ValueError(f"thumbnail_mpp must be positive, got {thumbnail_mpp}")

	# Allow explicit path override to bypass metadata assumptions
	slide_path = manual_slide_path or Path(slide_metadata.source_path)
	if not slide_path.is_file():
		raise FileNotFoundError(f"Slide source file is missing: {slide_path}")

	output_dir = Path(output_dir)
	if not output_dir.is_dir():
		raise ValueError(f"output_dir does not exist or is not a directory: {output_dir}")

	scratch_dir = Path(scratch_dir) if scratch_dir is not None else output_dir
	scratch_dir.mkdir(parents=True, exist_ok=True)

	if n_workers is None:
		n_workers = os.cpu_count() or 1
	if n_workers < 1:
		raise ValueError(f"n_workers must be >= 1, got {n_workers}")

	thumbnail_rgb = _normalise_thumbnail(thumbnail)
	slide_w = int(slide_metadata.geometry.width)
	slide_h = int(slide_metadata.geometry.height)

	# --- Drop tiles that would be padded at the slide edge ------------
	fits_slide = (
		(candidate_coords[:, 0] + tile_size <= slide_w)
		& (candidate_coords[:, 1] + tile_size <= slide_h)
	)
	keep_mask = tissue_status & fits_slide
	tile_coords = candidate_coords[keep_mask].astype(np.int64)
	n_tissue = int(tile_coords.shape[0])

	if n_tissue > 0 and (tile_coords % tile_size).any():
		residuals = np.unique(tile_coords % tile_size)
		raise ValueError(
			f"Tile coordinates must be multiples of tile_size={tile_size} "
			f"for sparse zarr storage; got residuals {residuals.tolist()}."
		)

	# --- Prepare paths ------------------------------------------------
	final_path = output_dir / f"{pseudonym}.zarr.zip"
	tmp_zip = output_dir / f"{pseudonym}.zarr.zip.tmp"
	scratch_root = scratch_dir / f"{pseudonym}.zarr"

	if tmp_zip.exists(): tmp_zip.unlink()
	if scratch_root.exists(): shutil.rmtree(scratch_root)
	if final_path.exists() and final_path.is_dir(): shutil.rmtree(final_path)

	scratch_root.mkdir(parents=True)

	try:
		# 1. Main process creates the Zarr arrays and `.zarray` metadata
		store = zarr.storage.LocalStore(str(scratch_root))
		_populate_group_metadata(
			store=store,
			slide_metadata=slide_metadata,
			candidate_coords=candidate_coords,
			tissue_status=tissue_status,
			tile_coords=tile_coords,
			thumbnail_rgb=thumbnail_rgb,
			thumbnail_mpp=thumbnail_mpp,
			slide_w=slide_w,
			slide_h=slide_h,
			tile_size=tile_size,
			jpegxl_distance=jpegxl_distance,
			jpegxl_effort=jpegxl_effort,
			n_total=n_total,
			n_tissue=n_tissue,
			slide_id=pseudonym,
		)

		# 2. Fan out pixel encode across worker processes
		_write_pixels_parallel(
			slide_path=str(slide_path),
			scratch_root=str(scratch_root),
			tile_coords=tile_coords,
			tile_size=tile_size,
			n_workers=n_workers,
		)

		# 3. Pack directory into a single zip
		_zip_directory(scratch_root, tmp_zip)

		# 4. Atomic rename (os.replace is atomic on POSIX even when the
		# destination exists — unlike unlink+rename, which leaves a
		# window where the final path is missing).
		os.replace(tmp_zip, final_path)

	except BaseException:
		if tmp_zip.exists():
			try: tmp_zip.unlink()
			except OSError: pass
		raise

	shutil.rmtree(scratch_root, ignore_errors=True)
	return final_path


# --- Main-process group build ----------------------------------------

def _populate_group_metadata(
	*,
	store,
	slide_metadata: MapFileEntry,
	candidate_coords: np.ndarray,
	tissue_status: np.ndarray,
	tile_coords: np.ndarray,
	thumbnail_rgb: np.ndarray,
	thumbnail_mpp: float,
	slide_w: int,
	slide_h: int,
	tile_size: int,
	jpegxl_distance: float,
	jpegxl_effort: int,
	n_total: int,
	n_tissue: int,
	slide_id: str,
) -> None:
	root_attrs = {
		"zarr_schema_version": ZARR_SCHEMA_VERSION,
		"slide_id": slide_id,
		"mpp_x": float(slide_metadata.geometry.mpp_x),
		"mpp_y": float(slide_metadata.geometry.mpp_y),
		"slide_width": slide_w,
		"slide_height": slide_h,
		"tile_size": int(tile_size),
		"pixel_format": "RGB",
		"fill_value": int(FILL_VALUE),
		"jpegxl_distance": float(jpegxl_distance),
		"jpegxl_effort": int(jpegxl_effort),
		"thumbnail_mpp": float(thumbnail_mpp),
		"pipeline_version": slide_metadata.provenance.pipeline_version,
		"libisyntax_version": slide_metadata.provenance.libisyntax_version,
		"n_candidate_tiles": n_total,
		"n_tissue_tiles": n_tissue,
	}

	root = zarr.create_group(store=store, zarr_format=2, attributes=root_attrs)

	_write_small_array(root, "candidate_coords", candidate_coords.astype(np.int64))
	_write_small_array(root, "tissue_status", tissue_status)
	_write_small_array(root, "tile_coords", tile_coords)
	_write_small_array(
		root,
		"tissue_mask_chunks",
		_chunk_resolution_mask(tile_coords, slide_w, slide_h, tile_size),
	)

	_write_thumbnail(
		root,
		thumbnail_rgb=thumbnail_rgb,
		jpegxl_distance=jpegxl_distance,
		jpegxl_effort=jpegxl_effort,
	)

	if slide_metadata.icc_profile:
		icc_bytes = np.frombuffer(slide_metadata.icc_profile.encode("utf-8"), dtype=np.uint8)
		if icc_bytes.size > 0:
			_write_small_array(root, "icc_profile", icc_bytes)

	# Initialise the pixels array (writes .zarray but no chunks)
	# The numcodecs compressor handles the C-level JXL calls automatically during assignment
	jpegxl_codec = Jpegxl(distance=jpegxl_distance, effort=jpegxl_effort, lossless=False)
	root.create_array(
		name="pixels",
		shape=(slide_h, slide_w, 3),
		dtype=np.uint8,
		chunks=(tile_size, tile_size, 3),
		compressor=jpegxl_codec,
		fill_value=FILL_VALUE,
	)


def _write_small_array(group, name: str, data: np.ndarray) -> None:
	chunks = tuple(1 for _ in data.shape) if data.size == 0 else data.shape
	arr = group.create_array(name=name, shape=data.shape, dtype=data.dtype, chunks=chunks)
	if data.size > 0: arr[...] = data


def _chunk_resolution_mask(tile_coords: np.ndarray, slide_w: int, slide_h: int, tile_size: int) -> np.ndarray:
	n_chunks_y = (slide_h + tile_size - 1) // tile_size
	n_chunks_x = (slide_w + tile_size - 1) // tile_size
	mask = np.zeros((n_chunks_y, n_chunks_x), dtype=bool)
	if tile_coords.shape[0] > 0:
		cx = tile_coords[:, 0] // tile_size
		cy = tile_coords[:, 1] // tile_size
		mask[cy, cx] = True
	return mask


def _normalise_thumbnail(thumbnail) -> np.ndarray:
	arr = np.asarray(thumbnail)
	if arr.dtype != np.uint8:
		raise ValueError("thumbnail dtype must be uint8.")
	if arr.ndim == 2:
		arr = np.stack([arr, arr, arr], axis=-1)
	elif arr.ndim == 3:
		if arr.shape[-1] == 4: arr = arr[:, :, :3]
		elif arr.shape[-1] != 3: raise ValueError("thumbnail must have 3 or 4 channels")
	else:
		raise ValueError("thumbnail must be 2D or 3D")
	return np.ascontiguousarray(arr)


def _write_thumbnail(group, *, thumbnail_rgb: np.ndarray, jpegxl_distance: float, jpegxl_effort: int) -> None:
	h, w, _ = thumbnail_rgb.shape
	arr = group.create_array(
		name="thumbnail",
		shape=(h, w, 3),
		dtype=np.uint8,
		chunks=(h, w, 3),
		compressor=Jpegxl(distance=jpegxl_distance, effort=jpegxl_effort, lossless=False),
	)
	arr[...] = thumbnail_rgb


# --- Parallel pixel encode (Zarr native writing) ----------------------

_WORKER_WSI = None
_WORKER_WSI_CM = None
_WORKER_ZARR_PIXELS = None
_WORKER_TILE_SIZE = None

def _worker_init(
	slide_path: str,
	scratch_root: str,
	tile_size: int,
) -> None:
	global _WORKER_WSI, _WORKER_WSI_CM, _WORKER_ZARR_PIXELS, _WORKER_TILE_SIZE

	from tile_pyisyntax import ISyntaxWSI

	_WORKER_WSI_CM = ISyntaxWSI(slide_path)
	_WORKER_WSI = _WORKER_WSI_CM.__enter__()

	# Open the Zarr array initialized by the main process.
	# Zarr reads the metadata and reconstructs the JPEG XL compressor automatically.
	store = zarr.storage.LocalStore(scratch_root)
	root = zarr.open_group(store=store, mode='r+')
	_WORKER_ZARR_PIXELS = root["pixels"]
	
	_WORKER_TILE_SIZE = int(tile_size)

	atexit.register(_worker_cleanup)


def _worker_cleanup() -> None:
	global _WORKER_WSI_CM
	cm = _WORKER_WSI_CM
	_WORKER_WSI_CM = None
	if cm is not None:
		try: cm.__exit__(None, None, None)
		except Exception: pass


def _worker_encode_tile(coord) -> None:
	x, y = int(coord[0]), int(coord[1])
	ts = _WORKER_TILE_SIZE

	# Read and slice alpha
	region = _WORKER_WSI.read_region(0, x, y, ts, ts)
	rgb = np.ascontiguousarray(region[:, :, :3])

	# Assign directly to the Zarr array.
	# Because x and y are perfect multiples of tile_size, Zarr will intercept this,
	# pass `rgb` to the Jpegxl compressor, and write exactly one chunk file to disk.
	_WORKER_ZARR_PIXELS[y:y+ts, x:x+ts, :] = rgb

	# Force immediate garbage collection
	del region, rgb


def _write_pixels_parallel(
	*,
	slide_path: str,
	scratch_root: str,
	tile_coords: np.ndarray,
	tile_size: int,
	n_workers: int,
) -> None:
	n_tasks = tile_coords.shape[0]
	if n_tasks == 0:
		return

	# GENERATOR: Prevents holding/pickling huge coordinate arrays
	task_gen = ((int(row[0]), int(row[1])) for row in tile_coords)
	chunksize = max(1, min(64, (n_tasks // (n_workers * 8)) or 1))

	ctx = multiprocessing.get_context(_MP_START_METHOD)
	with ctx.Pool(
		processes=n_workers,
		initializer=_worker_init,
		# Note: Removed jpegxl_effort and distance as Zarr handles it intrinsically now
		initargs=(slide_path, scratch_root, tile_size),
		maxtasksperchild=8,
	) as pool:
		for _ in pool.imap_unordered(_worker_encode_tile, task_gen, chunksize=chunksize):
			pass


# --- Zip packing ------------------------------------------------------

def _zip_directory(src_dir: Path, dest_zip: Path) -> None:
	with zipfile.ZipFile(
		dest_zip,
		mode="w",
		compression=zipfile.ZIP_STORED,
		allowZip64=True,
	) as zf:
		for path in src_dir.rglob("*"):
			if not path.is_file():
				continue
			arcname = path.relative_to(src_dir).as_posix()
			zf.write(path, arcname=arcname)