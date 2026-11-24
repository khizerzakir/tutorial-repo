#!/usr/bin/env bash
set -euo pipefail

# Download and preprocess on the fly: each LSA SAF file is downloaded to a temporary folder, clipped (and remapped)
# by 02_preprocess_cdo.sh, validated, and the full-disk original is deleted right away. Only the clipped files
# are kept, under data/interim/<variable>/YYYY/MM/*_processed.nc, ready for 03_build_zarr_cube.py.
#
# Usage:  MAIN_VARIABLE=METREF uv run bash code/01b_download_and_clip.sh [YYYY] [MM] [VARIABLE] [URL] [AOI_FILE]
# Env:    JOBS=4            files handled in parallel (= max. number of raw files on disk at any time)
#         REMAP=0           keep the clipped data on the native grid (default 1: clip + remap to grid.txt)
#         QA_VARIABLES=...  categorical variables remapped by nearest neighbour (default quality_flag)
#         TMP_DIR=...       where raw files live while they are processed (default data/tmp)
#         OUT_DIR=...       output root (default data/interim/<variable>)
#         ENV_FILE=...      credentials file (default ./code/.env)
# Needs:  wget, cdo, the project Python environment (run through `uv run`), LSASAF_USERNAME/PASSWORD in .env

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PWD/code/.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
: "${LSASAF_USERNAME:?missing (add to $ENV_FILE)}" "${LSASAF_PASSWORD:?missing (add to $ENV_FILE)}"

YEAR="${1:-${SAMPLE_YEAR:-2020}}"; M="${2:-${SAMPLE_MONTH:-06}}"
VARIABLE="${3:-${VARIABLE_NAME:-METREF}}"; URL="${4:-${URL:-}}"; AOI="${5:-${AOI_FILE:-}}"
JOBS="${JOBS:-4}"; export MAIN_VARIABLE="${MAIN_VARIABLE:-$VARIABLE}"
[[ $YEAR =~ ^[0-9]{4}$ && $M =~ ^[0-9]{1,2}$ ]] && (( 10#$M >= 1 && 10#$M <= 12 )) \
  || { echo "Usage: $0 [YYYY] [MM] [VARIABLE] [URL] [AOI_FILE]" >&2; exit 1; }
[[ $VARIABLE =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "Invalid variable name: $VARIABLE" >&2; exit 1; }
: "${URL:?missing URL (pass it as the fourth argument or add URL to $ENV_FILE)}"
MONTH=$(printf '%02d' $((10#$M)))
for tool in wget cdo python3; do command -v "$tool" >/dev/null || { echo "$tool not found" >&2; exit 1; }; done

TMP_ROOT="${TMP_DIR:-$ROOT_DIR/data/tmp}/$VARIABLE/$YEAR$MONTH"
OUT="${OUT_DIR:-$ROOT_DIR/data/interim/$VARIABLE}"
PRE="$SCRIPT_DIR/02_preprocess_cdo.sh"
mkdir -p "$TMP_ROOT" "$OUT"

WGETRC="$(mktemp)"; export WGETRC
trap 'rm -f "$WGETRC"; rmdir "$TMP_ROOT" 2>/dev/null || true' EXIT
printf 'http_user=%s\nhttp_password=%s\n' "$LSASAF_USERNAME" "$LSASAF_PASSWORD" > "$WGETRC"

# 1) Collect the month's file URLs; skip files whose clipped output already exists (re-runs resume)
SRC="${URL%/}"; HOST="${SRC%%/PRODUCTS*}"
list=""
for d in $(seq -w 1 31); do
  list+=$({ wget -q -O- --tries=3 --timeout=60 "$SRC/$YEAR/$MONTH/$d/" || true; } \
          | tr '"' '\n' | grep -E '\.nc$' | sed "s|^|$HOST|" || true)$'\n'
done
done_file() { local b="${1##*/}"; [ -s "$OUT/$YEAR/$MONTH/${b%.nc}_processed.nc" ]; }
pending=$(while read -r u; do [ -z "$u" ] || done_file "$u" || echo "$u"; done <<< "$list")
found=$(printf '%s' "$list" | grep -c . || true); n=$(printf '%s' "$pending" | grep -c . || true)
echo "$YEAR-$MONTH: $found file(s) on server, $n to download + clip -> $OUT"
(( n )) || { echo "Already up to date."; exit 0; }

# 2) One file: download to a private temp folder -> 02_preprocess_cdo.sh -> raw deleted by DELETE_RAW=1
one() {   # $1 url, $2 1 = first file (derives grid.txt from the raw grid), else reuse it
  local u="$1" tmp f
  tmp="$(mktemp -d "$TMP_ROOT/job.XXXXXX")"; f="$tmp/${u##*/}"
  if ! wget -q --tries=3 --timeout=120 -O "$f.part" "$u"; then
    echo "FAILED download: $u" >&2; rm -rf "$tmp"; return 1
  fi
  mv "$f.part" "$f"
  local skip=1; [ "${2:-0}" = 1 ] && skip=0
  if ! SKIP_GRID=$skip DELETE_RAW=1 QUIET=1 PARALLEL=1 bash "$PRE" "" "$f" "$OUT" ${AOI:+"$AOI"}; then
    echo "FAILED processing: ${u##*/} (see $OUT/cdo.log)" >&2; rm -rf "$tmp"; return 1
  fi
  [ -e "$f" ] && { echo "FAILED processing: ${u##*/} (raw kept: $f)" >&2; return 1; }
  rm -rf "$tmp"
}
export -f one
export TMP_ROOT OUT PRE AOI

fmt() { printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); }
t0=$SECONDS
one "$(head -n1 <<< "$pending")" 1          # first file also snaps the study area to the raw grid
dt=$((SECONDS - t0)); dt=$((dt < 1 ? 1 : dt))
echo "First file: ~${dt}s (download + clip). Estimated remaining: ~$(fmt $((dt * (n - 1) / JOBS))) with $JOBS parallel jobs"
(( n > 1 )) && { tail -n +2 <<< "$pending" \
  | xargs -P "$JOBS" -I{} bash -c 'one "$1"' _ {} \
  || { echo "Some files failed. Re-run to retry; finished files are skipped." >&2; exit 1; }; }

kept=$(du -sh "$OUT/$YEAR/$MONTH" 2>/dev/null | cut -f1)
echo "Done: $n file(s) in $(fmt $SECONDS). Kept only the clipped files ($kept in $OUT/$YEAR/$MONTH); no raw files left."
