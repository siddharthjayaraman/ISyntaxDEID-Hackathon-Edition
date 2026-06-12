# Best branch thread scaling result

## Branch context

This benchmark was run on the branch with both speed optimisations stacked:

```text
feature/jpegxl-effort-speed-test
```

Code changes included:

```python
maxtasksperchild=None
```

and:

```python
jpegxl_effort=3
```

The JPEG XL distance remained unchanged:

```python
jpegxl_distance=1.0
```

## Input slide

```text
~/run_report/data/testslide.isyntax
```

## Thread scaling result

| Threads | Total s | Zarr write s | Wall clock | Max RSS MB | ZIP size |
|---:|---:|---:|---:|---:|---:|
| 1 | 109.87 | 109.31 | 1:50.36 | 10341.28 | 113M |
| 2 | 64.02 | 63.52 | 1:04.49 | 9556.69 | 113M |
| 4 | 40.92 | 40.39 | 0:41.44 | 8720.73 | 113M |
| 8 | 31.13 | 30.59 | 0:31.66 | 6671.16 | 113M |

## Best setting

```text
threads=8
```

Best observed runtime:

```text
total:      31.13 s
zarr_write: 30.59 s
wall clock: 0:31.66
```

## Comparison with original thread 4 baseline

Original thread 4 baseline:

```text
total:      91.57 s
zarr_write: 91.00 s
ZIP size:   125M
```

Best stacked result:

```text
total:      31.13 s
zarr_write: 30.59 s
ZIP size:   113M
```

Speedup:

```text
total speedup:      2.94x
zarr_write speedup: 2.98x
```

## Interpretation

The combined optimisation substantially improves runtime.

The two main wins are:

1. Disabling worker recycling avoids repeated worker process and slide initialisation overhead.
2. Lowering JPEG XL effort from 5 to 3 greatly reduces encode time.

Thread scaling remains positive up to 8 workers on this machine.

## Decision

Report the best current PoC as:

```text
maxtasksperchild=None
jpegxl_effort=3
threads=8
```

This is a speed optimised PoC. It preserves the Zarr structure and validates with the repository inspection route, but codec output is not bitwise equivalent to the original effort 5 output.
