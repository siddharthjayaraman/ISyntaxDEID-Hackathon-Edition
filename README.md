# ISyntaxDEID — Hackathon Edition

Convert a single Philips `.isyntax` whole-slide image (WSI) into a
de-identified, tissue-only sparse `.zarr.zip`.

## The hackathon goal

**Make the per-slide conversion faster.** [`scripts/benchmark.py`](scripts/benchmark.py)
measures wall-clock seconds to turn one `.isyntax` into a `.zarr.zip`, broken
down by stage. Optimise the pipeline, re-run the benchmark, and compare.

You may change anything in [`src/isyntax_deid/`](src/isyntax_deid) as long as the
output `.zarr.zip` stays correct (same tissue tiles, same layout — verify with
[`scripts/inspect_slide_zarr.py`](scripts/inspect_slide_zarr.py)).

## Setup

1. **Create the environment:**

   ```bash
   conda env create -f environment.yml
   conda activate isyntax-deid
   ```

2. **Verify the libisyntax wrapper.** Pixel reads and geometry go through
   `tile_pyisyntax`, which wraps the native `libisyntax` library. Both are
   **vendored under [`src/tile_pyisyntax/`](src/tile_pyisyntax)** (including the
   bundled `libisyntax.so`), so putting `src/` on `PYTHONPATH` is all you need:

   You may update tile_pyisyntax if it helps to improve performance.

   ```bash
   PYTHONPATH=src python -c "from tile_pyisyntax import ISyntaxWSI; print('ok')"
   ```

   > **The bundled `libisyntax.so` is an `x86-64` (amd64) Linux binary.** On any
   > other platform — Apple Silicon / arm64 Macs in particular — the `python -c`
   > check above will fail to load it and you must rebuild from source (next
   > step). Check your platform with `uname -sm` (e.g. `Darwin arm64`).

   <details>
   <summary><strong>Rebuilding <code>libisyntax</code> for arm64 / non-amd64</strong></summary>

   `libisyntax` builds with CMake and (for the library itself) needs only a C11
   compiler, CMake ≥ 3.15, and pthreads. On macOS:

   ```bash
   xcode-select --install      # C toolchain, if not already present
   brew install cmake
   ```

   Build the shared library:

   ```bash
   git clone https://github.com/amspath/libisyntax.git
   cd libisyntax
   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON
   cmake --build build --target isyntax
   ```

   `BUILD_SHARED_LIBS=ON` is required — without it the `isyntax` target builds a
   static archive instead of a loadable shared library. The CMake config already
   detects Apple Silicon and compiles with the right `-arch`. The result lands in
   `build/` as `libisyntax.dylib` (macOS) or `libisyntax.so` (Linux).

   The wrapper loads the library from a fixed path with `ctypes.CDLL`, so copy
   your build over the bundled file **keeping the exact name `libisyntax.so`**
   (a macOS Mach-O dylib loads fine under a `.so` name):

   ```bash
   # from the ISyntaxDEID repo root, adjust the source path to your build:
   cp /path/to/libisyntax/build/libisyntax.dylib src/tile_pyisyntax/libisyntax.so
   ```

   Then re-run the verify command above — it should print `ok`.

   NOTE: You will likely need to allow the libisyntax.so file to run in your security settings if executed on MACOS.

   </details>

3. **Get a test slide.** A public `.isyntax` is available here:
   <https://zenodo.org/records/5037046>

## Quickstart

All commands need `src/` on `PYTHONPATH`.

**Convert one slide** → `output/<id>/<id>.zarr.zip` (plus a metadata CSV and QA PNGs):

```bash
PYTHONPATH=src python scripts/convert_slide.py /path/to/slide.isyntax
```

**Benchmark the conversion** (1 warmup + 5 measured runs, per-stage breakdown):

```bash
PYTHONPATH=src python scripts/benchmark.py /path/to/slide.isyntax --runs 2 --threads 4
```

Example output:

```
stage             median      mean       min       max
----------------------------------------------------------
metadata            0.42      0.43      0.40      0.48
thumbnail           1.10      1.12      1.05      1.20
coordinates         0.05      0.05      0.05      0.06
tissue_detection    0.30      0.31      0.29      0.34
zarr_write         18.70     18.90     18.20     19.60
total              20.57     20.81     20.10     21.50

Slide: 90000x70000 px (6,300 MP), 42,000 tissue tiles encoded
Throughput: 306 MP/s, 2,041 tissue-tiles/s (median total 20.57s)
```

`zarr_write` (reading tiles from libisyntax + JPEG XL encoding) is almost always
the bottleneck — that's where most of the optimisation headroom is.

**Inspect a produced archive** (dumps attrs, arrays, reconstructed thumbnail):

```bash
PYTHONPATH=src python scripts/inspect_slide_zarr.py output/<id>/<id>.zarr.zip
```

## How conversion works

[`ISyntaxDeID.process_slide`](src/isyntax_deid/isyntax_deid.py) runs these stages
(each one is timed and reported by the benchmark):

| Stage | Module | What it does |
|-------|--------|--------------|
| `metadata` | [`metadata/extractor.py`](src/isyntax_deid/metadata/extractor.py) | Parse the XML header + libisyntax geometry into a `MapFileEntry`. |
| `thumbnail` | [`thumbnail_extractor.py`](src/isyntax_deid/thumbnail_extractor.py) | Read a low-res thumbnail at a fixed MPP (default 8). |
| `coordinates` | [`coordinates.py`](src/isyntax_deid/coordinates.py) | Generate the grid of `tile_size`×`tile_size` (default 224) candidate tiles in level-0 space. |
| `tissue_detection` | [`tissue_detection.py`](src/isyntax_deid/tissue_detection.py) | Detect tissue from the thumbnail (local std on the L channel), dilate to a permissive envelope, and mark each tile keep/drop. |
| `zarr_write` | [`zarr_writer.py`](src/isyntax_deid/zarr_writer.py) | Read every kept tile from libisyntax and JPEG XL-encode it, writing only tissue chunks. **The hot path.** |

### Output format

A single `{id}.zarr.zip` (zarr v2, `ZIP_STORED`):

- `pixels` — `(H, W, 3)` `uint8`, chunked at `(tile_size, tile_size, 3)`, JPEG XL
  compressed. **Sparse:** only tissue chunks exist; missing chunks read back as
  white (`255`).
- `thumbnail`, `candidate_coords`, `tile_coords`, `tissue_status`,
  `tissue_mask_chunks`, optional `icc_profile`.
- Group attrs: `mpp_x/y`, `slide_width/height`, `tile_size`,
  `n_candidate_tiles`, `n_tissue_tiles`, `pipeline_version`, etc.

> Tile coordinates must be exact multiples of `tile_size` — the sparse scheme
> assumes one chunk == one tile. Tiles past the slide edge are dropped.

**Anything reading a `.zarr.zip` must register the JPEG XL codec first:**

```python
import imagecodecs.numcodecs as _ic; _ic.register_codecs()
```

## Repo layout

```
src/isyntax_deid/      core conversion library (optimise here)
  isyntax_deid.py        per-slide orchestration + per-stage timing
  metadata/              XML header + geometry extraction
  thumbnail_extractor.py
  coordinates.py
  tissue_detection.py
  zarr_writer.py         sparse JPEG XL zarr writer (the bottleneck)
src/tile_pyisyntax/    vendored libisyntax wrapper + bundled libisyntax.so
scripts/
  convert_slide.py       convert one local slide
  benchmark.py           time the conversion (the hackathon metric)
  inspect_slide_zarr.py  inspect / validate a produced .zarr.zip
```

## License

Copyright © 2026 TileBio Ltd.

This software is licensed for **non-commercial research use only**, under the
[PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use requires a
separate licence from TileBio Ltd.

The vendored `tile_pyisyntax` wrapper and bundled `libisyntax` library under
`src/tile_pyisyntax/` are third-party components, not covered by the TileBio Ltd
copyright — `libisyntax` is distributed under its own terms by the
[amspath/libisyntax](https://github.com/amspath/libisyntax) project.
