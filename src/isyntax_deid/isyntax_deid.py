import logging
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from isyntax_deid.metadata.extractor import extract_metadata, flatten_metadata
from isyntax_deid.thumbnail_extractor import extract_thumbnail
from isyntax_deid.coordinates import generate_tile_coordinates, visualise_tile_coordinates
from isyntax_deid.tissue_detection import detect_tissue, tissue_region_mask, tile_envelope_status
import isyntax_deid.zarr_writer as zarr_writer


class ISyntaxDeID:
	"""Converts a single local ``.isyntax`` slide into a sparse ``.zarr.zip``.

	After ``process_slide`` returns, ``self.timings`` holds the wall-clock
	seconds spent in each stage -- this is what the hackathon benchmark reads.
	"""

	def __init__(self, config):
		self.config = config
		self.logger = logging.getLogger(self.__class__.__name__)
		self.timings: dict[str, float] = {}

	@contextmanager
	def _stage(self, name: str):
		start = time.perf_counter()
		yield
		self.timings[name] = time.perf_counter() - start

	def process_slide(
		self,
		slide_path: Path,
		slide_id: str,
		output_root: Path,
		force: bool = False,
		save_visuals: bool = True,
	) -> Path | None:
		"""Convert one slide. Returns the path to the ``.zarr.zip`` or None.

		Args:
			slide_path: local ``.isyntax`` file.
			slide_id: output stem; the result is ``{output_root}/{slide_id}/{slide_id}.zarr.zip``.
			output_root: directory under which the per-slide output dir is created.
			save_visuals: also write the thumbnail + tissue-overlay PNGs (QA only;
				set False in benchmarks to measure pure conversion cost).
		"""
		slide_output_dir = Path(output_root) / slide_id
		self.timings = {}

		try:
			self.logger.info(f"Processing: {slide_path.name}")
			slide_output_dir.mkdir(parents=True, exist_ok=True)

			with self._stage("metadata"):
				raw_metadata = extract_metadata(
					slide_path, self.config.pipeline_version,
					self.config.libisyntax_version, slide_id=slide_id,
				)
				metadata = flatten_metadata(raw_metadata)
				pd.DataFrame([metadata]).to_csv(slide_output_dir / f"{slide_id}.csv", index=False)

			with self._stage("thumbnail"):
				thumbnail = extract_thumbnail(str(slide_path), target_mpp=self.config.thumbnail_mpp)
				thumbnail_mpp = thumbnail.info.get("mpp_x", self.config.thumbnail_mpp)

			with self._stage("coordinates"):
				coords = generate_tile_coordinates(metadata["width"], metadata["height"])

			with self._stage("tissue_detection"):
				mask = tissue_region_mask(detect_tissue(thumbnail))
				status = tile_envelope_status(
					coords, self.config.tile_size, mask, thumbnail_mpp, metadata["mpp_x"],
				)

			if save_visuals:
				with self._stage("visuals"):
					vis = visualise_tile_coordinates(
						coords, thumbnail, thumbnail_mpp, metadata["mpp_x"], is_tissue=status,
					)
					vis.save(slide_output_dir / f"{slide_id}_tissue_coordinates.png")
					thumbnail.save(slide_output_dir / f"{slide_id}_thumbnail.png")

			with self._stage("zarr_write"):
				zarr_path = zarr_writer.write_slide_zarr(
					slide_metadata=raw_metadata, candidate_coords=coords, tissue_status=status,
					thumbnail=thumbnail, thumbnail_mpp=thumbnail_mpp, output_dir=slide_output_dir,
					pseudonym=slide_id, tile_size=self.config.tile_size, jpegxl_distance=1.0,
					n_workers=self.config.threads_per_slide,
				)

			self.timings["total"] = sum(
				v for k, v in self.timings.items() if k != "total"
			)
			return zarr_path
		except Exception as e:
			self.logger.error(f"Failed {slide_id}: {e}", exc_info=True)
			return None
