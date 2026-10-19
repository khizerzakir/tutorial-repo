#!/usr/bin/env bash
set -euo pipefail

# Download one month or a date range of LSA SAF NetCDF files -> data/raw/<variable>/YYYY/MM/*.nc
#
# Usage:
#   bash code/01_download_sample.sh [YYYY] [VARIABLE] [URL]
#   bash code/01_download_sample.sh [YYYY] [MM] [VARIABLE] [URL]
#   bash code/01_download_sample.sh [YYYY] [MM] [DD] [VARIABLE] [URL]
#   bash code/01_download_sample.sh [YYYY] [MM] [DD] [YYYY] [MM] [DD] [VARIABLE] [URL]
# Env:    JOBS=4, RAW_DIR=..., ENV_FILE=... (default: ./code/.env)
#         SAMPLE_YEAR=..., SAMPLE_MONTH=..., VARIABLE_NAME=..., URL=...
# Needs:  wget, and LSASAF_USERNAME / LSASAF_PASSWORD in the .env file

# Credentials (kept out of the process list via a private temporary wgetrc)
ENV_FILE="${ENV_FILE:-$PWD/code/.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
: "${LSASAF_USERNAME:?missing (add to $ENV_FILE)}" "${LSASAF_PASSWORD:?missing (add to $ENV_FILE)}"

usage() {
  cat >&2 <<'EOF'
Usage:
  bash code/01_download_sample.sh [YYYY] [VARIABLE] [URL]
  bash code/01_download_sample.sh [YYYY] [MM] [VARIABLE] [URL]
  bash code/01_download_sample.sh [YYYY] [MM] [DD] [VARIABLE] [URL]
  bash code/01_download_sample.sh [YYYY] [MM] [DD] [YYYY] [MM] [DD] [VARIABLE] [URL]
EOF
  exit 1
}

YEAR="${1:-${SAMPLE_YEAR:-2020}}"
M="${2:-${SAMPLE_MONTH:-06}}"
MODE="year"
START_DAY=""
END_YEAR=""
END_MONTH=""
END_DAY=""
if [[ ${1:-} =~ ^[0-9]{4}$ && ${2:-} =~ ^[0-9]{1,2}$ && ${3:-} =~ ^[0-9]{1,2}$ && ${4:-} =~ ^[0-9]{4}$ && ${5:-} =~ ^[0-9]{1,2}$ && ${6:-} =~ ^[0-9]{1,2}$ ]]; then
  MODE="range"
  YEAR="$1"; M="$2"; START_DAY="$3"
  END_YEAR="$4"; END_MONTH="$5"; END_DAY="$6"
  VARIABLE="${7:-${VARIABLE_NAME:-METREF}}"; URL="${8:-${URL:-}}"
elif [[ ${1:-} =~ ^[0-9]{4}$ && ${2:-} =~ ^[0-9]{1,2}$ && ${3:-} =~ ^[0-9]{1,2}$ ]]; then
  MODE="day"
  YEAR="$1"; M="$2"; START_DAY="$3"; END_YEAR="$1"; END_MONTH="$2"; END_DAY="$3"
  VARIABLE="${4:-${VARIABLE_NAME:-METREF}}"; URL="${5:-${URL:-}}"
elif [[ ${1:-} =~ ^[0-9]{4}$ && ${2:-} =~ ^[0-9]{1,2}$ ]]; then
  MODE="month"
  YEAR="$1"; M="$2"; END_YEAR="$1"; END_MONTH="$2"
  VARIABLE="${3:-${VARIABLE_NAME:-METREF}}"; URL="${4:-${URL:-}}"
elif [[ ${1:-} =~ ^[0-9]{4}$ ]]; then
  MODE="year"
  YEAR="$1"; END_YEAR="$1"
  VARIABLE="${2:-${VARIABLE_NAME:-METREF}}"; URL="${3:-${URL:-}}"
else
  usage
fi
JOBS="${JOBS:-4}"
[[ $YEAR =~ ^[0-9]{4}$ ]] || usage
[[ $M =~ ^[0-9]{1,2}$ ]] || usage
[[ ${END_YEAR:-$YEAR} =~ ^[0-9]{4}$ && ${END_MONTH:-$M} =~ ^[0-9]{1,2}$ ]] || usage
[[ ${START_DAY:-1} =~ ^[0-9]{1,2}$ && ${END_DAY:-31} =~ ^[0-9]{1,2}$ ]] || usage
(( 10#${M:-1} >= 1 && 10#${M:-1} <= 12 && 10#${END_MONTH:-$M} >= 1 && 10#${END_MONTH:-$M} <= 12 && 10#${START_DAY:-1} >= 1 && 10#${START_DAY:-1} <= 31 && 10#${END_DAY:-31} >= 1 && 10#${END_DAY:-31} <= 31 )) || usage
[[ $VARIABLE =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "Variable name must contain only letters, numbers, '.', '_' or '-'" >&2; exit 1; }
: "${URL:?missing URL (pass it as the last argument or add URL to $ENV_FILE)}"
MONTH=$(printf '%02d' $((10#$M)))
END_MONTH=$(printf '%02d' $((10#${END_MONTH:-$M})))
START_DAY=${START_DAY:-1}
END_DAY=${END_DAY:-31}
MONTH_NUM=$((10#$MONTH))
END_MONTH_NUM=$((10#$END_MONTH))
START_DAY_NUM=$((10#$START_DAY))
END_DAY_NUM=$((10#$END_DAY))
if [[ $MODE == year ]]; then
  START_DATE=$(printf '%04d-01-01' "$YEAR")
  END_DATE=$(printf '%04d-12-31' "$YEAR")
elif [[ $MODE == month ]]; then
  START_DATE=$(printf '%04d-%02d-01' "$YEAR" "$MONTH_NUM")
  END_DATE=$(date -d "$(printf '%04d-%02d-01' "$YEAR" "$MONTH_NUM") +1 month -1 day" +%F)
elif [[ $MODE == day ]]; then
  START_DATE=$(printf '%04d-%02d-%02d' "$YEAR" "$MONTH_NUM" "$START_DAY_NUM")
  END_DATE="$START_DATE"
else
  START_DATE=$(printf '%04d-%02d-%02d' "$YEAR" "$MONTH_NUM" "$START_DAY_NUM")
  END_DATE=$(printf '%04d-%02d-%02d' "$END_YEAR" "$END_MONTH_NUM" "$END_DAY_NUM")
fi
start_epoch=$(date -d "$START_DATE" +%s)
end_epoch=$(date -d "$END_DATE" +%s)
(( start_epoch <= end_epoch )) || { echo "Start date must be on or before end date." >&2; exit 1; }
command -v wget >/dev/null || { echo "wget not found" >&2; exit 1; }

WGETRC="$(mktemp)"; export WGETRC; trap 'rm -f "$WGETRC"' EXIT
printf 'http_user=%s\nhttp_password=%s\n' "$LSASAF_USERNAME" "$LSASAF_PASSWORD" > "$WGETRC"

SRC="${URL%/}"; HOST="${SRC%%/PRODUCTS*}"
ROOT="${RAW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/raw}/$VARIABLE"
mkdir -p "$ROOT"

# 1) Collect file URLs for the requested date range (days that don't exist return no listing)
list=""
current="$START_DATE"
start_month=$(date -d "$START_DATE" +%Y-%m-01)
end_month=$(date -d "$END_DATE" +%Y-%m-01)
while :; do
  y=${current%%-*}; rest=${current#*-}; m=${rest%%-*}
  m_num=$((10#$m))
  yyyymm=$(printf '%04d/%02d' "$y" "$m_num")
  month_start=1
  month_end=$(date -d "$(printf '%04d-%02d-01' "$y" "$m_num") +1 month -1 day" +%d)
  current_month=$(printf '%04d-%02d-01' "$y" "$m_num")
  [[ $current_month == "$start_month" ]] && month_start=$START_DAY
  [[ $current_month == "$end_month" ]] && month_end=$END_DAY
  dest="$ROOT/$y/$m"
  mkdir -p "$dest"
  for d in $(seq -w "$month_start" "$month_end"); do
    while IFS= read -r url; do
      [[ -n "$url" ]] && list+="$url"$'\t'"$dest"$'\n'
    done < <({ wget -q -O- --tries=3 --timeout=60 "$SRC/$yyyymm/$d/" || true; } \
            | tr '"' '\n' | grep -E '\.nc$' | sed "s|^|$HOST|" || true)
  done
  [[ $current_month == "$end_month" ]] && break
  current=$(date -d "$current +1 month" +%Y-%m-01)
done
pending=$(while IFS=$'\t' read -r u d; do [ -z "$u" ] || [ -f "$d/${u##*/}" ] || printf '%s\t%s\n' "$u" "$d"; done <<< "$list")
found=$(printf '%s' "$list" | grep -c . || true); n=$(printf '%s' "$pending" | grep -c . || true)
echo "$START_DATE -> $END_DATE: $found file(s) on server, $n to download -> $ROOT"
(( n )) || { echo "Already up to date."; exit 0; }

# 2) Download (to .part, then rename, so interrupted files are never mistaken for complete ones)
get() { local f="$2/${1##*/}"
        wget -q --tries=3 --timeout=60 -O "$f.part" "$1" && mv "$f.part" "$f" \
          || { echo "FAILED: $1" >&2; return 1; }; }
export -f get
fmt() { printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); }

t0=$SECONDS; first_url=$(head -n1 <<< "$pending" | cut -f1); first_dest=$(head -n1 <<< "$pending" | cut -f2); get "$first_url" "$first_dest"          # time one file for an estimate
dt=$((SECONDS - t0)); dt=$((dt < 1 ? 1 : dt))
echo "First file: ~${dt}s. Estimated remaining: ~$(fmt $((dt * (n - 1) / JOBS))) with $JOBS parallel jobs"
(( n > 1 )) && { tail -n +2 <<< "$pending" \
  | xargs -P "$JOBS" -d $'\n' -I{} bash -c 'IFS=$'"'\t'"' read -r url dest <<< "$1"; get "$url" "$dest"' _ {} \
  || { echo "Some downloads failed. Re-run to retry." >&2; exit 1; }; }
echo "Done: $n file(s) in $(fmt $SECONDS)"