#!/usr/bin/env bash
set -euo pipefail

# CDO preprocessing with dynamic grid generation.
#
# Usage:
#   bash code/02_preprocess_cdo.sh [resolution] [input_folder] [output_folder]
#
# Defaults are read from preprocess_utils/config_resolution.yaml.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$SCRIPT_DIR/preprocess_utils"
CONFIG_FILE="$CONFIG_DIR/config_resolution.yaml"

RESOLUTION="${1:-}"
CONFIG_VALUES="$(
python3 - "$CONFIG_FILE" <<'PY'
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
with config_path.open() as config_stream:
    config = yaml.safe_load(config_stream) or {}

try:
    domain = config["domain"]
    processing = config["processing"]
    paths = config["paths"]
    values = {
        "WEST": domain["lon_min"],
        "SOUTH": domain["lat_min"],
        "EAST": domain["lon_max"],
        "NORTH": domain["lat_max"],
        "RES": processing["resolution"],
        "PARALLEL": processing["parallel"],
        "REMAP_METHOD": processing["remap_method"],
        "BUFFER": processing["buffer"],
        "CONFIG_IN": paths["input"],
        "CONFIG_OUT": paths["output"],
        "GRID": paths["grid"],
    }
except (KeyError, TypeError) as error:
    raise SystemExit(f"Invalid configuration in {config_path}: missing {error}") from error

for key, value in values.items():
    print(f"{key}={value}")
PY
)" || {
    echo "Error loading configuration from $CONFIG_FILE" >&2
    exit 1
}

while IFS='=' read -r key value; do
    case "$key" in
        WEST|SOUTH|EAST|NORTH|RES|PARALLEL|REMAP_METHOD|BUFFER|CONFIG_IN|CONFIG_OUT|GRID)
            printf -v "$key" '%s' "$value"
            ;;
    esac
done <<< "$CONFIG_VALUES"

IN="${2:-$ROOT_DIR/$CONFIG_IN}"
OUT="${3:-$ROOT_DIR/$CONFIG_OUT}"
GRID="$CONFIG_DIR/$GRID"

: "${WEST:?west missing}" "${SOUTH:?south missing}" "${EAST:?east missing}" "${NORTH:?north missing}"
command -v cdo >/dev/null 2>&1 || {
    echo "Error: CDO was not found on PATH." >&2
    echo "Install CDO with Conda (conda install -c conda-forge cdo) or run this script in WSL with CDO installed." >&2
    exit 1
}

if [ -z "$RESOLUTION" ]; then
    RESOLUTION="$RES"
fi

python3 "$CONFIG_DIR/generate_grid.py" \
    --resolution "$RESOLUTION" \
    --config "$CONFIG_FILE" \
    --output "$GRID" ||
    { echo "Error generating grid" >&2; exit 1; }
[[ -f "$GRID" ]] || { echo "Error: grid.txt not generated" >&2; exit 1; }

CLIP_WEST=$(awk -v w="$WEST" -v b="$BUFFER" 'BEGIN {print w - b}')
CLIP_EAST=$(awk -v e="$EAST" -v b="$BUFFER" 'BEGIN {print e + b}')
CLIP_SOUTH=$(awk -v s="$SOUTH" -v b="$BUFFER" 'BEGIN {print s - b}')
CLIP_NORTH=$(awk -v n="$NORTH" -v b="$BUFFER" 'BEGIN {print n + b}')

LOG="${OUT}/cdo.log"
mkdir -p "$OUT"
echo "CDO pipeline at $(date) - Resolution: $RESOLUTION" >> "$LOG"
start_time=$(date +%s)

process_cdo() {
    local file="$1" base yyyy mm dd file_date outdir outfile part_file tmp1 start duration remap_op
    base="$(basename "$file")"
    [[ $base =~ ([0-9]{4})([0-9]{2})([0-9]{2}) ]] \
        || {
            printf '[%s] file=%s status=skipped reason=no-date\n' \
                "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$base" >> "$LOG"
            return 0
        }
    yyyy="${BASH_REMATCH[1]}"
    mm="${BASH_REMATCH[2]}"
    dd="${BASH_REMATCH[3]}"
    file_date="${yyyy}-${mm}-${dd}"
    outdir="${OUT}/$yyyy/$mm"
    mkdir -p "$outdir"
    outfile="${outdir}/${base%.nc}_processed.nc"
    part_file="${outfile}.part"
    [[ -f "$outfile" ]] && { rm -f "$part_file"; return 0; }

    tmp1=$(mktemp)
    trap 'rm -f "$tmp1" "$part_file"' RETURN
    start=$(date +%s)

    case "$REMAP_METHOD" in
        bilinear) remap_op="remapbil" ;;
        nearest) remap_op="remapnn" ;;
        *) remap_op="remapbil" ;;
    esac

    # Keep a buffer for interpolation, then remap directly to the target grid.
    if ! cdo -L -f nc4 -O \
        -sellonlatbox,"$CLIP_WEST","$CLIP_EAST","$CLIP_SOUTH","$CLIP_NORTH" \
        "$file" "$tmp1" 2>>"$LOG"; then
        duration=$(( $(date +%s) - start ))
        printf '[%s] file=%s date=%s status=failed stage=clipping duration=%ss\n' \
            "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$base" "$file_date" "$duration" >> "$LOG"
        return 1
    fi

    if cdo -L -f nc4 -O \
        "-${remap_op},$GRID" "$tmp1" "$part_file" 2>>"$LOG"; then
        if mv "$part_file" "$outfile"; then
            duration=$(( $(date +%s) - start ))
            printf '[%s] file=%s date=%s status=processed duration=%ss\n' \
                "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$base" "$file_date" "$duration" >> "$LOG"
        else
            duration=$(( $(date +%s) - start ))
            printf '[%s] file=%s date=%s status=failed stage=finalize duration=%ss\n' \
                "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$base" "$file_date" "$duration" >> "$LOG"
            return 1
        fi
    else
        duration=$(( $(date +%s) - start ))
        printf '[%s] file=%s date=%s status=failed stage=remapping duration=%ss\n' \
            "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$base" "$file_date" "$duration" >> "$LOG"
        return 1
    fi
}

export -f process_cdo
export OUT LOG CLIP_WEST CLIP_EAST CLIP_SOUTH CLIP_NORTH
export WEST SOUTH EAST NORTH GRID REMAP_METHOD

if find "$IN" -type f -name "*.nc" -print0 |
    xargs -0 -P "$PARALLEL" -I {} bash -c 'process_cdo "$@"' _ {}; then
    batch_status=0
else
    batch_status=$?
fi

echo "" >> "$LOG"
echo "Finished at $(date) - Time: $(($(date +%s)-start_time))s - Status: $batch_status" >> "$LOG"
exit "$batch_status"
