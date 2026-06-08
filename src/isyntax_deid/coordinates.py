"""Tile coordinate generation for WSI tiling.

Pure-math coordinate generator: given a rectangular region, produce the
top-left (x, y) origin of every tile that fits. No I/O, no WSI knowledge —
the function is scale-agnostic, so the caller decides what `width`,
`height`, `tile_size`, and `stride` mean in their coordinate system.

The conventional choice for pathology is **level-0 (native) pixel space**:
tile coordinates survive the switch from one pyramid level to another
because they describe a physical slide position, not a pixel position in
a particular level. When extracting tiles at a non-native MPP, scale the
coordinates back to that level using the pyramid's downsample factor.

Typical flow for 224x224 non-overlapping tiles:

	from isyntax_deid.coordinates.tiles import generate_tile_coordinates

	coords = generate_tile_coordinates(
		width=slide_width_level0,
		height=slide_height_level0,
		tile_size=224,
		stride=224,
	)  # shape (N, 2), dtype int64, columns are [x, y]

To restrict to a tissue region from a thumbnail-derived mask, pass the
bounding box of that mask scaled to level-0 coordinates via `x_min` /
`y_min` / `x_max` / `y_max`. To drop tiles whose centres miss tissue,
index the mask at `(coords * scale).astype(int)` and filter — a separate
concern from coordinate generation, so it lives elsewhere.
"""
from __future__ import annotations

from typing import Literal, Sequence

import numpy as np
from PIL import Image, ImageDraw


def generate_tile_coordinates(
	width: int,
	height: int,
	tile_size: int = 224,
	stride: int | None = None,
	*,
	x_min: int = 0,
	y_min: int = 0,
	x_max: int | None = None,
	y_max: int | None = None,
	edge: Literal["skip", "fit"] = "skip",
	dtype=np.int64,
) -> np.ndarray:
	"""Generate tile top-left coordinates tiling a rectangular region.

	Parameters
	----------
	width, height : int
		Bounds of the enclosing image, in whatever pixel space the caller
		is working in (typically level-0 for WSIs). Tiles must fit within
		[0, width) x [0, height).
	tile_size : int
		Side length of each tile in pixels. Default 224 — the input size
		for ResNet, EfficientNet, ViT-B/16 and most other ImageNet-
		pretrained backbones, so tiles are model-ready without further
		resizing.
	stride : int | None
		Spacing between successive tile origins. None defaults to
		`tile_size` (non-overlapping tiles — the standard choice for
		training). Use `tile_size // 2` for 50% overlap (common for
		inference to suppress tile-boundary artefacts).
	x_min, y_min : int
		Top-left of the tiling region. Default (0, 0). Set these to the
		tissue bounding box to skip the empty margin around a slide —
		saves a large fraction of the coordinates on slides where tissue
		covers a small area of the scan.
	x_max, y_max : int | None
		Bottom-right (exclusive) of the tiling region. None means the
		full `width` / `height`. No tile origin is emitted at or beyond
		these values, and no tile extends past them.
	edge : {"skip", "fit"}
		How to handle the right and bottom edges when the region size
		minus `tile_size` is not an exact multiple of `stride`.
		  - "skip" (default): stop at the last origin where a full tile
		    still fits. Up to `tile_size - 1` pixels at the far edge may
		    be uncovered. This is what almost every tiling pipeline does,
		    and is the right default for training-data generation.
		  - "fit": after the skip-style series, append one extra origin
		    at `region_max - tile_size` so the final tile ends exactly
		    at the edge. Guarantees 100% coverage at the cost of a non-
		    uniform stride on the boundary row/column (the last two
		    tiles overlap by whatever remainder existed). Use this when
		    you cannot afford to miss edge tissue — e.g. inference on
		    small biopsies where the tissue runs to the scan edge.
	dtype : numpy dtype
		Output dtype. Default `np.int64`. `np.int32` is safe for any
		realistic WSI (max ~2e9) and halves memory if you are producing
		many millions of coordinates and feeding them into a GPU
		pipeline.

	Returns
	-------
	np.ndarray
		Shape (N, 2) array where each row is (x, y), the top-left origin
		of one tile. When `edge="skip"`, N == nx * ny and you can
		recover the 2D grid via `coords.reshape(ny, nx, 2)`; with
		`edge="fit"` the grid may be ragged so reshape is not safe.
		Returns an empty (0, 2) array when the region is too small for
		even one tile — callers iterating with `for x, y in coords:`
		then simply see no tiles, rather than hitting an exception.

	Raises
	------
	ValueError
		`tile_size` or `stride` non-positive, the tiling region is
		outside the image bounds, or `edge` is not one of the allowed
		values.
	"""
	if tile_size <= 0:
		raise ValueError(f"tile_size must be positive, got {tile_size}")
	if stride is None:
		stride = tile_size
	if stride <= 0:
		raise ValueError(f"stride must be positive, got {stride}")
	if width <= 0 or height <= 0:
		raise ValueError(
			f"width and height must be positive, got ({width}, {height})"
		)

	if x_max is None:
		x_max = width
	if y_max is None:
		y_max = height

	if x_min < 0 or y_min < 0 or x_max > width or y_max > height:
		raise ValueError(
			f"tiling region ({x_min}, {y_min})-({x_max}, {y_max}) "
			f"falls outside image bounds (0, 0)-({width}, {height})"
		)
	if x_max <= x_min or y_max <= y_min:
		raise ValueError(
			f"tiling region ({x_min}, {y_min})-({x_max}, {y_max}) "
			f"has non-positive area"
		)

	# Last valid origin in each axis is the largest value `o` such that
	# `o + tile_size <= region_max`. np.arange's stop is exclusive, so
	# we pass `region_max - tile_size + 1` to include origins that place
	# the tile's right edge exactly on region_max.
	x_stop = x_max - tile_size + 1
	y_stop = y_max - tile_size + 1

	if x_stop <= x_min or y_stop <= y_min:
		# Region too small for even one tile. Empty result rather than
		# raise — simplifies calling code that iterates unconditionally
		# (e.g. a batch driver that applies a tissue bounding box per
		# slide and sometimes gets a very small bbox).
		return np.empty((0, 2), dtype=dtype)

	xs = np.arange(x_min, x_stop, stride, dtype=dtype)
	ys = np.arange(y_min, y_stop, stride, dtype=dtype)

	if edge == "fit":
		# Append an aligned-to-edge origin if the last regular tile
		# doesn't reach the far side of the region. This is the only
		# place the function emits a non-uniform stride.
		last_x_end = int(xs[-1]) + tile_size
		if last_x_end < x_max:
			xs = np.concatenate(
				[xs, np.array([x_max - tile_size], dtype=dtype)]
			)
		last_y_end = int(ys[-1]) + tile_size
		if last_y_end < y_max:
			ys = np.concatenate(
				[ys, np.array([y_max - tile_size], dtype=dtype)]
			)
	elif edge != "skip":
		raise ValueError(
			f"edge must be 'skip' or 'fit', got {edge!r}"
		)

	# Cartesian product via meshgrid, flatten to (N, 2). `indexing="xy"`
	# plus column-stacking x first, y second means row-major iteration
	# moves across x first — matches the natural scan order people
	# expect when debugging.
	xv, yv = np.meshgrid(xs, ys, indexing="xy")
	return np.column_stack([xv.ravel(), yv.ravel()])


def visualise_tile_coordinates(
	coords: np.ndarray,
	thumbnail: Image.Image,
	thumb_mpp: float,
	coord_mpp: float,
	tile_size: int = 224,
	is_tissue: np.ndarray | Sequence[bool] | None = None,
	*,
	alpha: int = 96,
	tissue_colour: tuple[int, int, int] = (255, 255, 0),
	background_colour: tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
	"""Render tile coordinates as coloured rectangles on top of a thumbnail.

	The coordinates live in `coord_mpp` pixel space (typically level-0 for
	WSIs at 0.25 MPP) while the thumbnail lives in `thumb_mpp` space
	(typically 4 or 8 MPP). This function scales each tile's position and
	footprint from coordinate space to thumbnail space before drawing,
	so a single call visualises the full slide at thumbnail resolution.

	Parameters
	----------
	coords : np.ndarray
		Shape (N, 2) array of tile top-left origins in `coord_mpp` pixel
		space, as returned by `generate_tile_coordinates`.
	thumbnail : PIL.Image.Image
		Slide thumbnail to draw over. Not mutated — the returned image
		is a new object in RGB mode.
	thumb_mpp : float
		Microns per pixel of the thumbnail. Read from
		`thumbnail.info["mpp_x"]` when using the thumbnail extractor in
		this repo.
	coord_mpp : float
		Microns per pixel at which the tile coordinates are expressed.
		For level-0-space coordinates on a 40x WSI, this is 0.25.
	tile_size : int
		Side length of each tile in `coord_mpp` pixels. Must match the
		value passed to `generate_tile_coordinates` — otherwise the
		drawn rectangles will not reflect the tiles you actually
		extract. Default 224 for CNN-ready tiles.
	is_tissue : array-like of bool, or None
		Per-tile classification. True -> `tissue_colour`, False ->
		`background_colour`. Length must equal `coords.shape[0]`. When
		None (default), every tile is drawn in `tissue_colour` — useful
		for visualising the pre-filter coordinate grid.
	alpha : int
		Opacity (0-255) of each rectangle. Default 96 (~38%). Low enough
		to see the tissue through the overlay even when tiles are dense;
		bump toward 255 for presentation figures where legibility of the
		overlay matters more than seeing the underlying stain.
	tissue_colour, background_colour : (R, G, B)
		RGB fills for the two tile classes. Defaults: red (255, 0, 0)
		for tissue, black (0, 0, 0) for background.

	Returns
	-------
	PIL.Image.Image
		RGB image the same size as `thumbnail`, with tile rectangles
		composited on top. Save as PNG or JPEG.

	Raises
	------
	ValueError
		`coords` is not shape (N, 2); `is_tissue` length mismatches
		`coords`; or any MPP is non-positive.

	Notes
	-----
	At the typical scale of a tissue-detection thumbnail (8 MPP) with
	level-0 coordinates (0.25 MPP) and 224-pixel tiles, each rectangle
	is only ~7 thumbnail pixels on a side. The rendering is still
	useful — dense tissue tiles visibly tint the slide red, letting you
	spot-check tissue detection at a glance — but individual tile
	boundaries will not be distinguishable. For finer inspection, pass
	a higher-resolution thumbnail (4 MPP → ~14 px tiles, 2 MPP → ~28 px
	tiles) or crop to a region of interest before calling.
	"""
	if coords.ndim != 2 or coords.shape[1] != 2:
		raise ValueError(
			f"coords must be shape (N, 2), got {coords.shape}"
		)
	if thumb_mpp <= 0 or coord_mpp <= 0:
		raise ValueError(
			f"mpp values must be positive, got "
			f"thumb_mpp={thumb_mpp}, coord_mpp={coord_mpp}"
		)
	if tile_size <= 0:
		raise ValueError(f"tile_size must be positive, got {tile_size}")
	if not 0 <= alpha <= 255:
		raise ValueError(f"alpha must be in [0, 255], got {alpha}")

	n = coords.shape[0]
	if is_tissue is not None:
		is_tissue_arr = np.asarray(is_tissue, dtype=bool)
		if is_tissue_arr.shape != (n,):
			raise ValueError(
				f"is_tissue length {is_tissue_arr.shape} does not match "
				f"coords length ({n},)"
			)
	else:
		is_tissue_arr = None

	# Coord-space → thumb-space scale. A tile `tile_size` pixels wide at
	# `coord_mpp` covers `tile_size * coord_mpp` microns of physical
	# slide; at `thumb_mpp` that is `tile_size * coord_mpp / thumb_mpp`
	# thumbnail pixels.
	scale = coord_mpp / thumb_mpp
	tile_thumb_size = tile_size * scale

	# Work in RGBA so the overlay alpha composites correctly. Convert
	# back to RGB on the way out — WSI thumbnails have no meaningful
	# alpha channel and the extra plane just confuses downstream saves
	# (JPEG doesn't support alpha, PNG saves 33% larger for no gain).
	base = thumbnail.convert("RGBA")
	overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
	draw = ImageDraw.Draw(overlay)

	tissue_rgba = (*tissue_colour, alpha)
	background_rgba = (*background_colour, alpha)

	tw, th = base.size

	# Vectorise the scale + clip — 50K tiles is still fast in a Python
	# loop, but pre-computing in numpy avoids a hot-path multiplication
	# per iteration and makes the clipping branch-free.
	xs_thumb = coords[:, 0].astype(np.float64) * scale
	ys_thumb = coords[:, 1].astype(np.float64) * scale
	x1s = np.clip(xs_thumb, 0.0, tw)
	y1s = np.clip(ys_thumb, 0.0, th)
	x2s = np.clip(xs_thumb + tile_thumb_size, 0.0, tw)
	y2s = np.clip(ys_thumb + tile_thumb_size, 0.0, th)

	# Round to integer pixels once. PIL's rectangle accepts floats but
	# rounds internally per call; doing it here is ~equivalent but lets
	# us skip degenerate zero-area tiles cheaply.
	x1i = x1s.round().astype(int)
	y1i = y1s.round().astype(int)
	x2i = x2s.round().astype(int)
	y2i = y2s.round().astype(int)

	for i in range(n):
		if x2i[i] <= x1i[i] or y2i[i] <= y1i[i]:
			# Tile fell entirely outside the thumbnail after clipping —
			# can happen with a stale coords array or a thumbnail that
			# was cropped after coord generation. Skip silently.
			continue
		colour = (
			tissue_rgba
			if is_tissue_arr is None or is_tissue_arr[i]
			else background_rgba
		)
		# Pass x2-1, y2-1 so adjacent tiles don't overlap by a pixel
		# under PIL's inclusive rectangle convention — avoids darker
		# bands where two semi-transparent fills stack at shared edges.
		draw.rectangle(
			[int(x1i[i]), int(y1i[i]), int(x2i[i]) - 1, int(y2i[i]) - 1], outline=colour, fill=None
		)

	return Image.alpha_composite(base, overlay).convert("RGB")