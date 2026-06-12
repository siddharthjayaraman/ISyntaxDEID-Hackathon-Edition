# JPEG XL effort 3 thread 4 result

## Change

This branch is stacked on the worker recycling optimisation:

```python
maxtasksperchild=None
```

It then changes the JPEG XL effort used by the Zarr writer call from the writer default:

```python
jpegxl_effort=5
```

to:

```python
jpegxl_effort=3
```

The JPEG XL distance remains unchanged:

```python
jpegxl_distance=1.0
```

## Benchmark

Input slide:

```text
~/run_report/data/testslide.isyntax
```

Thread count:

```text
4
```

## Result

| Mode | Total s | Zarr write s | Wall clock | Max RSS MB | ZIP size |
|---|---:|---:|---:|---:|---:|
| baseline | 91.57 | 91.00 | 1:32.11 | 1213.17 | 125M |
| worker recycling None | 79.82 | 79.18 | 1:20.32 | 8717.84 | 125M |
| worker recycling None + JPEG XL effort 3 | 41.66 | 41.07 | 0:42.19 | 8755.96 | 113M |

## Speedup

Versus baseline:

```text
total speedup:      2.20x
zarr_write speedup: 2.22x
```

Versus worker recycling only:

```text
total speedup:      1.92x
zarr_write speedup: 1.93x
```

## Validation

The output archive opened successfully with the repository inspection script.

The inspection reconstructed all tissue chunks:

```text
22612/22612 chunks
done in 44.7s
```

## Interpretation

JPEG XL encoder effort is a major bottleneck in this workload.

Lowering effort from 5 to 3 nearly halves the remaining runtime after worker recycling is disabled.

The output ZIP also became smaller in this test, from 125M to 113M. This was unexpected, but favourable for this slide.

## Decision

Keep this as the current best speed PoC.

This is not a bitwise equivalent output change because codec parameters changed, but it preserves the Zarr structure and validates with the provided inspection route.
