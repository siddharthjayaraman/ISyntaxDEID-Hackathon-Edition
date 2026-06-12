# RAM disk thread 4 result

## Experiment

Branch:

```text
feature/ramdisk-runner-wsl-lib
````

Input slide:

```text
~/run_report/data/testslide.isyntax
```

Comparison:

```text
baseline:
  unchanged pipeline
  input from disk
  output root on disk

ramdisk:
  unchanged pipeline logic
  input copied to /dev/shm
  output root on /dev/shm
  final output copied back to disk
```

Thread count:

```text
4
```

## Result

| Mode     | Total s | Zarr write s | Wall clock | Max RSS MB | ZIP MB |
| -------- | ------: | -----------: | ---------: | ---------: | -----: |
| baseline |   91.57 |        91.00 |    1:32.11 |    1213.17 | 124.92 |
| ramdisk  |   91.76 |        91.22 |    1:32.61 |    1193.77 | 124.92 |

Speedup:

```text
0.998x
```

Peak RSS delta:

```text
-19.40 MB
```

## Interpretation

RAM disk staging made the run marginally slower.

This suggests that, for this test slide and WSL setup, the conversion is not limited by disk backed scratch Zarr writes or ZIP staging.

The remaining likely bottlenecks are:

* native tile reads through libisyntax
* JPEG XL compression
* Python Zarr chunk assignment overhead
* multiprocessing task dispatch
* worker restart overhead from `maxtasksperchild=8`

## Decision

Do not continue optimising the RAM disk path unless a different machine or storage system shows disk I/O pressure.

Next experiment should target worker churn in `src/isyntax_deid/zarr_writer.py`.
