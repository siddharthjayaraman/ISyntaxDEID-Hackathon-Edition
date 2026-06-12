# Day 3 fine grained Zarr writer profile

## Context

This profile was run after the codec mode benchmark showed that JPEG XL effort 3 remained faster and much smaller than raw, Blosc LZ4 and Blosc Zstd.

The aim was to break the broad `zarr_write` timing into internal writer events.

## Command

```bash
PYTHONPATH=src python scripts/benchmark_zarr_profile.py ~/run_report/data/testslide.isyntax --threads 8 --pixel-codec jpegxl --out ~/run_report/benchmarks/zarr_profile
```

## Result

| Event | Count | Total s | Mean s |
|---|---:|---:|---:|
| tile.read_region | 22612 | 111.506 | 0.004931 |
| tile.zarr_assignment | 22612 | 87.230 | 0.003858 |
| pixels.write_parallel_total | 1 | 28.408 | 28.407995 |
| tile.rgba_to_rgb_contiguous | 22612 | 5.077 | 0.000225 |
| zip.directory | 1 | 2.818 | 2.818165 |
| worker.open_isyntax | 8 | 0.470 | 0.058727 |
| cleanup.scratch_rmtree | 1 | 0.333 | 0.333465 |
| metadata.populate_group | 1 | 0.193 | 0.193035 |
| worker.open_zarr_pixels | 8 | 0.079 | 0.009895 |
| output.atomic_replace | 1 | 0.000 | 0.000020 |
| store.create_local | 1 | 0.000 | 0.000013 |
| output.final_size | 1 | 0.000 | 0.000000 |

## Interpretation

The dominant costs are native tile access and Zarr chunk assignment.

The cumulative worker timings are larger than wall time because they are summed across 8 worker processes. The wall time for the parallel pixel write section was 28.41 seconds.

Approximate wall equivalent from worker totals:

| Component | Worker total s | Approx wall equivalent at 8 workers |
|---|---:|---:|
| native read_region | 111.51 | 13.94 |
| Zarr assignment | 87.23 | 10.90 |
| RGBA to RGB copy | 5.08 | 0.63 |

This rules out Zarr group creation as a meaningful bottleneck. It also suggests that ZIP packaging is not the main bottleneck for this slide.

## Decision

The next evidence based PoC should target Zarr pixel chunk assignment overhead.

The most useful next experiment is a manual valid Zarr ZIP writer that bypasses `pixels[y:y+ts, x:x+ts, :] = rgb` while preserving the same sparse Zarr v2 output contract.

The experiment should not change tissue detection, candidate coordinates, tile coordinates, tile size or JPEG XL settings.
