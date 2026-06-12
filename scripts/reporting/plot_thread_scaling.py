#!/usr/bin/env python3

from pathlib import Path
import argparse
import csv


DATA = [
    {"threads": 1, "median_total_s": 314.39, "median_zarr_write_s": 313.97, "tissue_tiles_s": 72},
    {"threads": 2, "median_total_s": 163.89, "median_zarr_write_s": 163.45, "tissue_tiles_s": 138},
    {"threads": 4, "median_total_s": 90.82, "median_zarr_write_s": 90.38, "tissue_tiles_s": 249},
    {"threads": 8, "median_total_s": 58.64, "median_zarr_write_s": 58.19, "tissue_tiles_s": 386},
]


def add_metrics(rows):
    base_total = rows[0]["median_total_s"]
    base_tiles = rows[0]["tissue_tiles_s"]
    out = []
    for r in rows:
        rr = dict(r)
        rr["speedup_total"] = base_total / rr["median_total_s"]
        rr["parallel_efficiency_pct"] = 100.0 * rr["speedup_total"] / rr["threads"]
        rr["tiles_s_speedup"] = rr["tissue_tiles_s"] / base_tiles
        out.append(rr)
    return out


def scale(value, src_min, src_max, dst_min, dst_max):
    if src_max == src_min:
        return (dst_min + dst_max) / 2
    return dst_min + (value - src_min) * (dst_max - dst_min) / (src_max - src_min)


def write_svg(path, rows, y_key, y_label, title, ideal=False):
    width, height = 900, 560
    left, right, top, bottom = 95, 40, 60, 90
    plot_w = width - left - right
    plot_h = height - top - bottom

    xs = [r["threads"] for r in rows]
    ys = [r[y_key] for r in rows]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = 0, max(ys) * 1.12

    def px(x):
        return scale(x, x_min, x_max, left, left + plot_w)

    def py(y):
        return scale(y, y_min, y_max, top + plot_h, top)

    points = " ".join(f"{px(r['threads']):.1f},{py(r[y_key]):.1f}" for r in rows)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="32" text-anchor="middle" font-family="Arial" font-size="22">{title}</text>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="black"/>',
        f'<text x="{width/2}" y="{height-25}" text-anchor="middle" font-family="Arial" font-size="16">Threads per slide</text>',
        f'<text x="24" y="{height/2}" text-anchor="middle" font-family="Arial" font-size="16" transform="rotate(-90 24 {height/2})">{y_label}</text>',
    ]

    for r in rows:
        x = px(r["threads"])
        parts.append(f'<line x1="{x:.1f}" y1="{top+plot_h}" x2="{x:.1f}" y2="{top+plot_h+6}" stroke="black"/>')
        parts.append(f'<text x="{x:.1f}" y="{top+plot_h+26}" text-anchor="middle" font-family="Arial" font-size="14">{r["threads"]}</text>')

    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        y_val = y_min + frac * (y_max - y_min)
        y = py(y_val)
        parts.append(f'<line x1="{left-6}" y1="{y:.1f}" x2="{left}" y2="{y:.1f}" stroke="black"/>')
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#ddd"/>')
        parts.append(f'<text x="{left-12}" y="{y+5:.1f}" text-anchor="end" font-family="Arial" font-size="13">{y_val:.1f}</text>')

    if ideal:
        ideal_points = " ".join(f"{px(r['threads']):.1f},{py(r['threads']):.1f}" for r in rows)
        parts.append(f'<polyline points="{ideal_points}" fill="none" stroke="#777" stroke-width="2" stroke-dasharray="6,6"/>')
        parts.append(f'<text x="{left+plot_w-10}" y="{py(rows[-1]["threads"])-10:.1f}" text-anchor="end" font-family="Arial" font-size="13">Ideal</text>')

    parts.append(f'<polyline points="{points}" fill="none" stroke="black" stroke-width="3"/>')

    for r in rows:
        x, y = px(r["threads"]), py(r[y_key])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="black"/>')
        parts.append(f'<text x="{x:.1f}" y="{y-10:.1f}" text-anchor="middle" font-family="Arial" font-size="13">{r[y_key]:.2f}</text>')

    parts.append("</svg>")
    path.write_text("\n".join(parts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--outdir",
        default=str(Path.home() / "run_report" / "benchmarks" / "baseline_threads"),
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = add_metrics(DATA)

    csv_path = outdir / "thread_scaling_summary.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    write_svg(outdir / "thread_scaling_runtime.svg", rows, "median_total_s", "Median runtime, seconds", "ISyntaxDEID runtime scaling")
    write_svg(outdir / "thread_scaling_tiles_per_second.svg", rows, "tissue_tiles_s", "Tissue tiles per second", "ISyntaxDEID tissue tile throughput")
    write_svg(outdir / "thread_scaling_speedup.svg", rows, "speedup_total", "Speedup versus 1 thread", "ISyntaxDEID speedup versus ideal scaling", ideal=True)
    write_svg(outdir / "thread_scaling_efficiency.svg", rows, "parallel_efficiency_pct", "Parallel efficiency, percent", "ISyntaxDEID parallel efficiency")

    print(f"Wrote {csv_path}")
    for p in sorted(outdir.glob("thread_scaling_*.svg")):
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
