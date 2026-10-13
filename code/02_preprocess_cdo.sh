#!/usr/bin/env bash
set -euo pipefail

# CDO preprocessing with dynamic grid generation.
#
# Usage:
#   bash code/02_preprocess_cdo.sh [resolution] [input_folder] [output_folder]
#
# Defaults:
#   resolution: RES from preprocess_utils/config.txt, or 0.05
#   input:      data/raw/
#   output:     data/interim/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$SCRIPT_DIR/preprocess_utils"

RESOLUTION="${1:-}"
source "$CONFIG_DIR/config.txt"
: "${WEST:?west missing}" "${SOUTH:?south missing}" "${EAST:?east missing}" "${NORTH:?north missing}"
command -v cdo >/dev/null 2>&1 || {
    echo "Error: CDO was not found on PATH." >&2
    echo "Install CDO with Conda (conda install -c conda-forge cdo) or run this script in WSL with CDO installed." >&2
    exit 1
}

if [ -z "$RESOLUTION" ]; then
    RESOLUTION="${RES:-0.05}"
fi
IN="${2:-$ROOT_DIR/data/raw}"
OUT="${3:-$ROOT_DIR/data/interim}"

python3 "$CONFIG_DIR/generate_grid.py" \
    --resolution "$RESOLUTION" \
    --config "$CONFIG_DIR/config_resolution.yaml" \
    --output "$CONFIG_DIR/grid.txt" ||
    { echo "Error generating grid" >&2; exit 1; }
GRID="$CONFIG_DIR/grid.txt"
[[ -f "$GRID" ]] || { echo "Error: grid.txt not generated" >&2; exit 1; }

BUFFER="${BUFFER:-0.2}"
REMAP_METHOD="${REMAP_METHOD:-bilinear}"
PARALLEL="${PARALLEL:-4}"
CLIP_WEST=$(awk -v w="$WEST" -v b="$BUFFER" 'BEGIN {print w - b}')
CLIP_EAST=$(awk -v e="$EAST" -v b="$BUFFER" 'BEGIN {print e + b}')
CLIP_SOUTH=$(awk -v s="$SOUTH" -v b="$BUFFER" 'BEGIN {print s - b}')
CLIP_NORTH=$(awk -v n="$NORTH" -v b="$BUFFER" 'BEGIN {print n + b}')

LOG="${OUT}/cdo.log"
mkdir -p "$OUT"
echo "CDO pipeline at $(date) - Resolution: $RESOLUTION" >> "$LOG"
start_time=$(date +%s)

process_cdo() {
    local file="$1" base yyyy mm outdir outfile tmp1 start remap_op
    base="$(basename "$file")"
    [[ $base =~ ([0-9]{4})([0-9]{2})([0-9]{2}) ]] \
        || { echo "No date in $base" >> "$LOG"; return 0; }
    yyyy="${BASH_REMATCH[1]}"
    mm="${BASH_REMATCH[2]}"
    outdir="${OUT}/$yyyy/$mm"
    mkdir -p "$outdir"
    outfile="${outdir}/${base%.nc}_processed.nc"
    [[ -f "$outfile" ]] && return 0

    tmp1=$(mktemp)
    trap 'rm -f "$tmp1"' RETURN
    start=$(date +%s)

    case "$REMAP_METHOD" in
        bilinear) remap_op="remapbil" ;;
        nearest) remap_op="remapnn" ;;
        *) remap_op="remapbil" ;;
    esac

    # Keep a buffer for interpolation, then remap directly to the target grid.
    cdo -L -f nc4 -O \
        -sellonlatbox,"$CLIP_WEST","$CLIP_EAST","$CLIP_SOUTH","$CLIP_NORTH" \
        "$file" "$tmp1" 2>>"$LOG" &&
    cdo -L -f nc4 -O "-${remap_op},$GRID" "$tmp1" "$outfile" 2>>"$LOG" &&
    echo "$base ($(( $(date +%s) - start ))s)" >> "$LOG" ||
    echo "$base failed" >> "$LOG"
}

export -f process_cdo
export OUT LOG CLIP_WEST CLIP_EAST CLIP_SOUTH CLIP_NORTH
export WEST SOUTH EAST NORTH GRID REMAP_METHOD

find "$IN" -type f -name "*.nc" -print0 |
    xargs -0 -P "$PARALLEL" -I {} bash -c 'process_cdo "$@"' _ {}

echo "" >> "$LOG"
echo "Finished at $(date) - Time: $(($(date +%s)-start_time))s" >> "$LOG"
