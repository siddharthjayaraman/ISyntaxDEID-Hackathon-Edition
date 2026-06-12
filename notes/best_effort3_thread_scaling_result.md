# Thread matched and batch throughput result

## Branch context

This benchmark was run on:

```text
feature/jpegxl-effort-speed-test
```

The branch stacks two optimisation changes:

```python
maxtasksperchild=None
```

and:

```python
jpegxl_effort=3
```

The JPEG XL distance was unchanged:

```python
jpegxl_distance=1.0
```

## Input slide

```text
~/run_report/data/testslide.isyntax
```

## Thread matched comparison

This compares the original baseline and the optimised branch at the same thread count.

| Threads per slide | Baseline total s | Optimised total s | Same-thread total speedup | Baseline Zarr write s | Optimised Zarr write s | Same-thread Zarr speedup | Parallel slides on 8 cores | Baseline batch slides/hour | Optimised batch slides/hour |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 314.39 | 109.87 | 2.861x | 313.97 | 109.31 | 2.872x | 8 | 91.61 | 262.13 |
| 2 | 163.89 | 64.02 | 2.560x | 163.45 | 63.52 | 2.573x | 4 | 87.86 | 224.93 |
| 4 | 90.82 | 40.92 | 2.219x | 90.38 | 40.39 | 2.238x | 2 | 79.28 | 175.95 |
| 8 | 58.64 | 31.13 | 1.884x | 58.19 | 30.59 | 1.902x | 1 | 61.39 | 115.64 |

## Correct interpretation

The optimised branch improves runtime at every matched thread count.

The strongest same-thread speedup is at one thread:

```text
1 thread:
  total speedup:      2.861x
  zarr_write speedup: 2.872x
```

The fastest single-slide latency is at eight threads:

```text
8 threads:
  total:      31.13 s
  zarr_write: 30.59 s
```

However, eight threads per slide is not the best strategy for a large batch of slides on an eight core CPU.

## Batch throughput interpretation

The project needs to process a very large number of images, so the more important production metric is:

```text
slides per hour per machine
```

not only:

```text
seconds per slide
```

Using the measured single-slide runtimes and assuming an eight core CPU, the best estimated batch throughput from this test is:

```text
8 slides in parallel x 1 thread per slide:
  262.13 slides/hour
```

The estimated batch-throughput ranking is:

| Batch strategy on 8 cores | Estimated optimised throughput |
|---|---:|
| 8 slides x 1 thread | 262.13 slides/hour |
| 4 slides x 2 threads | 224.93 slides/hour |
| 2 slides x 4 threads | 175.95 slides/hour |
| 1 slide x 8 threads | 115.64 slides/hour |

This means that although eight threads gives the lowest latency for one slide, the current data suggests that large-scale batch conversion may be faster by running more slides concurrently with fewer threads per slide.

This should be validated with true concurrent multi-slide runs because the estimate does not capture shared I/O contention, memory pressure, scheduler behaviour, or native library contention.

## Two optimisations that led to the improvement

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

At four threads, this reduced runtime from:

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

At four threads, after disabling worker recycling, this reduced runtime from:

```text
79.82 s to 40.92 s
```

## JPEG XL effort lower bound

The current repository validation restricts JPEG XL effort to values from 3 to 9.

Given the large improvement from effort 5 to effort 3, this lower bound should be treated as an open optimisation question rather than a fixed constraint.

The next codec sweep should test lower effort values, for example:

```text
jpegxl_effort=2
jpegxl_effort=1
```

Those modes should be evaluated as extreme speed modes, not adopted blindly.

Recommended validation for lower effort values:

```text
runtime
ZIP size
decoded tile mean absolute error
max absolute pixel difference
sample tile visual checks
possibly downstream model sanity checks
```

## Recommendation

Report the current code-level proof of concept as:

```text
maxtasksperchild=None
jpegxl_effort=3
```

For single-slide latency, the fastest observed setting was:

```text
threads=8
total=31.13 s
```

For batch processing on an eight core CPU, the best estimated strategy from this test was:

```text
8 concurrent slides x 1 thread per slide
estimated throughput=262.13 slides/hour
```

The next production-oriented benchmark should directly test:

```text
1 slide x 8 threads
2 slides x 4 threads
4 slides x 2 threads
8 slides x 1 thread
```

The current branch preserves the Zarr structure and validates with the repository inspection route, but codec output is not bitwise equivalent to the original effort 5 output.
