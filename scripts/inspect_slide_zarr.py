"""Verification helper: read a slide zarr.zip and inspect its contents.

Usage::

    python inspect_slide_zarr.py <path/to/slide.zarr.zip> [output_dir]

What it does
------------
1. Opens the zip (explicit ``ZipStore`` — zarr v3 does not auto-detect
   ``.zip`` suffixes).
2. Prints every group-level attr and a one-line summary of every
   sub-array (shape, dtype, chunks, a few basic stats).
3. Saves the *stored* thumbnail (``thumbnail`` sub-array, a single
   JPEG XL chunk at ``thumbnail_mpp``) to ``<output_dir>/stored_thumbnail.png``.
4. Walks the full ``pixels`` array chunk-by-chunk and builds a
   reconstructed thumbnail at 8 microns per pixel, saved to
   ``<output_dir>/reconstructed_thumbnail_8mpp.png``.

The two thumbnails should look visually similar. Any gross mismatch
— missing tissue patches, obvious tiling artefacts, off-by-one
geometry, blown-out colours — is a red flag for chunk corruption,
codec mis-configuration, or a tile-coordinate bug upstream.

Chunks flagged as non-tissue in ``tissue_mask_chunks`` are *skipped*
during the reconstructed-thumbnail pass. Non-tissue chunks are not
materialised in the archive and would just return ``fill_value=255``
on read, which is already the reconstructed canvas's initial colour
— skipping them is a pure speed win with no visual difference.
"""
from __future__ import annotations

import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import zarr
from PIL import Image

# Importing the writer module triggers JPEG XL codec registration
# via imagecodecs.numcodecs — without it, zarr cannot decode the
# ``pixels`` or ``thumbnail`` chunks and raises at first read.
import isyntax_deid.zarr_writer  # noqa: F401


TARGET_MPP = 2.0


# Pillow >= 9.1 moved resampling filters under Image.Resampling; the
# old top-level aliases are still available in 10.x but scheduled to
# disappear. Try the new path first, fall back to the legacy one.
try:
	_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover — Pillow < 9.1
	_LANCZOS = Image.LANCZOS  # type: ignore[attr-defined]


def _format_value(v) -> str:
	"""Render an attr value for human-readable printing."""
	if isinstance(v, float):
		return f"{v:.6g}"
	if isinstance(v, str):
		# Quote strings so the reader can distinguish "None" the
		# string from None the value.
		return repr(v)
	return str(v)


def print_attrs(attrs: dict) -> None:
	"""Print group-level attrs as an aligned key-value block."""
	if not attrs:
		print("  (no attrs)")
		return
	keylen = max(len(k) for k in attrs)
	for k in sorted(attrs):
		print(f"  {k.ljust(keylen)} : {_format_value(attrs[k])}")


def print_array_summary(z, name: str) -> None:
	"""Print a one-or-two-line summary for a sub-array, if present.

	For the small metadata-ish arrays we also print lightweight
	statistics (tissue counts, coordinate bounding box) to make the
	dump actually useful during debugging, without flooding the
	terminal with the full coordinate list.
	"""
	if name not in z:
		print(f"  {name}: (not present)")
		return
	a = z[name]
	header = (
		f"  {name}: shape={tuple(a.shape)} dtype={a.dtype} "
		f"chunks={tuple(a.chunks)}"
	)
	stats_lines: list[str] = []
	try:
		if name in {"tile_coords", "candidate_coords"}:
			if a.shape[0] > 0:
				data = a[...]
				stats_lines.append(
					f"    x range: [{int(data[:, 0].min())}, "
					f"{int(data[:, 0].max())}]"
				)
				stats_lines.append(
					f"    y range: [{int(data[:, 1].min())}, "
					f"{int(data[:, 1].max())}]"
				)
		elif name == "tissue_status":
			data = a[...]
			stats_lines.append(
				f"    tissue: {int(data.sum())} / {data.size}"
			)
		elif name == "tissue_mask_chunks":
			data = a[...]
			stats_lines.append(
				f"    tissue chunks: {int(data.sum())} / {data.size}"
			)
		elif name == "icc_profile":
			stats_lines.append(f"    bytes: {int(a.shape[0])}")
	except Exception as e:  # pragma: no cover
		stats_lines.append(f"    (stats unavailable: {e})")

	print(header)
	for line in stats_lines:
		print(line)


def downsample_pixel_array(z, target_mpp: float) -> Image.Image:
	"""Stream the ``pixels`` array into a target_mpp-scale thumbnail.

	We iterate chunk-aligned rectangles so peak RAM stays at a single
	chunk plus the thumbnail canvas — never the full level-0 array,
	which at 100k × 100k × 3 would be ~30 GB.

	Chunks outside ``tissue_mask_chunks`` are skipped: they are not
	stored in the archive and would decode as solid ``fill_value``
	(255) regions, which is exactly what the canvas is pre-filled
	with. This turns the reconstruction from a full-grid pass into
	a tissue-only pass, which matters for slides with <20% tissue
	coverage.
	"""
	pixels = z["pixels"]
	slide_h, slide_w, _ = pixels.shape
	chunk_h, chunk_w, _ = pixels.chunks

	attrs = dict(z.attrs)
	mpp_x = float(attrs["mpp_x"])
	fill = int(attrs.get("fill_value", 255))
	scale = mpp_x / target_mpp
	thumb_h = max(1, round(slide_h * scale))
	thumb_w = max(1, round(slide_w * scale))
	canvas = np.full((thumb_h, thumb_w, 3), fill, dtype=np.uint8)

	# Prefer the tissue mask if present; falls back to decoding every
	# chunk for older archives that didn't store tissue_mask_chunks.
	if "tissue_mask_chunks" in z:
		mask = np.asarray(z["tissue_mask_chunks"][...])
	else:
		mask = None

	n_chunks_y = (slide_h + chunk_h - 1) // chunk_h
	n_chunks_x = (slide_w + chunk_w - 1) // chunk_w
	to_decode = int(mask.sum()) if mask is not None else n_chunks_y * n_chunks_x

	print(
		f"  level-0: {slide_h}×{slide_w} at {mpp_x:.4g} mpp  →  "
		f"thumb: {thumb_h}×{thumb_w} at {target_mpp} mpp "
		f"(scale={scale:.4g})"
	)
	print(f"  decoding {to_decode} chunks (tissue only)...")

	done = 0
	t0 = time.perf_counter()
	for cy in range(n_chunks_y):
		for cx in range(n_chunks_x):
			if mask is not None and not mask[cy, cx]:
				continue

			y0 = cy * chunk_h
			y1 = min(y0 + chunk_h, slide_h)
			x0 = cx * chunk_w
			x1 = min(x0 + chunk_w, slide_w)

			# Where this chunk maps to in the thumbnail. round() on
			# both ends keeps the output tight even when the scale
			# isn't a clean fraction.
			ty0 = round(y0 * scale)
			ty1 = round(y1 * scale)
			tx0 = round(x0 * scale)
			tx1 = round(x1 * scale)
			th, tw = ty1 - ty0, tx1 - tx0
			if th <= 0 or tw <= 0:
				# Below-1-pixel chunks at very aggressive downscales.
				# Nothing to paint; canvas already holds fill.
				continue

			block = np.asarray(pixels[y0:y1, x0:x1])
			resized = Image.fromarray(block).resize((tw, th), _LANCZOS)
			canvas[ty0:ty1, tx0:tx1] = np.asarray(resized)

			done += 1
			if done % 500 == 0:
				elapsed = time.perf_counter() - t0
				rate = done / elapsed if elapsed > 0 else 0.0
				eta = (to_decode - done) / rate if rate > 0 else 0.0
				print(
					f"    {done}/{to_decode} chunks  "
					f"({rate:.1f}/s, ETA {eta:.0f}s)"
				)

	elapsed = time.perf_counter() - t0
	print(f"  done in {elapsed:.1f}s")
	return Image.fromarray(canvas)


def main(zarr_path: Path, output_dir: Path) -> None:
	if not zarr_path.is_file():
		raise FileNotFoundError(f"zarr archive not found: {zarr_path}")
	output_dir.mkdir(parents=True, exist_ok=True)

	print(f"Opening {zarr_path}")
	store = zarr.storage.ZipStore(str(zarr_path), mode="r")
	z = zarr.open(store=store, mode="r")

	# --- Group-level attrs -------------------------------------------
	attrs = dict(z.attrs)
	print("\n=== group attrs ===")
	print_attrs(attrs)

	# --- Sub-arrays ---------------------------------------------------
	print("\n=== sub-arrays ===")
	for name in [
		"pixels",
		"thumbnail",
		"candidate_coords",
		"tissue_status",
		"tile_coords",
		"tissue_mask_chunks",
		"icc_profile",
	]:
		print_array_summary(z, name)

	# --- Stored thumbnail --------------------------------------------
	print("\n=== stored thumbnail ===")
	stored_thumb = np.asarray(z["thumbnail"][...])
	print(
		f"  shape={stored_thumb.shape} dtype={stored_thumb.dtype} "
		f"thumbnail_mpp={attrs.get('thumbnail_mpp')}"
	)
	stored_path = output_dir / "stored_thumbnail.png"
	Image.fromarray(stored_thumb).save(stored_path)
	print(f"  saved to {stored_path}")

	# --- Reconstructed thumbnail from the full pixel array -----------
	print("\n=== reconstructed thumbnail from pixels ===")
	reconstructed = downsample_pixel_array(z, TARGET_MPP)
	reconstructed_path = output_dir / "reconstructed_thumbnail_8mpp.png"
	reconstructed.save(reconstructed_path)
	print(f"  saved to {reconstructed_path}")

	print(
		f"\nCompare {stored_path.name} and {reconstructed_path.name} "
		f"side-by-side — they should look visually similar."
	)


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print(
			"usage: inspect_slide_zarr.py <slide.zarr.zip> [output_dir]"
		)
		sys.exit(1)
	zarr_path = Path(sys.argv[1])
	output_dir = (
		Path(sys.argv[2]) if len(sys.argv) > 2 else Path("zarr_inspect_out")
	)
	main(zarr_path, output_dir)