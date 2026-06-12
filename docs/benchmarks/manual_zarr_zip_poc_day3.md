# Day 3 manual valid Zarr ZIP writer PoC

## Context

Fine grained profiling showed that the main writer costs were native tile reads and Zarr chunk assignment. Zarr group creation and final ZIP packaging were not the main bottlenecks.

This PoC tested whether bypassing `pixels[y:y+ts, x:x+ts, :] = rgb` and writing encoded chunk files directly could reduce writer time while preserving a valid sparse Zarr v2 ZIP archive.

## Command

```bash
PYTHONPATH=src python scripts/benchmark_manual_zarr_zip.py ~/run_report/data/testslide.isyntax --threads 8 --pixel-codec jpegxl --out ~/run_report/benchmarks/manual_zarr_zip
```

## Result

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

| Worker event | Count | Total s | Mean s |
|---|---:|---:|---:|
| read_region | 22612 | 108.052 | 0.004779 |
| manual_encode | 22612 | 47.120 | 0.002084 |
| rgba_to_rgb | 22612 | 4.994 | 0.000221 |
| manual_chunk_file_write | 22612 | 3.908 | 0.000173 |

## Comparison with current optimised writer

| Writer | Threads | Writer seconds | Output MB | Validation |
|---|---:|---:|---:|---|
| Current Zarr assignment writer, JPEG XL effort 3 | 8 | 31.08 | 112.02 | pass |
| Manual valid Zarr ZIP PoC, JPEG XL effort 3 | 8 | 25.34 | 113.14 | pass |

## Interpretation

The manual writer reduced writer time from 31.08 seconds to 25.34 seconds on the same slide and thread count.

This is about a 1.23x writer speedup while keeping output size essentially unchanged and passing the existing inspection route.

The remaining dominant cost is now native `read_region`, followed by manual JPEG XL encode. Direct chunk file writing itself is small.

This result supports manual valid Zarr ZIP writing as a serious architecture candidate, not just a speculative optimisation.
