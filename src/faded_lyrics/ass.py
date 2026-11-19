"""Fade / pop ASS karaoke + plain SRT helpers."""

from __future__ import annotations

from typing import Any

from faded_lyrics.palette import DEFAULT_DIM, DEFAULT_SUNG

_OUTLINE = "&H00000000"
_BACK = "&H80000000"
_POP_SCALE = 112
_POP_SETTLE_MS = 160
_GLYPH_FRAC = 0.58
_LINE_MAX_FRAC = 0.86


def ass_time(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours, rem = divmod(total, 3600.0)
    minutes, secs = divmod(rem, 60.0)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def srt_time(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours, rem = divmod(total, 3600.0)
    minutes, secs = divmod(rem, 60.0)
    return (
        f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d},"
        f"{int(round((secs % 1.0) * 1000)):03d}"
    )


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _load_ass_font(font_px: int) -> Any:
    """Bold Arial for real glyph widths; None falls back to the em estimate."""
    try:
        from PIL import ImageFont
    except Exception:  # noqa: BLE001
        return None
    for name in ("arialbd.ttf", "Arial Bold.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, int(font_px))
        except OSError:
            continue
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def _word_width_px(font: Any, token: str, font_px: int) -> float:
    if font is not None:
        try:
            box = font.getbbox(token)
            return float(max(1, box[2] - box[0]))
        except Exception:  # noqa: BLE001
            pass
    return max(8.0, float(font_px) * _GLYPH_FRAC * max(1, len(token)))


def wrap_display_lines(
    lines: list[list[dict]],
    *,
    width: int,
    font_px: int,
    max_frac: float = _LINE_MAX_FRAC,
) -> list[list[dict]]:
    """Re-wrap timed lines so each fits inside ``max_frac`` of the frame width."""
    font = _load_ass_font(font_px)
    space = _word_width_px(font, " ", font_px)
    limit = float(width) * float(max_frac)
    out: list[list[dict]] = []
    for line in lines:
        if not line:
            continue
        current: list[dict] = []
        used = 0.0
        for word in line:
            w = _word_width_px(font, str(word["word"]), font_px)
            need = w if not current else used + space + w
            if current and need > limit:
                out.append(current)
                current = [word]
                used = w
            else:
                current.append(word)
                used = need
        if current:
            out.append(current)
    return out


def build_fade_ass(
    lines: list[list[dict]],
    *,
    width: int,
    height: int,
    margin_bottom: float = 0.40,
    font_px: int | None = None,
    fade_ms: int = 420,
    lead_in: float = 0.12,
    sung_color: str = DEFAULT_SUNG,
    dim_color: str = DEFAULT_DIM,
    pop_scale: int = _POP_SCALE,
) -> str:
    """Per-word karaoke: waiting dim, sung accent pop, then fade out.

    ``margin_bottom`` is the fraction of frame height from the BOTTOM up to the
    baseline.
    """
    font_px = int(font_px) if font_px else max(40, int(round(height * 0.065)))
    outline = max(2, int(round(height * 0.0045)))
    shadow = max(1, outline // 2)
    y = int(round(height * (1.0 - float(margin_bottom))))
    font = _load_ass_font(font_px)
    space = _word_width_px(font, " ", font_px)
    fade_ms = max(80, int(fade_ms))
    pop = max(100, min(140, int(pop_scale)))
    display = wrap_display_lines(lines, width=width, font_px=font_px)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Word,Arial,{font_px},&H00FFFFFF,&H00FFFFFF,{_OUTLINE},{_BACK},"
            f"-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,0,0,0,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    for line in display:
        if not line:
            continue
        widths = [_word_width_px(font, str(w["word"]), font_px) for w in line]
        total = sum(widths) + space * max(0, len(line) - 1)
        x_cursor = max(0.0, (float(width) - total) / 2.0)
        line_start = max(0.0, float(line[0]["start"]) - float(lead_in))
        for word, w_width in zip(line, widths):
            token = _ass_escape(str(word["word"]))
            w0 = float(word["start"])
            w1 = float(word["end"])
            x = x_cursor + w_width / 2.0
            x_cursor += w_width + space
            dlg_end = w1 + fade_ms / 1000.0
            hit = max(0, int(round((w0 - line_start) * 1000.0)))
            settle = hit + _POP_SETTLE_MS
            fade0 = max(settle + 20, int(round((w1 - line_start) * 1000.0)))
            fade1 = fade0 + fade_ms
            tags = (
                f"{{\\an5\\pos({x:.1f},{y})\\c{dim_color}\\1a&H00&"
                f"\\fscx100\\fscy100"
                f"\\t({hit},{hit + 45},\\c{sung_color}\\fscx{pop}\\fscy{pop})"
                f"\\t({hit + 45},{settle},\\fscx100\\fscy100)"
                f"\\t({fade0},{fade1},\\alpha&HFF&\\fscx92\\fscy92)}}"
            )
            events.append(
                f"Dialogue: 0,{ass_time(line_start)},{ass_time(dlg_end)},"
                f"Word,,0,0,0,,{tags}{token}"
            )
    return "\n".join([*header, *events]) + "\n"


def build_plain_srt(lines: list[list[dict]]) -> str:
    blocks: list[str] = []
    index = 1
    for line in lines:
        text = " ".join(str(w["word"]) for w in line)
        t0 = float(line[0]["start"])
        t1 = max(t0 + 0.2, float(line[-1]["end"]))
        blocks.append(f"{index}\n{srt_time(t0)} --> {srt_time(t1)}\n{text}\n")
        index += 1
    return "\n".join(blocks) + ("\n" if blocks else "")
