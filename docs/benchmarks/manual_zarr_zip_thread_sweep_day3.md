# Day 3 manual Zarr ZIP thread sweep

## Context

The manual valid Zarr ZIP writer PoC was benchmarked across 1, 2, 4 and 8 worker processes using the same slide, JPEG XL effort 3 and the same sparse Zarr v2 output structure.

## Command

```bash
for t in 1 2 4 8; do
    PYTHONPATH=src python scripts/benchmark_manual_zarr_zip.py \
      ~/run_report/data/testslide.isyntax \
      --threads "$t" \
      --pixel-codec jpegxl \
      --out ~/run_report/benchmarks/manual_zarr_zip_threads/threads_${t}
done
```

## Summary

| Threads | Writer s | Total s | Pixel write s | Zip s | Output MB | Tissue tiles | Speedup vs 1 thread |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 79.886 | 80.450 | 76.725 | 2.588 | 113.136 | 22612 | 1.000x |
| 2 | 50.055 | 50.616 | 46.899 | 2.600 | 113.136 | 22612 | 1.596x |
| 4 | 33.665 | 34.229 | 30.472 | 2.635 | 113.136 | 22612 | 2.373x |
| 8 | 26.214 | 26.781 | 22.861 | 2.767 | 113.136 | 22612 | 3.047x |

## Worker event detail

| Threads | read_region total s | read_region mean ms | encode total s | encode mean ms | chunk file write total s | chunk file write mean ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 32.986 | 1.459 | 35.843 | 1.585 | 2.643 | 0.117 |
| 2 | 45.364 | 2.006 | 38.908 | 1.721 | 3.044 | 0.135 |
| 4 | 67.276 | 2.975 | 41.703 | 1.844 | 3.540 | 0.157 |
| 8 | 106.650 | 4.717 | 52.375 | 2.316 | 4.497 | 0.199 |

## Interpretation

The fastest tested setting was 8 threads with 26.214 seconds writer time.

The direct manual chunk file write component is small across all tested thread counts. The remaining bottleneck is dominated by native tile access and JPEG XL encoding, not metadata creation, Zarr group creation or final ZIP packaging.

Scaling is useful but sublinear. The mean `read_region` time increases as worker count rises, which suggests contention in native iSyntax access, storage, cache behaviour or process-level decoding. For this slide, 8 workers still gives the best single-slide wall time.

## Decision

Keep the manual valid Zarr ZIP writer as the strongest architecture PoC so far. The next evidence step should be validation against the standard writer output and, if more slides are available, a many-slides throughput comparison rather than further single-slide micro-optimisation.
