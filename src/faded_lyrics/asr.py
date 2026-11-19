"""Whisper word timestamps via ffmpeg float32 decode (skips broken av path)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_ASR_DEVICE = "cpu"
LYRICS_NAME = "lyrics.json"

# Out-of-process so a long CPU encode streams PROGRESS lines instead of buffering.
TRANSCRIBE_PROGRAM = r'''
import argparse, json, subprocess, sys
import numpy as np

a = argparse.ArgumentParser()
a.add_argument("--input", required=True)
a.add_argument("--ffmpeg", default="ffmpeg")
a.add_argument("--model", default="large-v3-turbo")
a.add_argument("--device", default="cpu")
a.add_argument("--language", default="")
a.add_argument("--vad", default="0")
a.add_argument("--engine", default="auto")
a.add_argument("--words", default="1")
a = a.parse_args()

def say(line):
    print(line, flush=True)

def decode(path):
    # Never faster-whisper's av decoder: av 19 rejects metadata_errors and that
    # failure looks like a broken model.
    proc = subprocess.run(
        [a.ffmpeg, "-v", "error", "-i", path, "-vn", "-ac", "1",
         "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[-600:])
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)

language = a.language or None
want_words = bool(int(a.words))
samples = decode(a.input)
duration = round(float(samples.size) / 16000.0, 3)
say("PROGRESS decoded %.1f s of audio" % duration)

payload = None
rows = []

def _word_rows(raw_words):
    out = []
    for item in raw_words or []:
        if isinstance(item, dict):
            token = " ".join(str(item.get("word") or item.get("text") or "").split())
            try:
                w0 = float(item.get("start") or 0.0)
                w1 = float(item.get("end") or w0)
            except (TypeError, ValueError):
                continue
        else:
            token = " ".join(str(getattr(item, "word", "") or "").split())
            try:
                w0 = float(getattr(item, "start", 0.0) or 0.0)
                w1 = float(getattr(item, "end", w0) or w0)
            except (TypeError, ValueError):
                continue
        if not token:
            continue
        out.append({"word": token, "start": round(w0, 3),
                    "end": round(max(w1, w0), 3)})
    return out

def emit(seg):
    text = " ".join(str(seg.get("text") or "").split())
    if not text:
        return
    start = float(seg.get("start") or 0.0)
    end = max(float(seg.get("end") or start), start)
    row = {"index": len(rows), "start": round(start, 3),
           "end": round(end, 3), "text": text}
    words = _word_rows(seg.get("words"))
    if words:
        row["words"] = words
    rows.append(row)
    say("PROGRESS segment %d at %.2f s: %s" % (len(rows), start, text[:80]))

if a.engine in ("auto", "faster-whisper"):
    try:
        from faster_whisper import WhisperModel
        compute = "int8" if a.device == "cpu" else "float16"
        say("PROGRESS loading faster-whisper %s on %s (%s)" % (a.model, a.device, compute))
        model = WhisperModel(a.model, device=a.device, compute_type=compute)
        gen, info = model.transcribe(
            samples,
            language=language,
            vad_filter=bool(int(a.vad)),
            beam_size=5,
            condition_on_previous_text=False,
            word_timestamps=want_words,
        )
        say("PROGRESS transcribing")
        for seg in gen:
            payload_seg = {"start": seg.start, "end": seg.end, "text": seg.text}
            if want_words:
                payload_seg["words"] = list(seg.words or [])
            emit(payload_seg)
        payload = {
            "engine": "faster-whisper",
            "device": a.device,
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "word_timestamps": want_words,
        }
    except Exception as exc:
        say("PROGRESS faster-whisper failed: %s: %s" % (type(exc).__name__, exc))
        if a.engine == "faster-whisper":
            print(json.dumps({"ok": False, "error": "faster-whisper: %s" % exc}))
            sys.exit(1)

if payload is None:
    import whisper
    rows.clear()
    say("PROGRESS loading openai-whisper %s on %s" % (a.model, a.device))
    model = whisper.load_model(a.model, device=a.device)
    result = model.transcribe(
        a.input, language=language, verbose=False,
        condition_on_previous_text=False, word_timestamps=want_words,
    )
    for seg in result.get("segments") or []:
        emit(seg)
    payload = {
        "engine": "openai-whisper",
        "device": a.device,
        "language": result.get("language"),
        "language_probability": None,
        "word_timestamps": want_words,
    }

payload.update({"ok": True, "duration_sec": duration, "segments": rows})
print(json.dumps(payload))
'''


def say(*values: Any) -> None:
    print(*values, flush=True)


def _source_signature(source: Path) -> dict[str, Any]:
    try:
        stat = source.stat()
    except OSError:
        return {"name": source.name}
    return {"name": source.name, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _read_doc(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_current(doc: dict, source: Path, model: str, language: str, engine: str = "auto") -> bool:
    if not isinstance(doc, dict) or not doc.get("segments"):
        return False
    if str(doc.get("model") or "") != str(model):
        return False
    if str(doc.get("language_requested") or "") != str(language):
        return False
    if str(doc.get("engine_requested") or "") != str(engine or "auto"):
        return False
    return doc.get("source") == _source_signature(source)


def _run_streaming(program: str, argv: list[str]) -> dict[str, Any]:
    """Run the worker, echo PROGRESS lines, return the JSON payload."""
    proc = subprocess.Popen(
        [sys.executable, "-c", program, *argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    payload: dict[str, Any] | None = None
    noise: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("PROGRESS "):
            say(f"[asr] {line[len('PROGRESS '):]}")
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                continue
            except ValueError:
                pass
        noise.append(line)
    code = proc.wait()
    if payload is None or not payload.get("ok") or code != 0:
        detail = str((payload or {}).get("error") or "") or "\n".join(noise[-12:])
        raise RuntimeError(f"transcription failed (exit {code}): {detail[-800:] or 'no output'}")
    return payload


def build_document(
    source: Path,
    *,
    payload: dict[str, Any],
    model: str,
    language: str,
    engine: str = "auto",
) -> dict[str, Any]:
    rows = []
    for row in payload.get("segments") or []:
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        start = float(row.get("start") or 0.0)
        entry: dict[str, Any] = {
            "index": len(rows),
            "start": round(start, 3),
            "end": round(max(float(row.get("end") or start), start), 3),
            "text": text,
        }
        words = row.get("words")
        if isinstance(words, list) and words:
            cleaned = []
            for item in words:
                if not isinstance(item, dict):
                    continue
                token = " ".join(str(item.get("word") or "").split())
                if not token:
                    continue
                try:
                    w0 = float(item.get("start") or 0.0)
                    w1 = float(item.get("end") or w0)
                except (TypeError, ValueError):
                    continue
                cleaned.append(
                    {"word": token, "start": round(w0, 3), "end": round(max(w1, w0), 3)}
                )
            if cleaned:
                entry["words"] = cleaned
        rows.append(entry)
    full = " ".join(row["text"] for row in rows).strip()
    if not rows:
        raise ValueError("the ASR returned no segments")
    return {
        "version": 1,
        "source": _source_signature(source),
        "model": str(model),
        "language_requested": str(language or ""),
        "language": str(payload.get("language") or ""),
        "language_probability": payload.get("language_probability"),
        "engine": str(payload.get("engine") or ""),
        "engine_requested": str(engine or "auto"),
        "device": str(payload.get("device") or ""),
        "duration_sec": round(float(payload.get("duration_sec") or 0.0), 3),
        "segment_count": len(rows),
        "chars": len(full),
        "segments": rows,
        "text": full,
    }


def transcribe_audio(
    audio: Path | str,
    out_dir: Path | str,
    *,
    model: str = DEFAULT_MODEL,
    language: str = "",
    asr_device: str = DEFAULT_ASR_DEVICE,
    engine: str = "auto",
    vad: bool = False,
    force: bool = False,
    word_timestamps: bool = True,
) -> dict:
    """Transcribe ``audio`` with word stamps; cache ``lyrics.json`` under ``out_dir``."""
    source = Path(audio)
    if not source.is_file():
        raise ValueError(f"no such audio file: {source}")
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / LYRICS_NAME

    if not force and destination.is_file():
        existing = _read_doc(destination)
        if is_current(existing, source, model, language, engine):
            if not word_timestamps or any(
                isinstance(row, dict) and row.get("words")
                for row in (existing.get("segments") or [])
            ):
                say(f"[asr] reusing {destination.name}")
                return existing

    say(f"[asr] transcribing {source.name} (model={model}, engine={engine})")
    argv = [
        "--input",
        str(source.resolve()),
        "--model",
        str(model),
        "--device",
        str(asr_device or DEFAULT_ASR_DEVICE),
        "--language",
        str(language or ""),
        "--vad",
        "1" if vad else "0",
        "--engine",
        str(engine or "auto"),
        "--words",
        "1" if word_timestamps else "0",
    ]
    payload = _run_streaming(TRANSCRIBE_PROGRAM, argv)
    doc = build_document(
        source,
        payload=payload,
        model=model,
        language=language,
        engine=engine,
    )
    destination.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    say(f"[asr] wrote {destination.name} ({doc['segment_count']} segments)")
    return doc


def collect_words(doc: dict) -> list[dict[str, Any]]:
    """Flat word list from a lyrics.json that carries per-segment ``words``."""
    out: list[dict[str, Any]] = []
    for seg in doc.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        words = seg.get("words")
        if isinstance(words, list) and words:
            for item in words:
                if not isinstance(item, dict):
                    continue
                token = " ".join(str(item.get("word") or "").split())
                if not token:
                    continue
                try:
                    start = float(item.get("start") or 0.0)
                    end = float(item.get("end") or start)
                except (TypeError, ValueError):
                    continue
                out.append(
                    {
                        "word": token,
                        "start": max(0.0, start),
                        "end": max(start + 0.04, end),
                    }
                )
            continue
        text = " ".join(str(seg.get("text") or "").split())
        try:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or start)
        except (TypeError, ValueError):
            continue
        tokens = text.split()
        if not tokens:
            continue
        weights = [max(1, len(t)) for t in tokens]
        total = float(sum(weights))
        span = max(0.05, end - start)
        cursor = start
        for token, weight in zip(tokens, weights):
            piece = span * (weight / total)
            out.append(
                {
                    "word": token,
                    "start": cursor,
                    "end": cursor + max(0.04, piece),
                }
            )
            cursor += piece
    out.sort(key=lambda row: row["start"])
    return out
