"""Fixed-MPP thumbnail extraction for iSyntax WSIs.

Thumbnails must be produced at a consistent microns-per-pixel scale — not a magnification label — because
scanners vary in base objective (20x = 0.5 MPP, 40x = 0.25 MPP) and in how
they report apparent magnification. Extracting at a fixed MPP guarantees
every downstream stage sees the same pixel-to-tissue ratio.

Typical targets:
	- 8 MPP (~1.25x equivalent): standard for tissue masking (HistoQC,
	  CLAM). ~1875x1875 px for a 15mm x 15mm tissue area.
	- 4 MPP (~2.5x equivalent): higher detail, reusable for coarse
	  slide-level tasks (stain QC, pen-mark detection, reference frames).

The iSyntax pyramid is power-of-2. When base MPP is a clean 0.25 or 0.5 and
the target is 4 or 8, the selected level's native MPP equals the target
exactly and no rescaling happens. When the pyramid does not land on the
target (non-standard scanner MPP, or non-power-of-2 target), the thumbnail
is resampled with PIL to hit the requested MPP exactly — downsampled from
a finer pyramid level so we never fabricate pixels. The final MPP is
attached to `image.info` for the anonymisation mapping file.
"""
from __future__ import annotations
from PIL import Image
from pathlib import Path

# Adjust this import to match the filename of the wrapper module in-repo.
from tile_pyisyntax import ISyntaxWSI, ISyntaxPixelFormat

# Float tolerance when comparing MPPs. 0.1% is wider than IEEE-754 rounding
# on a clean power-of-2 pyramid but tight enough that "8.0 MPP" and "8.01
# MPP" are not confused.
_MPP_TOL = 1.001


def _select_level(wsi: ISyntaxWSI, target_mpp: float) -> int:
	"""Pick the pyramid level to read from, given that the caller will
	rescale the result to exactly `target_mpp`.

	We prefer the level with the largest MPP that is still <= target_mpp
	(with a small FP tolerance). Rationale:
	  - Using a level with MPP <= target means the subsequent resize is a
	    downsample (or identity), so we never fabricate detail by
	    upsampling from a coarser level.
	  - Among levels that satisfy MPP <= target, the largest-MPP level is
	    the coarsest that still supports a clean downsample, which
	    minimises the number of pixels read from disk and processed.

	If no level has MPP <= target_mpp, the caller has asked for a
	resolution finer than the slide actually contains. We raise rather
	than silently upsample from level 0 — pathology does not tolerate
	invented pixels.
	"""
	level_count = wsi.get_level_count()
	if level_count <= 0:
		raise RuntimeError("WSI has no pyramid levels")

	best_level = None
	best_mpp = -1.0
	max_mpp_seen = -1.0
	for lvl in range(level_count):
		mpp = wsi.get_level_mpp_x(lvl)
		if mpp <= 0:
			# Defensive: skip levels with bogus metadata rather than crash
			# on log2(0). A missing MPP on one level is not fatal if
			# another level serves the request.
			continue
		if mpp > max_mpp_seen:
			max_mpp_seen = mpp
		# Tolerance lets a level whose nominal MPP is 8.0 but whose float
		# representation is 8.0000003 still count as "<= 8.0".
		if mpp <= target_mpp * _MPP_TOL and mpp > best_mpp:
			best_mpp = mpp
			best_level = lvl

	if best_level is None:
		# All levels have MPP > target — i.e., the finest level (level 0)
		# is still coarser than requested. We refuse to invent detail.
		base_mpp = wsi.get_level_mpp_x(0)
		raise RuntimeError(
			f"target_mpp {target_mpp} is finer than any available "
			f"pyramid level (base MPP = {base_mpp:.4f}, coarsest MPP = "
			f"{max_mpp_seen:.4f}). Pick a target_mpp >= {base_mpp:.4f}."
		)
	return best_level


def extract_thumbnail(
	path: str,
	target_mpp: float = 8.0,
	resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
	"""Extract a whole-slide thumbnail at exactly `target_mpp` microns/pixel.

	Selects the coarsest pyramid level whose native MPP is still <=
	`target_mpp`, reads that level in full, then (if needed) downsamples
	with PIL so the returned image has *exactly* `target_mpp` per pixel.
	Returned thumbnails from different slides in a cohort are therefore
	pixel-registrable in physical (micron) space even when the underlying
	scanners used different base MPPs.

	Parameters
	----------
	path : str
		Path to the .isyntax file.
	target_mpp : float
		Requested MPP. Typical values: 8.0 (fast tissue detection) or 4.0
		(higher detail, reusable for downstream work).
	resample : Image.Resampling
		PIL resampling filter for the optional rescale step. LANCZOS is
		the safe default for pathology thumbnails — preserves tissue
		edges better than BILINEAR/BICUBIC when downsampling by non-
		integer factors. BOX is ~2x faster and acceptable for pure
		tissue-mask use where sub-pixel accuracy doesn't matter.

	Returns
	-------
	PIL.Image.Image
		RGB thumbnail of the whole slide at `target_mpp`. `image.info`
		carries provenance for the mapping file:
			- mpp_x, mpp_y    : actual per-axis MPP of the returned image
			                    (== target_mpp, up to sub-pixel rounding)
			- level           : iSyntax pyramid level read from
			- base_mpp_x      : level-0 MPP (needed to convert thumbnail
			                    coordinates back to native-pixel space)
			- source_mpp_x/y  : native MPP of the level read (pre-rescale)
			- requested_mpp   : the `target_mpp` argument, for audit trail
			- rescaled        : bool — whether a PIL resize was applied
		Note: `info` is NOT automatically persisted by PIL's default save
		path. Use PIL.PngImagePlugin.PngInfo if writing to PNG — see the
		CLI at the bottom of this module for an example.

	Raises
	------
	ValueError
		`target_mpp` is non-positive.
	RuntimeError
		WSI has no usable pyramid levels, or `target_mpp` is finer than
		every available level (we refuse to upsample — that would
		fabricate pixels the scanner never captured).
	"""
	if target_mpp <= 0:
		raise ValueError(f"target_mpp must be positive, got {target_mpp}")
	
	if isinstance(path, Path):
		path = str(path)

	with ISyntaxWSI(path) as wsi:
		level = _select_level(wsi, target_mpp)
		source_mpp_x = float(wsi.get_level_mpp_x(level))
		source_mpp_y = float(wsi.get_level_mpp_y(level))
		base_mpp_x = float(wsi.get_level_mpp_x(0))

		src_w = wsi.get_level_width(level)
		src_h = wsi.get_level_height(level)

		# One-shot read of the entire level. `read_region` coordinates are
		# level-local pixels, so (0, 0, W, H) covers the full slide at the
		# chosen scale. At 8 MPP a 15x15 mm area is ~1875x1875 px = 14 MB
		# as RGBA; at 4 MPP it is ~56 MB. If you regularly scan 50x50 mm
		# mounts at 4 MPP, consider a tile-by-tile reader instead —
		# unnecessary at the scales this module targets.
		image = wsi.read_region(
			level, 0, 0, src_w, src_h, return_pil_image=True
		)

	# iSyntax pixels carry no meaningful alpha (the wrapper returns a
	# constant 255 plane). Drop it BEFORE any resize so we aren't paying
	# 25% extra memory and compute through the LANCZOS filter for a
	# channel we're about to throw away.
	if image.mode == "RGBA":
		image = image.convert("RGB")

	# Target pixel dimensions are computed from physical extent:
	#   physical_um = src_w * source_mpp_x
	#   target_px   = physical_um / target_mpp = src_w * source_mpp_x / target_mpp
	# Round to integer pixels, then record the *achieved* MPP — rounding
	# may shift it by a fraction of a percent from the requested value.
	dst_w = max(1, int(round(src_w * source_mpp_x / target_mpp)))
	dst_h = max(1, int(round(src_h * source_mpp_y / target_mpp)))

	rescaled = (dst_w, dst_h) != (src_w, src_h)
	if rescaled:
		image = image.resize((dst_w, dst_h), resample=resample)

	# Recompute MPP from the actual pixel count — if dst_w came out as
	# round(src_w * 0.506) it is not exactly src_w * 0.506, so the MPP
	# the pixels really represent is slightly off from target_mpp. Record
	# the true value rather than a convenient lie.
	final_mpp_x = src_w * source_mpp_x / dst_w
	final_mpp_y = src_h * source_mpp_y / dst_h

	# Attach provenance. These fields are what the mapping file needs to
	# prove a given thumbnail corresponds to a given physical slide region.
	image.info["mpp_x"] = final_mpp_x
	image.info["mpp_y"] = final_mpp_y
	image.info["level"] = int(level)
	image.info["base_mpp_x"] = base_mpp_x
	image.info["source_mpp_x"] = source_mpp_x
	image.info["source_mpp_y"] = source_mpp_y
	image.info["requested_mpp"] = float(target_mpp)
	image.info["rescaled"] = bool(rescaled)

	return image