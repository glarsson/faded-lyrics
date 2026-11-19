#!/usr/bin/env bash
# faded-lyrics: still background + bottom ffmpeg showwaves + Whisper fade lyrics.
#
# Usage:
#   ./run_eq_with_lyrics.sh <picture.png> <track.mp3|wav> [lyrics.txt]
#   ./run_eq_with_lyrics.sh --picture bg.png --audio song.wav [--lyrics sheet.txt]
#
# Optional env / flags:
#   --out-dir DIR   artifact folder (default ./out/<slug>)
#   --aspect 16:9|9:16 (default 16:9)
#   --copy-to DIR   also copy final_lyrics.mp4 here
#   --force         re-copy audio / re-ASR

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || command -v python || true)"
fi
if [[ -z "${PYTHON}" ]]; then
  echo "error: no python found" >&2
  exit 2
fi

PICTURE=""
AUDIO=""
LYRICS=""
OUT_DIR=""
ASPECT="16:9"
COPY_TO=""
VIZ_FRAC="0.16"
MARGIN_V="0.40"
FORCE=0

usage() {
  cat <<'EOF'
Usage:
  ./run_eq_with_lyrics.sh <picture.png> <track.mp3|wav> [lyrics.txt]
  ./run_eq_with_lyrics.sh --picture bg.png --audio song.wav [--lyrics sheet.txt]

Options: --out-dir --aspect 16:9|9:16 --copy-to DIR --viz-frac 0.16 --margin-v 0.40 --force
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --picture|--bg|--image) PICTURE="$2"; shift 2 ;;
    --audio|--track|--song) AUDIO="$2"; shift 2 ;;
    --lyrics|--sheet|--txt) LYRICS="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --aspect) ASPECT="$2"; shift 2 ;;
    --copy-to) COPY_TO="$2"; shift 2 ;;
    --viz-frac) VIZ_FRAC="$2"; shift 2 ;;
    --margin-v) MARGIN_V="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*)
      echo "error: unknown flag $1" >&2
      usage
      exit 2
      ;;
    *)
      if [[ -z "$PICTURE" ]]; then PICTURE="$1"
      elif [[ -z "$AUDIO" ]]; then AUDIO="$1"
      elif [[ -z "$LYRICS" ]]; then LYRICS="$1"
      else
        echo "error: unexpected argument $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$PICTURE" || -z "$AUDIO" ]]; then
  usage
  exit 2
fi
if [[ ! -f "$PICTURE" ]]; then echo "error: no such picture: $PICTURE" >&2; exit 2; fi
if [[ ! -f "$AUDIO" ]]; then echo "error: no such audio: $AUDIO" >&2; exit 2; fi
if [[ -n "$LYRICS" && ! -f "$LYRICS" ]]; then echo "error: no such lyrics: $LYRICS" >&2; exit 2; fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(
  -u -m faded_lyrics
  --audio "$(cd "$(dirname "$AUDIO")" && pwd)/$(basename "$AUDIO")"
  --picture "$(cd "$(dirname "$PICTURE")" && pwd)/$(basename "$PICTURE")"
  --aspect "$ASPECT"
  --width 1920 --height 1080 --fps 30
  --margin-v "$MARGIN_V"
  --viz-frac "$VIZ_FRAC"
)
if [[ -n "$LYRICS" ]]; then
  ARGS+=(--lyrics "$(cd "$(dirname "$LYRICS")" && pwd)/$(basename "$LYRICS")")
fi
if [[ -n "$OUT_DIR" ]]; then
  mkdir -p "$OUT_DIR"
  ARGS+=(--out-dir "$(cd "$OUT_DIR" && pwd)")
fi
if [[ "$FORCE" -eq 1 ]]; then ARGS+=(--force); fi

echo "[eq+lyrics] picture  ${ARGS[4]}"
echo "[eq+lyrics] audio    ${ARGS[2]}"
echo "[eq+lyrics] aspect   $ASPECT  viz=$VIZ_FRAC  marginV=$MARGIN_V"
echo "[eq+lyrics] python   $PYTHON"

"$PYTHON" "${ARGS[@]}"
code=$?
if [[ $code -ne 0 ]]; then
  echo "[eq+lyrics] FAILED (exit $code)"
  exit "$code"
fi

FINAL=""
if [[ -n "$OUT_DIR" && -f "${OUT_DIR}/final_lyrics.mp4" ]]; then
  FINAL="$(cd "$(dirname "${OUT_DIR}/final_lyrics.mp4")" && pwd)/final_lyrics.mp4"
else
  FINAL="$(find "$ROOT/out" -name final_lyrics.mp4 -type f 2>/dev/null | head -1 || true)"
fi

if [[ -n "$FINAL" ]]; then
  echo "[eq+lyrics] PASS -> $FINAL"
  if [[ -n "$COPY_TO" ]]; then
    mkdir -p "$COPY_TO"
    stem="$(basename "$AUDIO")"
    stem="${stem%.*}"
    dest="${COPY_TO}/${stem} - lyrics visualizer.mp4"
    cp -f "$FINAL" "$dest"
    echo "[eq+lyrics] copied -> $dest"
  fi
else
  echo "[eq+lyrics] PASS (could not resolve final_lyrics.mp4 path)"
fi
exit 0
