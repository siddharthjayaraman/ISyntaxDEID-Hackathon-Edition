# Worker recycling thread 4 result

## Change

Changed worker recycling in `src/isyntax_deid/zarr_writer.py`.

Original baseline:

```python
maxtasksperchild=8
```

Tested values:

```python
maxtasksperchild=256
maxtasksperchild=None
```

Final selected value:

```python
maxtasksperchild=None
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

| Mode | Total s | Zarr write s | Wall clock | Max RSS MB |
|---|---:|---:|---:|---:|
| baseline, maxtasksperchild 8 | 91.57 | 91.00 | 1:32.11 | 1213.17 |
| maxtasksperchild 256 | 80.79 | 80.25 | 1:21.28 | 8849.09 |
| maxtasksperchild None | 79.82 | 79.18 | 1:20.32 | 8717.84 |

## Best result

```text
Best setting: maxtasksperchild=None
```

Speedup versus baseline:

```text
total speedup:      1.147x
zarr_write speedup: 1.149x
```

## Memory interpretation

Peak RSS increased from about 1.2 GB to about 8.7 GB.

For a speed focused 4 worker hackathon proof of concept, this is acceptable on a workstation or node with sufficient RAM.

## Interpretation

Disabling worker recycling gives a meaningful runtime win.

Likely mechanism:

- avoids repeated worker process restarts
- avoids repeated `ISyntaxWSI` initialisations
- avoids repeated Zarr group and pixel array reopen operations
- reduces multiprocessing process churn

## Decision

Keep `maxtasksperchild=None` and stack further optimisation tests on top.
