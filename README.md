# faded-lyrics

Turn a **still background image** and an **audio track** into a lyric video: https://youtu.be/u99B8Z-E__0?t=38

- loops the picture to the track length
- draws a neon `ffmpeg showwaves` strip along the bottom
- times each word with Whisper (faster-whisper by default)
- burns per-word pop + fade ASS lyrics (palette sampled from the still)

Optional lyrics sheet: on-screen spelling comes from your `.txt`; clocks come from ASR. Tags like `[verse]` / `[chorus]` are ignored.

## Requires

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`
- `pip install -r requirements.txt` (first Whisper run downloads the model)

NVENC is used when available; otherwise libx264. CPU int8 Whisper is the default (no GPU required).

## Install

```bash
git clone https://github.com/glarsson/faded-lyrics.git
cd faded-lyrics
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Usage

```bash
python -m faded_lyrics --picture bg.png --audio track.mp3
python -m faded_lyrics --picture bg.png --audio track.wav --lyrics sheet.txt
python -m faded_lyrics --picture bg.png --audio track.wav --aspect 16:9 --out-dir ./out
```

Windows wrapper:

```powershell
.\run_eq_with_lyrics.ps1 bg.png track.mp3
.\run_eq_with_lyrics.ps1 bg.png track.wav lyrics.txt -CopyTo D:\Downloads
```

Unix wrapper:

```bash
chmod +x run_eq_with_lyrics.sh
./run_eq_with_lyrics.sh bg.png track.mp3
./run_eq_with_lyrics.sh --picture bg.png --audio track.wav --lyrics sheet.txt
```

Defaults: 1920x1080 / 16:9 / 30 fps / viz strip 16% of height / margin 0.40 / word fade 420 ms.

Artifacts land under `./out/<slug>/`:

- `lyrics.json` - Whisper segments + word stamps
- `lyrics.ass` / `lyrics.srt` - burned / sidecar captions
- `final_lyrics.mp4` - the deliverable

## Lyrics sheet tips

- Prefer ASCII; UTF-8 is fine for letters Whisper can hear
- One display line per line of text
- `[intro]`, `[verse]`, `[chorus]` lines are skipped
- Without a sheet, ASR words are packed into short on-screen lines

## License

MIT
