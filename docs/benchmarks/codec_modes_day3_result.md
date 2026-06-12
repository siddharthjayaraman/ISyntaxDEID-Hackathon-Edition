# Day 3 codec mode benchmark

## Context

This benchmark was run after the two existing optimisation changes on `feature/jpegxl-effort-speed-test`:

1. JPEG XL effort reduced to 3.
2. Worker recycling disabled by setting `maxtasksperchild=None`.

The follow-up branch added valid Zarr pixel codec modes while preserving the existing sparse Zarr v2 output structure.

## Command

```bash
PYTHONPATH=src python scripts/benchmark_codec_modes.py ~/run_report/data/testslide.isyntax --threads 8 --runs 1 --out ~/run_report/benchmarks/codec_modes
```

## Result

| Writer mode | Median write s | Output MB | Speedup vs jpegxl |
|---|---:|---:|---:|
| jpegxl | 31.08 | 112.02 | 1.000x |
| raw | 32.79 | 3249.07 | 0.948x |
| blosc_lz4 | 33.65 | 2595.81 | 0.924x |
| blosc_zstd | 36.65 | 1895.89 | 0.848x |

## Interpretation

JPEG XL at effort 3 remains the fastest tested valid Zarr output mode and is dramatically smaller than the alternatives.

The raw output is slower despite removing compression, because the write volume increases to about 3.25 GB. Blosc LZ4 and Blosc Zstd are also slower and produce much larger archives than JPEG XL.

This result suggests that replacing JPEG XL with raw or standard Blosc codecs is not the next high-value optimisation path for this test slide.

The next target should be writer mechanics rather than codec replacement:

- native `read_region` time
- RGBA to RGB copy time
- Zarr array assignment time
- worker initialisation and scheduling overhead
- chunk file creation and final zip packaging
