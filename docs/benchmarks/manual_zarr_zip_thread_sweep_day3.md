# Day 3 manual Zarr ZIP thread sweep

## Context

The manual valid Zarr ZIP writer PoC was benchmarked across 1, 2, 4 and 8 worker processes using the same slide, JPEG XL effort 3 and the same sparse Zarr v2 output structure.

This sweep must be interpreted in two different ways:

1. Single-slide latency: fastest wall time for one slide.
2. Batch throughput: fastest total slides per hour on a fixed CPU budget.

These are not the same optimisation target.

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

## Single-slide result

| Threads per slide | Writer s | Total s | Pixel write s | Zip s | Output MB | Tissue tiles | Single-slide speedup vs 1 thread |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 79.886 | 80.450 | 76.725 | 2.588 | 113.136 | 22612 | 1.000x |
| 2 | 50.055 | 50.616 | 46.899 | 2.600 | 113.136 | 22612 | 1.596x |
| 4 | 33.665 | 34.229 | 30.472 | 2.635 | 113.136 | 22612 | 2.373x |
| 8 | 26.214 | 26.781 | 22.861 | 2.767 | 113.136 | 22612 | 3.048x |

## Batch throughput estimate on 8 cores

This assumes a fixed 8-core budget and uses the measured writer time.

| Threads per slide | Parallel slides on 8 cores | Writer s | Estimated slides/hour | Batch throughput interpretation |
|---:|---:|---:|---:|---|
| 1 | 8 | 79.886 | 360.5 | Best estimated bulk throughput |
| 2 | 4 | 50.055 | 287.7 | Lower batch throughput than 1 thread |
| 4 | 2 | 33.665 | 213.8 | Lower batch throughput than 1 or 2 threads |
| 8 | 1 | 26.214 | 137.3 | Best single-slide latency, worst batch throughput |

## Worker event detail

| Threads | read_region total s | read_region mean ms | encode total s | encode mean ms | chunk file write total s | chunk file write mean ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 32.986 | 1.459 | 35.843 | 1.585 | 2.643 | 0.117 |
| 2 | 45.364 | 2.006 | 38.908 | 1.721 | 3.044 | 0.135 |
| 4 | 67.276 | 2.975 | 41.703 | 1.844 | 3.540 | 0.157 |
| 8 | 106.650 | 4.717 | 52.375 | 2.316 | 4.497 | 0.199 |

## Interpretation

The fastest tested single-slide latency was 8 threads, with 26.214 seconds writer time.

That does not mean 8 threads is the best production setting for a fixed CPU budget.

For batch conversion, 1 thread per slide is likely better because an 8-core machine can process 8 slides concurrently. Using the measured writer times, the estimated throughput is about 360 slides/hour at 1 thread per slide versus about 137 slides/hour at 8 threads per slide.

Scaling is useful for single-slide latency but sublinear. The mean `read_region` time increases as worker count rises, which suggests contention in native iSyntax access, storage, cache behaviour or process-level decoding.

The direct manual chunk file write component is small across all tested thread counts. The remaining bottleneck is dominated by native tile access and JPEG XL encoding, not metadata creation, Zarr group creation or final ZIP packaging.

## Decision

Keep the manual valid Zarr ZIP writer as the strongest architecture PoC so far.

For production style throughput, the more important test is not more single-slide optimisation. The next evidence step should be a multi-slide batch benchmark comparing:

- 8 slides running at 1 thread each
- 4 slides running at 2 threads each
- 2 slides running at 4 threads each
- 1 slide running at 8 threads

This will test whether the estimated batch throughput holds when multiple `.isyntax` files are read and written concurrently on the same machine.
