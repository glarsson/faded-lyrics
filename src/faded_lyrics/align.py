"""Sheet parse + Needleman-Wunsch token align to ASR word clocks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Generic spelling drift only. No track-specific echo phrase collapse.
_TOKEN_ALIASES = {
    "gon": "gonna",
    "gonna": "gon",
    "ya": "you",
    "you": "ya",
    "lemme": "letme",
    "letme": "lemme",
    "gotta": "gotto",
    "gotto": "gotta",
    "headin": "heading",
    "heading": "headin",
    "sayin": "saying",
    "saying": "sayin",
}


def parse_sheet(path: Path) -> list[str]:
    """Written lyrics, one display line each; ``[chorus]``-style tags dropped."""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = " ".join(raw.split())
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            continue
        lines.append(text)
    return lines


def _norm_tok(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def _tokens_match(sheet_n: str, asr_n: str) -> bool:
    if not sheet_n or not asr_n:
        return False
    if sheet_n == asr_n:
        return True
    if _TOKEN_ALIASES.get(sheet_n) == asr_n or _TOKEN_ALIASES.get(asr_n) == sheet_n:
        return True
    if len(sheet_n) >= 4 and len(asr_n) >= 4:
        if sheet_n.startswith(asr_n) or asr_n.startswith(sheet_n):
            return True
    if len(sheet_n) >= 5 and len(asr_n) >= 5 and abs(len(sheet_n) - len(asr_n)) <= 2:
        misses = sum(1 for a, b in zip(sheet_n, asr_n) if a != b)
        misses += abs(len(sheet_n) - len(asr_n))
        if misses <= 2:
            return True
    return False


def align_sheet_words(
    lines: list[str],
    asr_words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Sheet spelling + ASR word clocks, grouped by the sheet's own line breaks.

    Needleman-Wunsch over tokens (match / skip-ASR / skip-sheet). Global and
    monotonic, so repeated choruses consume successive ASR choruses instead of
    all collapsing onto the last one.
    """
    sheet_tokens: list[str] = []
    line_of: list[int] = []
    for index, line in enumerate(lines):
        for token in line.split():
            token = token.rstrip(",.")
            if _norm_tok(token) == "":
                continue
            sheet_tokens.append(token)
            line_of.append(index)
    if not sheet_tokens or not asr_words:
        return []

    sheet_n = [_norm_tok(t) for t in sheet_tokens]
    sheet_n = ["letme" if t == "lemme" else t for t in sheet_n]
    asr_n = [_norm_tok(str(w["word"])) for w in asr_words]
    asr_use = list(asr_n)
    asr_span: list[tuple[int, int]] = [(i, i) for i in range(len(asr_words))]
    for i in range(len(asr_n) - 1):
        if asr_n[i] == "let" and asr_n[i + 1] == "me":
            asr_use[i] = "letme"
            asr_span[i] = (i, i + 1)

    n, m = len(sheet_n), len(asr_use)
    MATCH, MISMATCH, GAP_ASR, GAP_SHEET = 2, -2, -1, -2
    neg = -10**9
    score = [[neg] * (m + 1) for _ in range(n + 1)]
    back: list[list[str]] = [[""] * (m + 1) for _ in range(n + 1)]
    score[0][0] = 0
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + GAP_SHEET
        back[i][0] = "S"
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + GAP_ASR
        back[0][j] = "A"

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            matched = _tokens_match(sheet_n[i - 1], asr_use[j - 1])
            diag = score[i - 1][j - 1] + (MATCH if matched else MISMATCH)
            up = score[i - 1][j] + GAP_SHEET
            left = score[i][j - 1] + GAP_ASR
            best = diag
            move = "M" if matched else "X"
            if up > best:
                best, move = up, "S"
            if left > best:
                best, move = left, "A"
            if matched and diag >= best:
                best, move = diag, "M"
            score[i][j] = best
            back[i][j] = move

    placed: list[tuple[float, float] | None] = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j] if i or j else ""
        if move == "M":
            lo, hi = asr_span[j - 1]
            placed[i - 1] = (
                float(asr_words[lo]["start"]),
                float(asr_words[hi]["end"]),
            )
            i -= 1
            j -= 1
        elif move in ("X", "S"):
            i -= 1
            if move == "X":
                j -= 1
        else:
            j -= 1

    known = [k for k, value in enumerate(placed) if value is not None]
    if not known:
        return []
    first, last = known[0], known[-1]
    for index in range(first):
        placed[index] = placed[first]
    anchor = first
    for index in range(first + 1, last + 1):
        if placed[index] is None:
            continue
        if index - anchor > 1:
            lo_s, lo_e = placed[anchor] or (0.0, 0.0)
            hi_s, hi_e = placed[index] or (0.0, 0.0)
            steps = index - anchor
            for step_i in range(1, steps):
                frac = step_i / float(steps)
                placed[anchor + step_i] = (
                    lo_s + (hi_s - lo_s) * frac,
                    lo_e + (hi_e - lo_e) * frac,
                )
        anchor = index
    if last < n - 1:
        lengths = [
            max(0.12, float(placed[k][1]) - float(placed[k][0]))
            for k in known
        ]
        step = sum(lengths) / float(len(lengths))
        cursor_t = float((placed[last] or (0.0, 0.0))[1])
        asr_end = float(asr_words[-1]["end"])
        remain = n - 1 - last
        if remain > 0 and asr_end > cursor_t + 0.5:
            step = max(step, (asr_end - cursor_t) / float(remain))
        for index in range(last + 1, n):
            placed[index] = (cursor_t, cursor_t + step)
            cursor_t += step

    grouped: list[list[dict[str, Any]]] = [[] for _ in lines]
    prev_start = -1.0
    for index, token in enumerate(sheet_tokens):
        span = placed[index]
        if span is None:
            continue
        start, end = float(span[0]), float(span[1])
        if start < prev_start:
            start = prev_start + 0.04
            end = max(end, start + 0.04)
        prev_start = start
        grouped[line_of[index]].append(
            {
                "word": token,
                "start": max(0.0, start),
                "end": max(start + 0.04, end),
            }
        )
    return [line for line in grouped if line]


def group_lines(words: list[dict], *, cap: int = 36) -> list[list[dict]]:
    """Pack words into short on-screen lines (never split a word)."""
    lines: list[list[dict]] = []
    current: list[dict] = []
    length = 0
    for word in words:
        token = str(word["word"])
        extra = len(token) + (1 if current else 0)
        if current and (float(word["start"]) - float(current[-1]["end"])) > 1.25:
            lines.append(current)
            current = []
            length = 0
        if current and length + extra > int(cap):
            lines.append(current)
            current = []
            length = 0
        current.append(word)
        length = length + extra if length else len(token)
    if current:
        lines.append(current)
    return lines
