# Best branch thread scaling and throughput result

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

## Original baseline

The original comparison baseline was the unchanged pipeline at 4 threads:

```text
total:      91.57 s
zarr_write: 91.00 s
ZIP size:   125M
```

## Single-slide thread scaling result

| Threads per slide | Total s | Zarr write s | Wall clock | Max RSS MB | ZIP size |
|---:|---:|---:|---:|---:|---:|
| 1 | 109.87 | 109.31 | 1:50.36 | 10341.28 | 113M |
| 2 | 64.02 | 63.52 | 1:04.49 | 9556.69 | 113M |
| 4 | 40.92 | 40.39 | 0:41.44 | 8720.73 | 113M |
| 8 | 31.13 | 30.59 | 0:31.66 | 6671.16 | 113M |

## Single-slide latency interpretation

The fastest single-slide latency observed was:

```text
threads=8
total:      31.13 s
zarr_write: 30.59 s
wall clock: 0:31.66
```

Compared with the original 4 thread baseline, this gives:

```text
total speedup:      2.94x
zarr_write speedup: 2.98x
```

However, this is not the same as the best batch-processing strategy.

The thread scaling is clearly sublinear:

```text
1 to 2 threads: 1.72x
1 to 4 threads: 2.69x
1 to 8 threads: 3.53x
```

So using all 8 cores for one slide improves latency, but it does not give 8x throughput.

## Estimated batch throughput on an 8 core CPU

Using the measured single-slide runtimes, the estimated slide throughput on an 8 core CPU is:

| Batch strategy | Approx slides per hour | Interpretation |
|---|---:|---|
| 1 slide x 8 threads | 115.6 | Best single-slide latency |
| 2 slides x 4 threads | 175.9 | Better batch throughput |
| 4 slides x 2 threads | 224.9 | Better batch throughput |
| 8 slides x 1 thread | 262.1 | Highest estimated throughput from this simple model |

This means the best production strategy for millions of slides is probably not one slide using all CPU cores.

For large-scale batch processing, the current benchmark suggests that running multiple slides concurrently with fewer threads per slide may process more slides per machine per hour.

The practical deployment question should therefore be:

```text
Which combination of slides in parallel and threads per slide maximises slides per hour without exceeding memory and I/O limits?
```

A direct batch benchmark should compare:

```text
1 slide x 8 threads
2 slides x 4 threads
4 slides x 2 threads
8 slides x 1 thread
```

## Two optimisations that produced the current speedup

### 1. Disable worker recycling

Original worker pool setting:

```python
maxtasksperchild=8
```

Optimised setting:

```python
maxtasksperchild=None
```

This avoids repeated worker process restarts, repeated `ISyntaxWSI` initialisation, and repeated Zarr array reopening.

At 4 threads, this reduced runtime from:

```text
91.57 s to 79.82 s
```

### 2. Lower JPEG XL effort from 5 to 3

Original effective setting:

```python
jpegxl_effort=5
```

Optimised setting:

```python
jpegxl_effort=3
```

The JPEG XL distance was kept unchanged:

```python
jpegxl_distance=1.0
```

At 4 threads, after disabling worker recycling, this reduced runtime from:

```text
79.82 s to 41.66 s
```

At 8 threads, the combined result was:

```text
31.13 s total runtime
```

## Codec effort lower bound

The current repository validation restricts JPEG XL effort to values from 3 to 9.

However, upstream JPEG XL tooling supports lower effort values. The lower bound of 3 therefore appears to be a conservative local guard rather than a demonstrated biological or AI-training constraint.

Because effort 3 produced the largest measured runtime improvement so far, efforts below 3 should be tested as additional extreme speed modes, for example:

```text
jpegxl_effort=2
jpegxl_effort=1
```

Those lower efforts should not be adopted blindly. They should be evaluated with:

```text
runtime
ZIP size
decoded tile mean absolute error
max absolute pixel difference
sample tile visual checks
possibly downstream model sanity checks
```

## Decision

Report the current best single-slide latency proof of concept as:

```text
maxtasksperchild=None
jpegxl_effort=3
threads=8
```

Report the current batch-processing implication as:

```text
For millions of slides, optimise slides per hour per machine, not only seconds per slide.
The current scaling results suggest that multiple concurrent slides with fewer threads per slide may outperform one highly threaded slide.
```

This is a speed optimised proof of concept. It preserves the Zarr structure and validates with the repository inspection route, but codec output is not bitwise equivalent to the original effort 5 output.
