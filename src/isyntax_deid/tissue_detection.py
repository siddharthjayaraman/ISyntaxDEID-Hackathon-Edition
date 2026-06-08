"""Tissue detection for WSI thumbnails — universal, texture-based.

One predicate, one feature, one knob:

    "Mark a pixel as tissue if the local standard deviation of L,
     in a small window, exceeds the glass noise floor."

Glass is uniform — at 8 MPP under a Philips iSyntax scanner, real
glass has only sensor noise (~0.5–2.5 std on the L axis depending on
scanner make and age). Any tissue, regardless of stain or density,
has cellular and architectural variation that produces local std
several times higher:

  - H&E and IHC of any colour: per-cell stain variation creates texture.
  - Adipose: 30–100 µm vacuoles with sub-pixel membranes — invisible to
    per-pixel colour thresholds, but a 5×5 window straddles membrane
    intersections and lumen centres, producing clear local variance.
    This was the case the prior chroma/luminance detector silently
    missed.
  - Tissue folds, dense regions, debris: trivially textured.

The threshold is adaptive. The noise floor is estimated per slide from
the brightest 5% of valid pixels (assumed glass); the threshold is
``max(noise_floor × texture_multiplier, min_texture_threshold)``. With
``texture_multiplier=1.0`` (calibrated against ~50 representative NHS
slides), the threshold sits at the noise floor itself — tissue, which
has std well above the noise floor, is captured cleanly, and the
small population of glass pixels with above-median std is rejected by
the downstream opening + min-component-area cleanup.

iSyntax synthetic (255,255,255) fill outside the scan is detected
exactly (uint8 == 255 on all channels — sensor noise guarantees real
glass never hits this) and excluded from both noise-floor estimation
and the final mask.

Two-mask architecture preserved: this function returns a precise mask;
callers wanting permissive tile-selection envelopes layer
``tissue_region_mask`` on top.

Dependencies: numpy, Pillow, opencv-python.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


# iSyntax pads outside the scan with pure (255, 255, 255). Real glass
# always has at least sub-pixel sensor noise, so an exact triple-255
# is unambiguously synthetic and safe to detect by exact equality.
_ISYNTAX_FILL: int = 255


@dataclass(frozen=True)
class BackgroundReference:
	"""Adaptive background reference derived from a thumbnail.

	L is on CIELAB's 0-100 scale, a and b on ~[-128, 127]. Returned by
	:func:`estimate_background` and exposed so callers can log it
	alongside each slide's mask for QC — unusual values (very low L,
	strongly non-zero a/b) are a signal the scanner or slide is out of
	spec.
	"""
	L: float
	a: float
	b: float


def estimate_background(
	thumbnail: Image.Image,
	*,
	percentile: float = 95,
) -> BackgroundReference:
	"""Estimate background (L, a, b) by pooling the brightest non-fill pixels.

	No longer used internally by :func:`detect_tissue` (which derives
	its noise floor from local std rather than mean colour) but
	preserved as a standalone QC signal: a slide whose median bright
	pixel is L < 80 or |a|, |b| > 5 has a scanner / staining problem
	worth flagging in your audit log.
	"""
	rgb_u8 = np.asarray(thumbnail.convert("RGB"))
	is_fill = np.all(rgb_u8 == _ISYNTAX_FILL, axis=-1)
	valid = ~is_fill

	if not valid.any():
		return BackgroundReference(L=100.0, a=0.0, b=0.0)

	rgb = rgb_u8.astype(np.float32) / 255.0
	lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
	L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]

	threshold = np.percentile(L[valid], percentile)
	bg = (L >= threshold) & valid
	if not bg.any():
		bg = valid

	return BackgroundReference(
		L=float(np.median(L[bg])),
		a=float(np.median(a[bg])),
		b=float(np.median(b[bg])),
	)


def _local_std(arr: np.ndarray, ksize: int) -> np.ndarray:
	"""Sliding-window standard deviation. Two box filters; ~Gaussian-blur cost.

	Uses Var(X) = E[X²] - (E[X])² with cv2.boxFilter for both moments.
	The np.maximum guards against tiny negative values from float
	rounding when the variance is genuinely zero.
	"""
	a = arr.astype(np.float32, copy=False)
	mean = cv2.boxFilter(a, -1, (ksize, ksize), normalize=True)
	sq_mean = cv2.boxFilter(a * a, -1, (ksize, ksize), normalize=True)
	return np.sqrt(np.maximum(sq_mean - mean * mean, 0.0))


def _estimate_noise_floor(
	L: np.ndarray,
	L_std: np.ndarray,
	valid: np.ndarray,
	background_percentile: float,
) -> tuple[float, np.ndarray]:
	"""Estimate the glass-only local-std median.

	Returns (noise_floor, bg_mask) where ``bg_mask`` is the boolean
	array of pixels that were used to compute the floor — the caller
	may need it for debug-time colour-reference reporting.

	The brightest ``100 - background_percentile`` fraction of valid
	pixels is treated as glass; the median of their local std is the
	noise floor. If that selection happens to be empty (pathological
	thumbnail with very few valid pixels), we fall back to the full
	valid mask.
	"""
	L_threshold = np.percentile(L[valid], background_percentile)
	bg = (L >= L_threshold) & valid
	if not bg.any():
		bg = valid
	return float(np.median(L_std[bg])), bg


def _emit_debug(
	*,
	rgb_u8: np.ndarray,
	mask_bool: np.ndarray | None,
	valid: np.ndarray,
	bg: np.ndarray | None,
	lab: np.ndarray | None,
	noise_floor: float | None,
	threshold: float | None,
	floor_hit: bool | None,
	texture_multiplier: float,
	min_texture_threshold: float,
) -> None:
	"""Emit one structured calibration line to stdout. Format is stable
	and parsed by ``scripts/summarize_tissue_calibration.py``.
	"""
	h, w = rgb_u8.shape[:2]
	total = h * w
	valid_pct = 100.0 * float(valid.sum()) / total

	if mask_bool is None or bg is None or lab is None:
		# All-fill thumbnail path — no real metrics to report.
		print(
			f"[detect_tissue] thumb={w}x{h} valid={valid_pct:.1f}% "
			"bg_L=NA bg_a=NA bg_b=NA noise_floor=NA threshold=NA "
			f"(mult={texture_multiplier}, min={min_texture_threshold}, "
			"floor_hit=NA) tissue=0.0%",
			flush=True,
		)
		return

	tissue_pct = 100.0 * float(mask_bool.sum()) / total
	bg_L = float(np.median(lab[..., 0][bg]))
	bg_a = float(np.median(lab[..., 1][bg]))
	bg_b = float(np.median(lab[..., 2][bg]))
	print(
		f"[detect_tissue] thumb={w}x{h} valid={valid_pct:.1f}% "
		f"bg_L={bg_L:.1f} bg_a={bg_a:.2f} bg_b={bg_b:.2f} "
		f"noise_floor={noise_floor:.2f} threshold={threshold:.2f} "
		f"(mult={texture_multiplier}, min={min_texture_threshold}, "
		f"floor_hit={'yes' if floor_hit else 'no'}) "
		f"tissue={tissue_pct:.1f}%",
		flush=True,
	)


def detect_tissue(
	thumbnail: Image.Image,
	*,
	background_percentile: float = 95.0,
	opening_kernel_size: int = 3,
	opening_iterations: int = 1,
	fill_holes: bool = True,
	max_hole_area_px: int = 4096,
	min_component_area_px: int = 8,
	texture_kernel_size: int = 5,
	texture_multiplier: float = 0.75,
	min_texture_threshold: float = 1.0,
	debug: bool = False,
) -> np.ndarray:
	"""Detect tissue pixels in a thumbnail via local intensity variance.

	A pixel is tissue iff::

	    local_std_of_L(x, y) > max(noise_floor × texture_multiplier,
	                               min_texture_threshold)

	where ``noise_floor`` is the median local std among the brightest
	``100 - background_percentile``% of valid pixels (assumed glass).

	Parameters
	----------
	thumbnail : PIL.Image.Image
		RGB thumbnail, e.g. the output of ``extract_thumbnail`` at 8
		MPP. Channels 4 (RGBA) and 1 (grayscale) are converted to RGB
		on entry.
	background_percentile : float
		L percentile defining "brightest valid pixels" for noise-floor
		estimation. Default 95 — top 5% of valid pixels are sampled.
		Raise toward 99 only if you know bright glass is genuinely
		rare; the default is correct for clinical pathology where at
		least ~5% of every scan is empty mounting glass.
	opening_kernel_size, opening_iterations : int
		Morphological opening passes after thresholding. Strips the
		small population of glass pixels with above-median std (the
		main false-positive source) without eroding real tissue at 8
		MPP. Defaults of 3 / 1 are correct for 8 MPP thumbnails;
		double them for 4 MPP.
	fill_holes : bool
		Fill enclosed holes inside detected regions. Default True.
		Closes small interior gaps in regions where one window happens
		to land on locally smooth stain.
	max_hole_area_px : int
		Cap on hole size to fill. Default 4096 (~16 mm² at 8 MPP).
		Guards against the iSyntax-fill-ring trap where a near-closed
		ring of edge artefacts would otherwise flip the entire scan
		interior to "tissue" as one giant hole.
	min_component_area_px : int
		Drop connected components below this area (debris, dust, fill-
		boundary rings). Default 8 — large enough to drop sensor-noise
		speckles, small enough to keep single-cell biopsy fragments.
	texture_kernel_size : int
		Side of the square window for the local-std computation, in
		thumbnail pixels. Default 5 — at 8 MPP that is ~40 µm,
		slightly wider than one adipocyte (30–100 µm), narrow enough
		to keep small tissue features local. Increase to 7 if very-
		isolated single-cell features are getting filtered.
	texture_multiplier : float
		Threshold = max(noise_floor × multiplier, min_texture_threshold).
		Default 1.0 — calibrated empirically against representative
		NHS slides. With multiplier=1.0 the threshold sits at the
		noise floor itself; tissue (std >> noise_floor) passes
		cleanly, the small fraction of glass pixels above median std
		is rejected by the morphology cleanup. Raise to 1.5–2.0 only
		if a particular scanner is producing speckle false positives
		that survive ``min_component_area_px``.
	min_texture_threshold : float
		Absolute floor on the threshold. Default 1.5 — protects
		against an unusually clean scanner where ``noise_floor ×
		texture_multiplier`` would otherwise round toward zero and
		mark sensor-noise as tissue. Rarely binds with the default
		multiplier; visible in the ``floor_hit`` field of the debug
		output.
	debug : bool
		When True, print one ``[detect_tissue]`` line of calibration
		metrics to stdout per call. Format is stable and parsed by
		``scripts/summarize_tissue_calibration.py``. Default False
		(silent — production setting).

	Returns
	-------
	np.ndarray
		Bool mask, shape ``(thumbnail_h, thumbnail_w)``. True = tissue.

	Notes
	-----
	What this catches:
	  - H&E / IHC stained tissue (cell-to-cell stain variation).
	  - Adipose, including pure-fat regions (membrane network creates
	    local variance over a 5×5 window even when per-pixel mean
	    matches glass).
	  - Dense unstained tissue and folds.
	  - Pen marks and scanner annotations (intentional — for tile
	    selection you'd rather over-include and let downstream tools
	    filter than silently miss tissue).

	What this excludes:
	  - iSyntax synthetic 255 fill (uniform → zero local std).
	  - Real glass with sensor noise (std at or below the adaptive
	    threshold; survivors are dropped by morphology).
	  - Slight scanner illumination gradients (low-frequency, low
	    local std at the 5×5 scale).
	"""
	rgb_u8 = np.asarray(thumbnail.convert("RGB"))

	is_fill = np.all(rgb_u8 == _ISYNTAX_FILL, axis=-1)
	valid = ~is_fill

	if not valid.any():
		# Degenerate thumbnail (all fill) — nothing to detect.
		if debug:
			_emit_debug(
				rgb_u8=rgb_u8, mask_bool=None, valid=valid, bg=None,
				lab=None, noise_floor=None, threshold=None,
				floor_hit=None, texture_multiplier=texture_multiplier,
				min_texture_threshold=min_texture_threshold,
			)
		return np.zeros(rgb_u8.shape[:2], dtype=bool)

	rgb = rgb_u8.astype(np.float32) / 255.0
	lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
	L = lab[..., 0]

	# 1. Local std map (one feature, isotropic, scale-aware).
	L_std = _local_std(L, texture_kernel_size)

	# 2. Adaptive noise floor from the brightest valid pixels (glass).
	noise_floor, bg = _estimate_noise_floor(L, L_std, valid, background_percentile)
	scaled = noise_floor * texture_multiplier
	threshold = max(scaled, min_texture_threshold)
	floor_hit = scaled < min_texture_threshold

	# 3. Threshold and clamp to valid scan area.
	mask = ((L_std > threshold) & valid).astype(np.uint8)

	# 4. Opening: strip single-pixel specks from sensor noise.
	if opening_iterations > 0:
		k = opening_kernel_size
		kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
		mask = cv2.morphologyEx(
			mask, cv2.MORPH_OPEN, kernel, iterations=opening_iterations
		)

	# 5. Close small interior gaps (locally-smooth-stain regions where
	# a single window misses despite the cluster being clearly tissue).
	if fill_holes:
		mask = _fill_holes(mask, max_hole_area_px=max_hole_area_px)

	# 6. Drop small components — debris, dust, fill-boundary rings.
	if min_component_area_px > 0:
		_, labels, stats, _ = cv2.connectedComponentsWithStats(
			mask, connectivity=8
		)
		keep = stats[:, cv2.CC_STAT_AREA] >= min_component_area_px
		keep[0] = False  # background class
		mask = keep[labels].astype(np.uint8)

	mask_bool = mask.astype(bool)

	if debug:
		_emit_debug(
			rgb_u8=rgb_u8, mask_bool=mask_bool, valid=valid, bg=bg,
			lab=lab, noise_floor=noise_floor, threshold=threshold,
			floor_hit=floor_hit, texture_multiplier=texture_multiplier,
			min_texture_threshold=min_texture_threshold,
		)

	return mask_bool


def tissue_region_mask(
	mask: np.ndarray,
	*,
	closing_kernel_size: int = 9,
	closing_iterations: int = 1,
	max_hole_area_px: int = 30000,
	valid: np.ndarray | None = None,
) -> np.ndarray:
	"""Permissive 'tissue region' envelope mask for tile selection.

	Closes intra-tissue gaps and fills bounded holes to produce a
	permissive envelope. Asymmetric-cost rationale: dropping a tile =
	permanent data loss; keeping a blank tile = one zarr chunk of
	(very compressible) storage. Use the precise mask from
	:func:`detect_tissue` for pixel export; use this for tile
	selection.

	Parameters
	----------
	mask : np.ndarray
		Boolean (or 0/1 integer) tissue mask, shape ``(H, W)`` at
		thumbnail resolution.
	closing_kernel_size : int
		Side of the square structuring element for the closing step,
		in thumbnail pixels. Default 9 — at 8 MPP that's ~70 µm per
		pass, bridging sectioning cracks and intra-fragment glass
		slivers without growing the outer perimeter.
	closing_iterations : int
		Number of closing passes. Default 1 is enough for most slides;
		2 for unusually fractured sectioning. 0 disables closing.
	max_hole_area_px : int
		Cap on hole size to fill. Default 30000 (~2 mm² at 8 MPP).
		Catches vacuole clusters, vessel/gland lumens, sectioning
		tears without filling across the iSyntax fill ring or inter-
		fragment gaps.
	valid : np.ndarray, optional
		Boolean array, same shape as ``mask``, True where the input
		pixel was real scanned content (not iSyntax synthetic fill).
		When provided, closing/hole-fill cannot push into fill
		territory. Pass ``~is_fill`` from the same thumbnail you ran
		``detect_tissue`` on. Optional because boundary leakage is
		absorbed by downstream tile-fraction thresholds; supply it
		for clean visualisation.

	Returns
	-------
	np.ndarray
		Boolean mask, same shape as ``mask``. True = inside a tissue
		region (and worth keeping a tile for).
	"""
	if mask.ndim != 2:
		raise ValueError(f"mask must be 2D, got shape {mask.shape}")
	if closing_iterations > 0 and closing_kernel_size <= 0:
		raise ValueError(
			f"closing_kernel_size must be positive when "
			f"closing_iterations > 0, got {closing_kernel_size}"
		)
	if closing_iterations < 0:
		raise ValueError(
			f"closing_iterations must be >= 0, got {closing_iterations}"
		)
	if max_hole_area_px < 0:
		raise ValueError(
			f"max_hole_area_px must be >= 0, got {max_hole_area_px}"
		)
	if valid is not None and valid.shape != mask.shape:
		raise ValueError(
			f"valid shape {valid.shape} does not match "
			f"mask shape {mask.shape}"
		)

	work = mask.astype(np.uint8)
	valid_u8 = valid.astype(np.uint8) if valid is not None else None

	if closing_iterations > 0:
		k = closing_kernel_size
		kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
		work = cv2.morphologyEx(
			work, cv2.MORPH_CLOSE, kernel, iterations=closing_iterations
		)
		if valid_u8 is not None:
			work = work & valid_u8

	if max_hole_area_px > 0:
		work = _fill_holes(work, max_hole_area_px=max_hole_area_px)
		if valid_u8 is not None:
			work = work & valid_u8

	return work.astype(bool)

def _fill_holes(
	mask_u8: np.ndarray,
	*,
	max_hole_area_px: int = 0,
) -> np.ndarray:
	"""Fill enclosed holes in a binary mask via border flood-fill.

	When ``max_hole_area_px > 0``, only holes <= that area are filled.
	Prevents the pathological case where a near-closed ring of edge
	artefacts around the scan boundary flips the entire scan interior
	to 1 as one giant "hole".
	"""
	h, w = mask_u8.shape
	inverted = (1 - mask_u8).astype(np.uint8)
	padded = cv2.copyMakeBorder(
		inverted, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=1
	)
	ff_buf = np.zeros((h + 4, w + 4), dtype=np.uint8)
	cv2.floodFill(padded, ff_buf, (0, 0), 2)
	filled = (padded[1:-1, 1:-1] != 2).astype(np.uint8)

	if max_hole_area_px <= 0:
		return filled

	hole_mask = (filled & (1 - mask_u8)).astype(np.uint8)
	if hole_mask.sum() == 0:
		return filled
	_, labels, stats, _ = cv2.connectedComponentsWithStats(
		hole_mask, connectivity=8
	)
	small = stats[:, cv2.CC_STAT_AREA] <= max_hole_area_px
	small[0] = False
	small_holes = small[labels].astype(np.uint8)
	return np.maximum(mask_u8, small_holes)

def visualise_tissue_mask(
	thumbnail: Image.Image,
	mask: np.ndarray,
	*,
	colour: tuple[int, int, int] = (0, 255, 0),
	alpha: int = 96,
) -> Image.Image:
	"""Overlay a tissue mask on a thumbnail for visual sanity-checking.

	Parameters
	----------
	thumbnail : PIL.Image.Image
		The thumbnail ``mask`` was generated from. Not mutated.
	mask : np.ndarray
		Bool (or 0/1 integer) array, same ``(H, W)`` as the thumbnail.
	colour : (R, G, B)
		Overlay colour. Default green — deliberately unlike any H&E or
		common IHC stain, so mask edges stand out from the underlying
		tissue.
	alpha : int
		Opacity in 0-255. Default 96 (~38%) leaves the stain visible
		beneath.
	"""
	if mask.shape != thumbnail.size[::-1]:
		raise ValueError(
			f"mask shape {mask.shape} does not match thumbnail "
			f"size {thumbnail.size[::-1]} (H, W)"
		)

	base = thumbnail.convert("RGBA")
	overlay_arr = np.zeros((*mask.shape, 4), dtype=np.uint8)
	overlay_arr[mask.astype(bool)] = (*colour, alpha)
	overlay = Image.fromarray(overlay_arr, mode="RGBA")
	return Image.alpha_composite(base, overlay).convert("RGB")

def tile_tissue_status(
	coords: np.ndarray,
	tile_size: int,
	tissue_mask: np.ndarray,
	thumb_mpp: float,
	coord_mpp: float,
	*,
	min_tissue_fraction: float = 0.005,
) -> np.ndarray:
	"""Per-tile tissue-fraction decision.

	For each tile coordinate, project its ``coord_mpp``-space bounding
	box onto the thumbnail-scale tissue mask, count True pixels, and
	compare the fraction to ``min_tissue_fraction``. Summed-area table
	gives O(1) per tile regardless of tile size.

	Parameters
	----------
	coords : np.ndarray
		Shape (N, 2) array of tile top-left origins in ``coord_mpp``
		pixel space (typically level-0 of the WSI).
	tile_size : int
		Side length of each tile, in ``coord_mpp`` pixels.
	tissue_mask : np.ndarray
		Bool or 0/1 integer array, shape (H, W), at thumbnail
		resolution.
	thumb_mpp, coord_mpp : float
		MPP of the mask and the coordinates respectively. For level-0
		coords on a 40x WSI, ``coord_mpp`` is 0.25.
	min_tissue_fraction : float
		A tile is marked True when at least this fraction of its mask
		footprint is tissue. Default 0.005 — very permissive; the real
		filtering happens in :func:`tile_envelope_status` or the
		downstream zarr export.
	"""
	if coords.ndim != 2 or coords.shape[1] != 2:
		raise ValueError(
			f"coords must be shape (N, 2), got {coords.shape}"
		)
	if tile_size <= 0:
		raise ValueError(f"tile_size must be positive, got {tile_size}")
	if thumb_mpp <= 0 or coord_mpp <= 0:
		raise ValueError(
			f"mpp values must be positive, got "
			f"thumb_mpp={thumb_mpp}, coord_mpp={coord_mpp}"
		)
	if not 0.0 <= min_tissue_fraction <= 1.0:
		raise ValueError(
			f"min_tissue_fraction must be in [0, 1], "
			f"got {min_tissue_fraction}"
		)
	if tissue_mask.ndim != 2:
		raise ValueError(
			f"tissue_mask must be 2D, got shape {tissue_mask.shape}"
		)

	if coords.shape[0] == 0:
		return np.zeros((0,), dtype=bool)

	H, W = tissue_mask.shape
	scale = coord_mpp / thumb_mpp

	cx = coords[:, 0].astype(np.float64)
	cy = coords[:, 1].astype(np.float64)
	x1 = np.floor(cx * scale).astype(np.int64)
	y1 = np.floor(cy * scale).astype(np.int64)
	x2 = np.ceil((cx + tile_size) * scale).astype(np.int64)
	y2 = np.ceil((cy + tile_size) * scale).astype(np.int64)

	x1 = np.clip(x1, 0, W)
	x2 = np.clip(x2, 0, W)
	y1 = np.clip(y1, 0, H)
	y2 = np.clip(y2, 0, H)

	integral = np.zeros((H + 1, W + 1), dtype=np.int64)
	integral[1:, 1:] = (
		tissue_mask.astype(np.int64).cumsum(axis=0).cumsum(axis=1)
	)

	tissue_count = (
		integral[y2, x2]
		- integral[y1, x2]
		- integral[y2, x1]
		+ integral[y1, x1]
	)
	footprint = (y2 - y1) * (x2 - x1)

	fraction = np.where(
		footprint > 0, tissue_count / np.maximum(footprint, 1), 0.0
	)
	return fraction >= min_tissue_fraction

def tile_envelope_status(
	coords: np.ndarray,
	tile_size: int,
	tissue_mask: np.ndarray,
	thumb_mpp: float,
	coord_mpp: float,
	*,
	min_per_tile_fraction: float = 0.002,
	dilate_tiles: int = 1,
	closing_tiles: int = 2,
	fill_interior_holes: bool = True,
	max_interior_hole_tiles: int = 512,
	min_component_tiles: int = 32,
) -> np.ndarray:
	"""Permissive tile selector: keep the spatial envelope of every
	tissue body, including interior holes and a small outer buffer.

	Lifts the morphology off the pixel grid and onto the tile grid,
	where the keep/drop decision actually lives. Pipeline:

	  1. Project pixel-mask to a tile-resolution grid (summed-area).
	  2. Threshold at ``min_per_tile_fraction`` to seed the tile grid.
	  3. Drop seed components < ``min_component_tiles`` (debris).
	  4. Close (``closing_tiles``) to bridge sparse seeds in one body.
	  5. Fill interior holes up to ``max_interior_hole_tiles``.
	  6. Dilate by ``dilate_tiles`` for outer safety buffer.

	Use the precise mask from :func:`detect_tissue`, OR
	:func:`tissue_region_mask` — this function does its own (more
	aggressive) tile-grid bridging
	"""
	if coords.ndim != 2 or coords.shape[1] != 2:
		raise ValueError(
			f"coords must be shape (N, 2), got {coords.shape}"
		)
	if tile_size <= 0:
		raise ValueError(f"tile_size must be positive, got {tile_size}")
	if thumb_mpp <= 0 or coord_mpp <= 0:
		raise ValueError(
			f"mpp values must be positive, got "
			f"thumb_mpp={thumb_mpp}, coord_mpp={coord_mpp}"
		)
	if not 0.0 <= min_per_tile_fraction <= 1.0:
		raise ValueError(
			f"min_per_tile_fraction must be in [0, 1], "
			f"got {min_per_tile_fraction}"
		)
	if tissue_mask.ndim != 2:
		raise ValueError(
			f"tissue_mask must be 2D, got shape {tissue_mask.shape}"
		)
	if dilate_tiles < 0:
		raise ValueError(f"dilate_tiles must be >= 0, got {dilate_tiles}")
	if closing_tiles < 0:
		raise ValueError(f"closing_tiles must be >= 0, got {closing_tiles}")
	if min_component_tiles < 0:
		raise ValueError(
			f"min_component_tiles must be >= 0, got {min_component_tiles}"
		)
	if max_interior_hole_tiles < 0:
		raise ValueError(
			f"max_interior_hole_tiles must be >= 0, "
			f"got {max_interior_hole_tiles}"
		)

	if coords.shape[0] == 0:
		return np.zeros((0,), dtype=bool)

	H, W = tissue_mask.shape
	scale = coord_mpp / thumb_mpp
	tile_thumbpx = tile_size * scale

	if tile_thumbpx < 1.0:
		raise ValueError(
			f"tile_size ({tile_size}) at coord_mpp={coord_mpp} maps to "
			f"{tile_thumbpx:.3f} thumbnail pixels at thumb_mpp={thumb_mpp}. "
			"Tile-grid morphology requires at least 1 thumb pixel per "
			"tile. Use a finer thumbnail or call tile_tissue_status."
		)

	grid_h = int(np.ceil(H / tile_thumbpx))
	grid_w = int(np.ceil(W / tile_thumbpx))

	integral = np.zeros((H + 1, W + 1), dtype=np.int64)
	integral[1:, 1:] = (
		tissue_mask.astype(np.int64).cumsum(axis=0).cumsum(axis=1)
	)

	ys = np.minimum(
		np.round(np.arange(grid_h + 1) * tile_thumbpx).astype(np.int64), H
	)
	xs = np.minimum(
		np.round(np.arange(grid_w + 1) * tile_thumbpx).astype(np.int64), W
	)

	sums = (
		integral[ys[1:, None], xs[None, 1:]]
		- integral[ys[:-1, None], xs[None, 1:]]
		- integral[ys[1:, None], xs[None, :-1]]
		+ integral[ys[:-1, None], xs[None, :-1]]
	)
	areas = (ys[1:, None] - ys[:-1, None]) * (xs[None, 1:] - xs[None, :-1])
	fractions = np.where(areas > 0, sums / np.maximum(areas, 1), 0.0)

	seed = (fractions >= min_per_tile_fraction).astype(np.uint8)

	if min_component_tiles > 0 and seed.any():
		_, labels, stats, _ = cv2.connectedComponentsWithStats(
			seed, connectivity=8
		)
		keep = stats[:, cv2.CC_STAT_AREA] >= min_component_tiles
		keep[0] = False
		seed = keep[labels].astype(np.uint8)

	if closing_tiles > 0 and seed.any():
		k = 2 * closing_tiles + 1
		kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
		seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, kernel, iterations=1)

	if fill_interior_holes and max_interior_hole_tiles > 0 and seed.any():
		seed = _fill_holes(seed, max_hole_area_px=max_interior_hole_tiles)

	if dilate_tiles > 0 and seed.any():
		k = 2 * dilate_tiles + 1
		kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
		seed = cv2.dilate(seed, kernel, iterations=1)

	envelope = seed.astype(bool)

	cx = coords[:, 0].astype(np.float64)
	cy = coords[:, 1].astype(np.float64)
	gx = np.clip(np.floor(cx / tile_size).astype(np.int64), 0, grid_w - 1)
	gy = np.clip(np.floor(cy / tile_size).astype(np.int64), 0, grid_h - 1)

	return envelope[gy, gx]