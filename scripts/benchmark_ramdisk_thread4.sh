#!/usr/bin/env bash
set -euo pipefail

SLIDE="${1:-$HOME/run_report/data/testslide.isyntax}"
OUTDIR="${2:-$HOME/run_report/benchmarks/ramdisk_vs_base_threads4}"
THREADS="${THREADS:-4}"
ID="testslide_t4"

LOGDIR="$OUTDIR/logs"
BASE_OUT="$OUTDIR/output_base"
RAM_OUT="$OUTDIR/output_ramdisk"

rm -rf "$OUTDIR"
rm -rf /dev/shm/isyntax_ramdisk_*
mkdir -p "$LOGDIR" "$BASE_OUT" "$RAM_OUT"

run_logged() {
    local label="$1"
    shift
    local log="$LOGDIR/${label}.log"

    echo "Running $label"
    /usr/bin/time -v "$@" > "$log" 2>&1
}

extract_stage() {
    local log="$1"
    local stage="$2"
    grep -E "^[[:space:]]+${stage}[[:space:]]+" "$log" | tail -n 1 | awk '{print $2}'
}

extract_time_value() {
    local log="$1"
    local key="$2"
    grep -F "$key" "$log" | tail -n 1 | awk -F': ' '{print $2}'
}

zip_mb() {
    local zip="$1"
    awk -v bytes="$(stat -c%s "$zip")" 'BEGIN {printf "%.2f", bytes / 1024 / 1024}'
}

run_logged baseline \
    env PYTHONPATH=src python scripts/convert_slide.py \
    "$SLIDE" \
    --out "$BASE_OUT" \
    --id "$ID" \
    --threads "$THREADS" \
    --no-visuals

run_logged ramdisk \
    env PYTHONPATH=src python scripts/convert_slide_ramdisk.py \
    "$SLIDE" \
    --out "$RAM_OUT" \
    --id "$ID" \
    --threads "$THREADS" \
    --no-visuals \
    --force

BASE_LOG="$LOGDIR/baseline.log"
RAM_LOG="$LOGDIR/ramdisk.log"
BASE_ZIP="$BASE_OUT/$ID/$ID.zarr.zip"
RAM_ZIP="$RAM_OUT/$ID/$ID.zarr.zip"

SUMMARY_CSV="$OUTDIR/ramdisk_vs_base_threads4_summary.csv"
SUMMARY_MD="$OUTDIR/ramdisk_vs_base_threads4_summary.md"

{
    echo "mode,total_s,zarr_write_s,wall_clock,max_rss_kb,zip_mb,log"
    echo "baseline,$(extract_stage "$BASE_LOG" total),$(extract_stage "$BASE_LOG" zarr_write),$(extract_time_value "$BASE_LOG" "Elapsed (wall clock) time"),$(extract_time_value "$BASE_LOG" "Maximum resident set size"),$(zip_mb "$BASE_ZIP"),$BASE_LOG"
    echo "ramdisk,$(extract_stage "$RAM_LOG" total),$(extract_stage "$RAM_LOG" zarr_write),$(extract_time_value "$RAM_LOG" "Elapsed (wall clock) time"),$(extract_time_value "$RAM_LOG" "Maximum resident set size"),$(zip_mb "$RAM_ZIP"),$RAM_LOG"
} > "$SUMMARY_CSV"

python - "$SUMMARY_CSV" "$SUMMARY_MD" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path

csv_path = Path(sys.argv[1])
md_path = Path(sys.argv[2])

rows = list(csv.DictReader(csv_path.open()))
by_mode = {row["mode"]: row for row in rows}

base = by_mode["baseline"]
ram = by_mode["ramdisk"]

base_total = float(base["total_s"])
ram_total = float(ram["total_s"])
base_rss = int(base["max_rss_kb"])
ram_rss = int(ram["max_rss_kb"])

speedup = base_total / ram_total if ram_total else 0.0
rss_delta_mb = (ram_rss - base_rss) / 1024

md_path.write_text(
    "\n".join(
        [
            "# RAM disk versus baseline thread 4",
            "",
            "| Mode | Total s | Zarr write s | Wall clock | Max RSS MB | ZIP MB |",
            "|---|---:|---:|---:|---:|---:|",
            f"| baseline | {float(base['total_s']):.2f} | {float(base['zarr_write_s']):.2f} | {base['wall_clock']} | {base_rss / 1024:.2f} | {float(base['zip_mb']):.2f} |",
            f"| ramdisk | {float(ram['total_s']):.2f} | {float(ram['zarr_write_s']):.2f} | {ram['wall_clock']} | {ram_rss / 1024:.2f} | {float(ram['zip_mb']):.2f} |",
            "",
            f"Speedup: `{speedup:.3f}x`",
            "",
            f"Peak RSS delta: `{rss_delta_mb:.2f} MB`",
            "",
            f"CSV: `{csv_path}`",
            "",
        ]
    )
)
PY

cat "$SUMMARY_MD"
