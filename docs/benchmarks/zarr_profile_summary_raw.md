# Fine grained Zarr writer profile

Total conversion seconds: 32.444

| Event | Count | Total s | Mean s | Median s | Max s |
|---|---:|---:|---:|---:|---:|
| tile.read_region | 22612 | 111.506 | 0.004931 | 0.002834 | 0.133910 |
| tile.zarr_assignment | 22612 | 87.230 | 0.003858 | 0.003758 | 0.009054 |
| pixels.write_parallel_total | 1 | 28.408 | 28.407995 | 28.407995 | 28.407995 |
| tile.rgba_to_rgb_contiguous | 22612 | 5.077 | 0.000225 | 0.000196 | 0.001013 |
| zip.directory | 1 | 2.818 | 2.818165 | 2.818165 | 2.818165 |
| worker.open_isyntax | 8 | 0.470 | 0.058727 | 0.057105 | 0.066556 |
| cleanup.scratch_rmtree | 1 | 0.333 | 0.333465 | 0.333465 | 0.333465 |
| metadata.populate_group | 1 | 0.193 | 0.193035 | 0.193035 | 0.193035 |
| worker.open_zarr_pixels | 8 | 0.079 | 0.009895 | 0.009646 | 0.012252 |
| output.atomic_replace | 1 | 0.000 | 0.000020 | 0.000020 | 0.000020 |
| store.create_local | 1 | 0.000 | 0.000013 | 0.000013 | 0.000013 |
| output.final_size | 1 | 0.000 | 0.000000 | 0.000000 | 0.000000 |
