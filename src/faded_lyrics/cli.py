"""CLI: still background + showwaves + Whisper-timed fade lyrics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from faded_lyrics import align, asr, ass, palette, render

ASS_NAME = "lyrics.ass"
SRT_NAME = "lyrics.srt"
OUT_NAME = "final_lyrics.mp4"
AUDIO_NAME = "source.wav"

_PORTRAIT = (1080, 1920)
_LANDSCAPE = (1920, 1080)
_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_VIZ_FRAC = 0.16


def say(*values: Any) -> None:
    print(*values, flush=True)


def fail(line: str) -> None:
    print(f"error: {line}", file=sys.stderr, flush=True)


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "clip"


def _default_out(source: Path) -> Path:
    return Path.cwd() / "out" / _slug(source.name)


def _is_audio(path: Path) -> bool:
    return path.suffix.lower() in _AUDIO_SUFFIXES


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _aspect_canvas(aspect: str) -> tuple[int, int] | None:
    key = (aspect or "").strip().replace(" ", "")
    if not key:
        return None
    if key in ("9:16", "9x16", "portrait"):
        return _PORTRAIT
    if key in ("16:9", "16x9", "landscape"):
        return _LANDSCAPE
    return None


def _default_font_px(width: int, height: int) -> int:
    if height > width:
        return max(44, int(round(width * 0.058)))
    return max(40, int(round(height * 0.065)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m faded_lyrics",
        description=(
            "Still background + bottom ffmpeg showwaves + Whisper-timed fade lyrics."
        ),
    )
    ap.add_argument("--picture", "--bg-image", dest="picture", required=True,
                    help="background still (png/jpg/webp)")
    ap.add_argument("--audio", required=True, help="wav/mp3/flac master track")
    ap.add_argument("--lyrics", "--lyrics-file", dest="lyrics", default="",
                    help="optional written sheet; spelling on screen, times from ASR")
    ap.add_argument("--out-dir", default="", help="artifact dir (default ./out/<slug>)")
    ap.add_argument("--model", default=asr.DEFAULT_MODEL, help="whisper model name")
    ap.add_argument("--language", default="", help="ISO language; empty = detect")
    ap.add_argument("--asr-device", default=asr.DEFAULT_ASR_DEVICE)
    ap.add_argument(
        "--engine",
        default="auto",
        choices=("auto", "faster-whisper", "openai-whisper"),
    )
    ap.add_argument("--force", action="store_true", help="re-copy audio / re-ASR / re-encode")
    ap.add_argument("--dry-run", action="store_true", help="write ASS/SRT only, skip encode")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument(
        "--aspect",
        default="16:9",
        help="delivery box: 16:9 (1920x1080) or 9:16 (1080x1920)",
    )
    ap.add_argument("--viz-frac", type=float, default=_VIZ_FRAC,
                    help="bottom showwaves height as fraction of frame (default 0.16)")
    ap.add_argument("--margin-v", type=float, default=0.40,
                    help="baseline as fraction of height from the BOTTOM (default 0.40)")
    ap.add_argument("--font-px", type=int, default=0)
    ap.add_argument("--cap", type=int, default=36, help="chars per line when no sheet")
    ap.add_argument("--fade-ms", type=int, default=420, help="post-word fade-out (ms)")
    ap.add_argument("--bitrate", default="12M")
    args = ap.parse_args(argv)

    picture = Path(args.picture)
    audio_arg = Path(args.audio)
    if not picture.is_file():
        fail(f"no such picture: {picture}")
        return 2
    if not _is_image(picture):
        fail(f"picture must be an image file: {picture}")
        return 2
    if not audio_arg.is_file():
        fail(f"no such audio: {audio_arg}")
        return 2
    if not _is_audio(audio_arg):
        fail(f"audio must be wav/mp3/flac/...: {audio_arg}")
        return 2

    work = Path(args.out_dir) if args.out_dir else _default_out(audio_arg)
    work.mkdir(parents=True, exist_ok=True)
    say(f"[faded_lyrics] out-dir {work}")
    say(f"[faded_lyrics] NVENC={'yes' if render.nvenc_ok() else 'no'}")

    try:
        audio = render.copy_audio(audio_arg, work / AUDIO_NAME, force=bool(args.force))
        doc = asr.transcribe_audio(
            audio,
            work,
            model=str(args.model or asr.DEFAULT_MODEL),
            language=str(args.language or ""),
            asr_device=str(args.asr_device),
            engine=str(args.engine),
            force=bool(args.force),
            word_timestamps=True,
        )
    except Exception as exc:  # noqa: BLE001
        fail(str(exc))
        return 1

    asr_words = asr.collect_words(doc)
    say(
        f"[faded_lyrics] {len(doc.get('segments') or [])} segment(s), "
        f"{len(asr_words)} ASR word(s), lang={doc.get('language')}"
    )
    if not asr_words:
        fail("no usable timed words")
        return 1

    sheet_path = Path(args.lyrics) if args.lyrics else None
    if sheet_path is None:
        candidate = work / "lyrics_sheet.txt"
        if candidate.is_file():
            sheet_path = candidate
    if sheet_path is not None:
        if not sheet_path.is_file():
            fail(f"no sheet at {sheet_path}")
            return 2
        sheet_lines = align.parse_sheet(sheet_path)
        lines = align.align_sheet_words(sheet_lines, asr_words)
        say(
            f"[faded_lyrics] sheet {sheet_path.name}: {len(sheet_lines)} line(s) -> "
            f"{sum(len(x) for x in lines)} word(s) on {len(lines)} line(s)"
        )
        if not lines:
            fail("sheet did not align to any ASR words")
            return 1
    else:
        lines = align.group_lines(asr_words, cap=int(args.cap or 36))

    flat = [w for line in lines for w in line]
    for row in flat[:12]:
        say(f"  {row['start']:8.2f} -> {row['end']:8.2f}  {row['word']}")
    if len(flat) > 12:
        say(f"  ... ({len(flat) - 12} more words)")

    canvas = _aspect_canvas(str(args.aspect or ""))
    if canvas is not None:
        width, height = canvas
    else:
        width = int(args.width or 1920)
        height = int(args.height or 1080)

    margin_v = float(args.margin_v)
    if margin_v < 0:
        margin_v = 0.34 if height > width else 0.40
    font_px = int(args.font_px or _default_font_px(width, height))

    sung_color, dim_color, pal_meta = palette.sample_image_palette(picture)
    say(
        f"[faded_lyrics] palette source={pal_meta.get('source')} "
        f"sung={pal_meta.get('rgb_sung')} dim={pal_meta.get('rgb_dim')}"
    )

    ass_text = ass.build_fade_ass(
        lines,
        width=width,
        height=height,
        margin_bottom=margin_v,
        font_px=font_px,
        fade_ms=int(args.fade_ms or 420),
        sung_color=sung_color,
        dim_color=dim_color,
    )
    (work / ASS_NAME).write_text(ass_text, encoding="utf-8")
    (work / SRT_NAME).write_text(ass.build_plain_srt(lines), encoding="utf-8")
    events = sum(1 for line in ass_text.splitlines() if line.startswith("Dialogue:"))
    say(
        f"[faded_lyrics] {len(flat)} word(s) -> {events} fade event(s) "
        f"({width}x{height}, font {font_px}px, fade {int(args.fade_ms)} ms)"
    )

    if args.dry_run:
        say("[faded_lyrics] dry run, nothing encoded")
        return 0

    staged = work / OUT_NAME
    try:
        render.mux_bg_showwaves_burn(
            picture,
            audio,
            work,
            staged,
            str(args.bitrate or "12M"),
            width=width,
            height=height,
            fps=int(args.fps or 30),
            viz_frac=float(args.viz_frac or _VIZ_FRAC),
        )
    except Exception as exc:  # noqa: BLE001
        fail(str(exc))
        return 1

    out_meta = render.video_meta(staged)
    out_dur = float(out_meta.get("duration") or 0.0)
    ref_duration = render.duration_sec(audio)
    say(
        f"[faded_lyrics] burned {out_meta.get('width')}x{out_meta.get('height')} "
        f"{out_dur:.3f} s {staged.stat().st_size / 1e6:.1f} MB"
    )

    problems: list[str] = []
    if abs(out_dur - ref_duration) > 0.15:
        problems.append(f"duration {out_dur:.3f}s vs audio {ref_duration:.3f}s")
    if not render.has_audio(staged):
        problems.append("no audio stream")
    if problems:
        fail("FAIL: " + "; ".join(problems))
        return 1

    sidecar = {
        "audio": str(audio.resolve()),
        "picture": str(picture.resolve()),
        "words": len(flat),
        "events": events,
        "duration_sec": out_dur,
        "fade_ms": int(args.fade_ms),
        "margin_v": float(margin_v),
        "font_px": int(font_px),
        "aspect": str(args.aspect or "") or None,
        "canvas": [int(width), int(height)],
        "nvenc": bool(render.nvenc_ok()),
        "sheet": str(sheet_path) if sheet_path else None,
        "palette": pal_meta,
    }
    (work / "burn.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    say(f"[faded_lyrics] PASS -> {staged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
