"""Background loop + bottom showwaves + ASS burn (NVENC or libx264)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ASS_NAME = "lyrics.ass"
OUT_NAME = "final_lyrics.mp4"
_VIZ_FRAC = 0.16
_DEFAULT_WAVE = "0x37AFD4|0x88EEFF|0xFFFFFF"

_NVENC_OK: bool | None = None


def say(*values: Any) -> None:
    print(*values, flush=True)


def nvenc_ok() -> bool:
    """Probe h264_nvenc once; cache the result for the process."""
    global _NVENC_OK
    if _NVENC_OK is not None:
        return _NVENC_OK
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x180:d=0.04",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        _NVENC_OK = proc.returncode == 0
    except OSError:
        _NVENC_OK = False
    return _NVENC_OK


def h264_args(bitrate: str | None = None) -> list[str]:
    if nvenc_ok():
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p1",
            "-rc",
            "vbr",
            "-cq",
            "20",
            "-b:v",
            str(bitrate or "12M"),
            "-pix_fmt",
            "yuv420p",
        ]
    say("[render] WARNING: NVENC unavailable, using libx264")
    args = ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]
    if bitrate:
        args += ["-maxrate", str(bitrate), "-bufsize", str(bitrate)]
    return [*args, "-pix_fmt", "yuv420p"]


def aac_args(bitrate: str = "192k") -> list[str]:
    return ["-c:a", "aac", "-b:a", str(bitrate), "-ar", "48000", "-ac", "2"]


def cover_vf(width: int, height: int) -> str:
    """Center-cover scale+crop to an exact delivery box."""
    return (
        f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=increase,"
        f"crop={int(width)}:{int(height)}"
    )


def duration_sec(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        return float((proc.stdout or "").strip() or 0.0)
    except ValueError:
        return 0.0


def has_audio(path: Path) -> bool:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return bool((proc.stdout or "").strip())


def video_meta(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    import json

    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return {}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    width = height = 0
    if streams:
        width = int(streams[0].get("width") or 0)
        height = int(streams[0].get("height") or 0)
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"width": width, "height": height, "duration": duration}


def copy_audio(src: Path, dest: Path, *, force: bool = False) -> Path:
    if dest.is_file() and not force:
        say(f"[render] reusing {dest.name}")
        return dest
    say(f"[render] copying audio -> {dest.name}")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not dest.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError("audio copy failed:\n" + "\n".join(tail))
    return dest


def mux_bg_showwaves_burn(
    bg_image: Path,
    audio: Path,
    work: Path,
    staged: Path,
    bitrate: str,
    *,
    width: int,
    height: int,
    fps: int,
    viz_frac: float = _VIZ_FRAC,
    wave_color: str = _DEFAULT_WAVE,
) -> None:
    """Still background + bottom ffmpeg showwaves + ASS burn in one encode pass.

    ASS path is cwd-relative (a Windows drive colon breaks filter options).
    """
    if staged.is_file():
        staged.unlink()
    viz_h = max(80, int(round(height * float(viz_frac))))
    fc = (
        f"[0:v]{cover_vf(width, height)},setsar=1,fps={int(fps)},"
        f"format=yuv420p[bg];"
        f"[1:a]showwaves=s={int(width)}x{int(viz_h)}:mode=cline:rate={int(fps)}:"
        f"colors={wave_color}:scale=sqrt,format=yuva420p,"
        f"colorchannelmixer=aa=0.92[viz];"
        f"[bg][viz]overlay=0:main_h-overlay_h[base];"
        f"[base]ass={ASS_NAME}[outv]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-loop",
        "1",
        "-i",
        str(bg_image.resolve()),
        "-i",
        str(audio.resolve()),
        "-filter_complex",
        fc,
        "-map",
        "[outv]",
        "-map",
        "1:a:0",
        *h264_args(bitrate),
        *aac_args("192k"),
        "-shortest",
        "-movflags",
        "+faststart",
        staged.name,
    ]
    encoder = "h264_nvenc" if nvenc_ok() else "libx264"
    say(f"[render] bg+showwaves+burn ({width}x{height}, viz={viz_h}px, {encoder})")
    proc = subprocess.run(
        cmd,
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not staged.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-10:]
        raise RuntimeError(
            f"bg+showwaves encode failed (rc={proc.returncode}):\n" + "\n".join(tail)
        )
