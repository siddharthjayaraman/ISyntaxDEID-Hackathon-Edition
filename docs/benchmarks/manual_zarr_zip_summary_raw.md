# Manual valid Zarr ZIP writer PoC

Zarr path: `/home/sjayaram/run_report/benchmarks/manual_zarr_zip/testslide_manual_jpegxl/testslide_manual_jpegxl.zarr.zip`

| Metric | Value |
|---|---:|
| prep_seconds | 0.574 |
| writer_seconds | 25.338 |
| total_seconds | 25.912 |
| metadata_arrays_seconds | 0.174 |
| manual_pixels_parallel_seconds | 22.168 |
| zip_directory_seconds | 2.624 |
| atomic_replace_seconds | 0.000 |
| cleanup_seconds | 0.322 |
| output_size_mb | 113.136 |
| n_candidate_tiles | 54116 |
| n_tissue_tiles | 22612 |

## Worker event summary

| Event | Count | Total s | Mean s | Median s | Max s |
|---|---:|---:|---:|---:|---:|
| read_region | 22612 | 108.052 | 0.004779 | 0.002736 | 0.189896 |
| manual_encode | 22612 | 47.120 | 0.002084 | 0.002004 | 0.006530 |
| rgba_to_rgb | 22612 | 4.994 | 0.000221 | 0.000195 | 0.000751 |
| manual_chunk_file_write | 22612 | 3.908 | 0.000173 | 0.000163 | 0.001709 |
