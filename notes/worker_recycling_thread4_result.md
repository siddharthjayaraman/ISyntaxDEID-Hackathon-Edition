# Worker recycling thread 4 result

## Change

Changed worker recycling in `src/isyntax_deid/zarr_writer.py`.

Before:

```python
maxtasksperchild=8
```

After:

```python
maxtasksperchild=256
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
| baseline | 91.57 | 91.00 | 1:32.11 | 1213.17 |
| maxtasksperchild 256 | 80.79 | 80.25 | 1:21.28 | 8849.09 |

## Speedup

```text
total speedup:      1.13x
zarr_write speedup: 1.13x
```

## Memory interpretation

Peak RSS increased from about 1.2 GB to about 8.9 GB.

For a speed focused 4 worker hackathon proof of concept, this is acceptable on a workstation or node with sufficient RAM.

## Interpretation

Reducing worker recycling gives a meaningful runtime win.

Likely mechanism:

- fewer worker process restarts
- fewer repeated `ISyntaxWSI` initialisations
- fewer repeated Zarr group and pixel array reopen operations
- less multiprocessing process churn

## Decision

Keep this optimisation and stack the next experiment on top.

Do not spend time tuning this down unless memory becomes limiting on the target machine.
