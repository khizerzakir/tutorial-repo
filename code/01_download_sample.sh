#!/usr/bin/env bash
set -euo pipefail

# Download one month of LSA SAF NetCDF files -> data/raw/<variable>/YYYY/MM/*.nc
#
# Usage:  bash scripts/01_download_sample.sh [YYYY] [MM] [VARIABLE] [URL]
# Env:    JOBS=4, RAW_DIR=..., ENV_FILE=... (default: ./code/.env)
#         SAMPLE_YEAR=..., SAMPLE_MONTH=..., VARIABLE_NAME=..., URL=...
# Needs:  wget, and LSASAF_USERNAME / LSASAF_PASSWORD in the .env file

# Credentials (kept out of the process list via a private temporary wgetrc)
ENV_FILE="${ENV_FILE:-$PWD/code/.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
: "${LSASAF_USERNAME:?missing (add to $ENV_FILE)}" "${LSASAF_PASSWORD:?missing (add to $ENV_FILE)}"

YEAR="${1:-${SAMPLE_YEAR:-2020}}"; M="${2:-${SAMPLE_MONTH:-06}}"
VARIABLE="${3:-${VARIABLE_NAME:-METREF}}"; URL="${4:-${URL:-}}"; JOBS="${JOBS:-4}"
[[ $YEAR =~ ^[0-9]{4}$ && $M =~ ^[0-9]{1,2}$ ]] && (( 10#$M >= 1 && 10#$M <= 12 )) \
  || { echo "Usage: $0 [YYYY] [MM] [VARIABLE] [URL]" >&2; exit 1; }
[[ $VARIABLE =~ ^[A-Za-z0-9_.-]+$ ]] \
  || { echo "Variable name must contain only letters, numbers, '.', '_' or '-'" >&2; exit 1; }
: "${URL:?missing URL (pass it as the fourth argument or add URL to $ENV_FILE)}"
MONTH=$(printf '%02d' $((10#$M)))
command -v wget >/dev/null || { echo "wget not found" >&2; exit 1; }

WGETRC="$(mktemp)"; export WGETRC; trap 'rm -f "$WGETRC"' EXIT
printf 'http_user=%s\nhttp_password=%s\n' "$LSASAF_USERNAME" "$LSASAF_PASSWORD" > "$WGETRC"

SRC="${URL%/}"; HOST="${SRC%%/PRODUCTS*}"
DEST="${RAW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/raw}/$VARIABLE/$YEAR/$MONTH"
mkdir -p "$DEST"

# 1) Collect file URLs for the month (days that don't exist return no listing)
list=""
for d in $(seq -w 1 31); do
  list+=$({ wget -q -O- --tries=3 --timeout=60 "$SRC/$YEAR/$MONTH/$d/" || true; } \
          | tr '"' '\n' | grep -E '\.nc$' | sed "s|^|$HOST|" || true)$'\n'
done
pending=$(while read -r u; do [ -z "$u" ] || [ -f "$DEST/${u##*/}" ] || echo "$u"; done <<< "$list")
found=$(printf '%s' "$list" | grep -c . || true); n=$(printf '%s' "$pending" | grep -c . || true)
echo "$YEAR-$MONTH: $found file(s) on server, $n to download -> $DEST"
(( n )) || { echo "Already up to date."; exit 0; }

# 2) Download (to .part, then rename, so interrupted files are never mistaken for complete ones)
get() { local f="$2/${1##*/}"
        wget -q --tries=3 --timeout=60 -O "$f.part" "$1" && mv "$f.part" "$f" \
          || { echo "FAILED: $1" >&2; return 1; }; }
export -f get
fmt() { printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); }

t0=$SECONDS; get "$(head -n1 <<< "$pending")" "$DEST"          # time one file for an estimate
dt=$((SECONDS - t0)); dt=$((dt < 1 ? 1 : dt))
echo "First file: ~${dt}s. Estimated remaining: ~$(fmt $((dt * (n - 1) / JOBS))) with $JOBS parallel jobs"
(( n > 1 )) && { tail -n +2 <<< "$pending" \
  | xargs -P "$JOBS" -I{} bash -c 'get "$1" "$2"' _ {} "$DEST" \
  || { echo "Some downloads failed. Re-run to retry." >&2; exit 1; }; }
echo "Done: $n file(s) in $(fmt $SECONDS)"