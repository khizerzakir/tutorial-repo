#!/usr/bin/env bash
set -euo pipefail

# CDO preprocessing with dynamic grid generation.
# QA variables (quality_flag by default) use nearest-neighbour remapping;
# all remaining variables use REMAP_METHOD from the YAML configuration.
#
# Usage:
#   bash code/02_preprocess_cdo.sh [resolution] [input_folder] [output_folder]
#   MAIN_VARIABLE=METREF QA_VARIABLES=quality_flag bash code/02_preprocess_cdo.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$SCRIPT_DIR/preprocess_utils"
CONFIG_FILE="${CONFIG_FILE:-$CONFIG_DIR/config_resolution.yaml}"
GRID_HELPER="$CONFIG_DIR/snap_aoi_to_netcdf_grid.py"
RESOLUTION="${1:-}"

CONFIG_VALUES="$(python3 - "$CONFIG_FILE" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1])
with path.open(encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}
try:
    domain = config["domain"]
    processing = config["processing"]
    paths = config["paths"]
    values = {
        "WEST": domain["lon_min"], "SOUTH": domain["lat_min"],
        "EAST": domain["lon_max"], "NORTH": domain["lat_max"],
        "RES": processing["resolution"],
        "PARALLEL": processing.get("parallel", 4),
        "REMAP_METHOD": processing.get("remap_method", "bilinear"),
        "BUFFER": processing.get("buffer", 0.2),
        "CONFIG_IN": paths.get("input", "data/raw"),
        "CONFIG_OUT": paths.get("output", "data/interim"),
        "GRID_NAME": paths.get("grid", "grid.txt"),
    }
except (KeyError, TypeError) as error:
    raise SystemExit(f"Invalid configuration in {path}: missing {error}") from error
for key, value in values.items():
    print(f"{key}={value}")
PY
)" || { echo "Could not read YAML configuration: $CONFIG_FILE" >&2; exit 1; }

while IFS='=' read -r key value; do
    case "$key" in
        WEST|SOUTH|EAST|NORTH|RES|PARALLEL|REMAP_METHOD|BUFFER|CONFIG_IN|CONFIG_OUT|GRID_NAME)
            printf -v "$key" '%s' "$value" ;;
    esac
done <<< "$CONFIG_VALUES"

IN="${2:-$ROOT_DIR/$CONFIG_IN}"
OUT="${3:-$ROOT_DIR/$CONFIG_OUT}"
AOI_FILE="${4:-${AOI_FILE:-}}"
AOI_CRS="${AOI_CRS:-}"
GRID="$CONFIG_DIR/$GRID_NAME"
MAIN_VARIABLE="${MAIN_VARIABLE:-}"
QA_VARIABLES="${QA_VARIABLES:-quality_flag}"
QA_CSV="$(printf '%s' "$QA_VARIABLES" | tr ' ' ',' | sed 's/,,*/,/g; s/^,//; s/,$//')"

: "${WEST:?west missing}" "${SOUTH:?south missing}" "${EAST:?east missing}" "${NORTH:?north missing}"
[[ -n "$MAIN_VARIABLE" ]] || { echo "Set MAIN_VARIABLE (e.g. MAIN_VARIABLE=METREF)." >&2; exit 1; }
[[ -n "$RESOLUTION" ]] && RES="$RESOLUTION"
command -v cdo >/dev/null 2>&1 || {
    echo "CDO was not found on PATH. Install with conda install -c conda-forge cdo." >&2
    exit 1
}
[[ -d "$IN" ]] || { echo "Input folder not found: $IN" >&2; exit 1; }
[[ "$PARALLEL" =~ ^[1-9][0-9]*$ ]] || { echo "PARALLEL must be a positive integer." >&2; exit 1; }
[[ -f "$GRID_HELPER" ]] || { echo "Grid helper not found: $GRID_HELPER" >&2; exit 1; }

case "$REMAP_METHOD" in
    bilinear) remap_op="remapbil" ;;
    nearest) remap_op="remapnn" ;;
    *) echo "REMAP_METHOD must be bilinear or nearest." >&2; exit 1 ;;
esac

FIRST_RAW="$(find "$IN" -type f -name '*.nc' -print -quit)"
[[ -n "$FIRST_RAW" ]] || { echo "No NetCDF files found under $IN" >&2; exit 1; }
RAW_NAMES="$(cdo -s showname "$FIRST_RAW" | tr '\n' ' ' | xargs)"
[[ " $RAW_NAMES " == *" $MAIN_VARIABLE "* ]] || {
    echo "Main variable '$MAIN_VARIABLE' not found. Available: $RAW_NAMES" >&2; exit 1;
}
IFS=',' read -r -a QA_LIST <<< "$QA_CSV"
for qa in "${QA_LIST[@]}"; do
    [[ " $RAW_NAMES " == *" $qa "* ]] || {
        echo "QA variable '$qa' not found. Available: $RAW_NAMES" >&2; exit 1;
    }
done

if [[ -z "$RESOLUTION" ]]; then RESOLUTION="$RES"; fi
GRID_ARGS=(--netcdf "$FIRST_RAW" --config "$CONFIG_FILE" --output-yaml "$CONFIG_FILE" --grid "$GRID")
if [[ -n "$AOI_FILE" ]]; then
    [[ -f "$AOI_FILE" ]] || { echo "AOI file not found: $AOI_FILE" >&2; exit 1; }
    GRID_ARGS+=(--aoi "$AOI_FILE" --output-gpkg "${AOI_OUTPUT:-$OUT/aoi_aligned.gpkg}")
    [[ -n "$AOI_CRS" ]] && GRID_ARGS+=(--aoi-crs "$AOI_CRS")
fi
python3 "$GRID_HELPER" "${GRID_ARGS[@]}" || { echo "Error creating grid/YAML from raw grid and selected bounds" >&2; exit 1; }
[[ -s "$GRID" ]] || { echo "Grid file was not generated: $GRID" >&2; exit 1; }

grid_value() { awk -F= -v k="$1" '$1 ~ "^[[:space:]]*" k "[[:space:]]*$" {gsub(/[[:space:]]/, "", $2); print $2}' "$GRID"; }
XF="$(grid_value xfirst)"; XI="$(grid_value xinc)"; NX="$(grid_value xsize)"
YF="$(grid_value yfirst)"; YI="$(grid_value yinc)"; NY="$(grid_value ysize)"
read -r GRID_WEST GRID_EAST GRID_SOUTH GRID_NORTH < <(awk \
    -v x="$XF" -v dx="$XI" -v nx="$NX" -v y="$YF" -v dy="$YI" -v ny="$NY" \
    'BEGIN {xe=x+(nx-1)*dx; ye=y+(ny-1)*dy; print (x<xe?x:xe)-dx/2, (x>xe?x:xe)+dx/2, (y<ye?y:ye)-dy/2, (y>ye?y:ye)+dy/2}')
CLIP_WEST="$(awk -v x="$GRID_WEST" -v b="$BUFFER" 'BEGIN {print x-b}')"
CLIP_EAST="$(awk -v x="$GRID_EAST" -v b="$BUFFER" 'BEGIN {print x+b}')"
CLIP_SOUTH="$(awk -v x="$GRID_SOUTH" -v b="$BUFFER" 'BEGIN {print x-b}')"
CLIP_NORTH="$(awk -v x="$GRID_NORTH" -v b="$BUFFER" 'BEGIN {print x+b}')"

LOG="$OUT/cdo.log"
mkdir -p "$OUT"
printf 'CDO preprocessing started %s; resolution=%s; main=%s (%s); QA=%s (nearest)\n' \
    "$(date -Is)" "$RESOLUTION" "$MAIN_VARIABLE" "$REMAP_METHOD" "$QA_CSV" >> "$LOG"
START_TIME="$(date +%s)"

process_cdo() {
    local file="$1" base yyyy mm dd file_date outdir outfile part_file
    local tmp_clip tmp_main tmp_qa tmp_main_remap tmp_qa_remap tmp_merge start duration
    base="$(basename "$file")"
    if [[ ! "$base" =~ ([0-9]{4})([0-9]{2})([0-9]{2}) ]]; then
        printf '[%s] file=%s status=skipped reason=no-date\n' "$(date -Is)" "$base" >> "$LOG"
        return 0
    fi
    yyyy="${BASH_REMATCH[1]}"; mm="${BASH_REMATCH[2]}"; dd="${BASH_REMATCH[3]}"
    file_date="$yyyy-$mm-$dd"
    outdir="$OUT/$yyyy/$mm"; mkdir -p "$outdir"
    outfile="$outdir/${base%.nc}_processed.nc"
    part_file="${outfile}.part"
    if [[ -s "$outfile" ]] && cdo -s sinfo "$outfile" >/dev/null 2>&1; then return 0; fi

    tmp_clip="$(mktemp "$outdir/.clip.XXXXXX.nc")"
    tmp_main="$(mktemp "$outdir/.main.XXXXXX.nc")"
    tmp_qa="$(mktemp "$outdir/.qa.XXXXXX.nc")"
    tmp_main_remap="$(mktemp "$outdir/.main_remap.XXXXXX.nc")"
    tmp_qa_remap="$(mktemp "$outdir/.qa_remap.XXXXXX.nc")"
    tmp_merge="$(mktemp "$outdir/.merged.XXXXXX.nc")"
    trap 'rm -f "${tmp_clip:-}" "${tmp_main:-}" "${tmp_qa:-}" "${tmp_main_remap:-}" "${tmp_qa_remap:-}" "${tmp_merge:-}" "$part_file"' RETURN
    start="$(date +%s)"

    if ! cdo -L -f nc4 -O \
        -sellonlatbox,"$CLIP_WEST","$CLIP_EAST","$CLIP_SOUTH","$CLIP_NORTH" \
        "$file" "$tmp_clip" 2>>"$LOG"; then
        printf '[%s] file=%s date=%s status=failed stage=clip\n' "$(date -Is)" "$base" "$file_date" >> "$LOG"
        return 1
    fi
    # Remap main/continuous variables with the configured method.
    if ! cdo -L -f nc4 -O -delname,"$QA_CSV" "$tmp_clip" "$tmp_main" 2>>"$LOG"; then
        printf '%s: failed to exclude QA variables before main remap\n' "$base" >> "$LOG"; return 1
    fi
    if ! cdo -L -f nc4 -O -selname,"$QA_CSV" "$tmp_clip" "$tmp_qa" 2>>"$LOG"; then
        printf '%s: failed to select QA variables\n' "$base" >> "$LOG"; return 1
    fi
    if ! cdo -L -f nc4 -O "-${remap_op},$GRID" "$tmp_main" "$tmp_main_remap" 2>>"$LOG"; then
        printf '%s: main remapping failed\n' "$base" >> "$LOG"; return 1
    fi
    # QA codes are categorical: nearest-neighbour avoids blending flag values.
    if ! cdo -L -f nc4 -O "-remapnn,$GRID" "$tmp_qa" "$tmp_qa_remap" 2>>"$LOG"; then
        printf '%s: QA nearest remapping failed\n' "$base" >> "$LOG"; return 1
    fi
    if ! cdo -L -f nc4 -O merge "$tmp_main_remap" "$tmp_qa_remap" "$tmp_merge" 2>>"$LOG"; then
        printf '%s: merging main and QA outputs failed\n' "$base" >> "$LOG"; return 1
    fi
    if [[ ! -s "$tmp_merge" ]] || ! cdo -s sinfo "$tmp_merge" >/dev/null 2>&1; then
        printf '%s: merged output is empty or unreadable\n' "$base" >> "$LOG"; return 1
    fi
    mv -f "$tmp_merge" "$part_file" && mv -f "$part_file" "$outfile"
    duration=$(( $(date +%s) - start ))
    printf '[%s] file=%s date=%s status=processed duration=%ss QA=nearest\n' \
        "$(date -Is)" "$base" "$file_date" "$duration" >> "$LOG"
}

export -f process_cdo
export OUT LOG GRID MAIN_VARIABLE QA_CSV remap_op
export CLIP_WEST CLIP_EAST CLIP_SOUTH CLIP_NORTH
find "$IN" -type f -name '*.nc' -print0 |
    xargs -0 -r -P "$PARALLEL" -I '{}' bash -c 'process_cdo "$1"' _ '{}'

echo "Finished $(date -Is); elapsed=$(( $(date +%s) - START_TIME ))s" >> "$LOG"
echo "Done. Main variables: $REMAP_METHOD; QA variables ($QA_CSV): nearest-neighbour. Log: $LOG"
