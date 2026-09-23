# Gaming Shorts Generator (V2)

A local, free, Python-based pipeline that turns a gameplay video you own (or
have permission to reuse) into a polished 1080×1920 YouTube Short with
burned-in captions — no paid APIs, no cloud services, no database.

```
Authorized gameplay video
        ↓
Whisper transcription
        ↓
Manual timestamp selection
        ↓
Vertical conversion (center crop)
        ↓
Caption generation (burned-in .ass subtitles)
        ↓
Rendered 1080×1920 Short
```

V1 scope is intentionally limited to a manual pipeline. Automatic "viral
moment" detection is not attempted. V2 adds explainable candidate detection,
but candidates are only suggestions for human review. The system does not
claim that a clip is viral and does not upload or publish anything.

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (must include `ffmpeg` and `ffprobe`), available in PATH
- [OpenAI Whisper](https://github.com/openai/whisper) (installed via `requirements.txt`), running locally — no API key needed
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed via `requirements.txt`) for public YouTube source acquisition

### Installing FFmpeg on Windows

1. Download a build from https://www.gyan.dev/ffmpeg/builds/ (the "release essentials" zip is enough), or run `winget install ffmpeg` / `choco install ffmpeg` if you have winget/Chocolatey.
2. Extract it somewhere permanent, e.g. `C:\ffmpeg`.
3. Add `C:\ffmpeg\bin` to your `PATH` environment variable.
4. Open a **new** terminal and confirm with:
   ```
   ffmpeg -version
   ffprobe -version
   ```

If FFmpeg isn't found, both scripts will stop early with a clear error
telling you to install it.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The first time you run transcription, Whisper will download the selected
model (see `config/settings.json` → `whisper_model`) to a local cache
(`~/.cache/whisper` by default). This requires an internet connection once;
after that, transcription runs fully offline.

## Configuration

All tunable values live in [`config/settings.json`](config/settings.json):

| Key | Meaning |
|---|---|
| `output_width` / `output_height` | Output Short resolution (default 1080×1920) |
| `fps` | Output frame rate |
| `clip_min_seconds` / `clip_max_seconds` | Allowed clip duration range |
| `whisper_model` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| `video_codec` / `audio_codec` / `video_preset` / `video_crf` / `audio_bitrate` | FFmpeg encoding settings |
| `caption_*` | Font, size, colors, outline/shadow, wrapping, and vertical position of burned-in captions |
| `normalize_audio` | Whether to apply loudness normalization (`loudnorm`) |
| `reaction_keywords` | Case-insensitive transcript phrases used as reaction signals |
| `candidate_window_*` | Seconds before/after a signal and the gap used to merge nearby signals |
| `audio_*` | RMS window, rolling-baseline, local-spike threshold, and sample rate |
| `scene_*` | Low-resolution frame sampling and scene-change thresholds |
| `max_candidates` | Maximum number of ranked candidates saved |

## Usage

### 1. Add a video

Place a gameplay video you own/have rights to in `input/videos/` (e.g.
`input/videos/gameplay.mp4`).

### 2. Transcribe it

```powershell
python scripts/transcribe.py
```

This finds every video in `input/videos/`, extracts audio with FFmpeg,
runs local Whisper transcription, and saves a JSON transcript (with
timestamps) to `processing/temp/<video-name>.json`. Existing transcripts
are skipped unless you pass `--force`. You can also target one file:

```powershell
python scripts/transcribe.py --video input/videos/gameplay.mp4 --model small
```

### 3. Generate a Short from a clip

Pick a start/end timestamp (seconds, or `HH:MM:SS`) and run:

```powershell
python scripts/make_short.py --video input/videos/gameplay.mp4 --start 32 --end 47
```

This will:

1. Validate the video, timestamps, and clip duration against
   `clip_min_seconds` / `clip_max_seconds`.
2. Trim the requested section.
3. Center-crop it to a 9:16 region (no stretching) and scale to
   `output_width` × `output_height`.
4. Load the matching transcript, chunk it into short readable caption
   cues, and burn them in (unless `--no-captions` is passed).
5. Normalize audio (if enabled) and preserve the original gameplay audio.
6. Save the result to `output/shorts/` as `short_<date>_<NNN>.mp4`
   (never overwriting an existing file).
7. Verify the rendered file (exists, non-empty, correct resolution, has
   video/audio streams, duration in range) and report any problems.

See all options:

```powershell
python scripts/make_short.py --help
```

### 4. Detect candidate moments automatically (V2)

```powershell
python scripts/detect_clips.py --video input/videos/gameplay.mp4
```

Detection reuses `processing/temp/<video-name>.json` when it exists. If it is
missing, the command automatically invokes the existing local Whisper
transcription pipeline once. It then combines three simple, inspectable
signals:

1. Reaction phrases, emphasis, and short utterances in the transcript.
2. Short-window RMS audio peaks relative to a nearby rolling baseline, rather
   than the loudest portions of the whole video.
3. Low-resolution frame differences sampled periodically for lightweight scene
   changes.

Nearby triggers are merged into one candidate. Candidate windows respect
`clip_min_seconds` and `clip_max_seconds`. Results are ranked by a normalized
`candidate_score` from 0 to 100 and saved to
`processing/temp/<video-name>_candidates.json`.

The JSON includes start/end/duration, transcript text, matched keywords,
audio peak and relative peak, scene-change score, reaction detection, and the
component scores (`transcript_score`, `audio_score`, `scene_score`, and
`reaction_score`). Review candidates before passing their timestamps to
`make_short.py`.

Scene detection is intentionally only a supporting signal. Fast camera motion,
flashes, menus, and gameplay effects can produce false positives; it is not an
AI understanding model.

### 5. Analyze a YouTube URL

```powershell
python scripts/detect_clips.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
```

Also supported are `https://youtu.be/VIDEO_ID` and
`https://www.youtube.com/shorts/VIDEO_ID`. The URL must identify a public
YouTube video. Invalid URLs and videos that yt-dlp cannot access normally are
reported clearly; the downloader does not bypass authentication, DRM,
CAPTCHAs, paywalls, private/restricted access, or geographic restrictions.

yt-dlp downloads a reasonable MP4-compatible source to
`processing/temp/youtube/VIDEO_ID/`. A valid cached source is reused on later
runs; use `--force-download` to retry a download. The cache also stores the
transcript and candidate JSON, so repeated detection does not unnecessarily
retranscribe the same source. Downloads are retained by default for caching,
and only files created by this downloader are ever eligible for cleanup.

The detector remains the same V2 pipeline after acquisition: transcript,
audio, scene analysis, candidate generation, and explainable scoring.

### 6. Review and render selected candidates

```powershell
python scripts/batch_process.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --top 5
```

The interactive workflow displays candidates, asks for IDs, and asks for a
final confirmation before calling the existing `make_short.py` renderer. It
never renders every candidate automatically and never uploads or publishes.
Local videos are supported too:

```powershell
python scripts/batch_process.py --video input/videos/gameplay.mp4 --top 5
```

Only process videos you own or have permission/license to reuse.

## Project structure

```
gaming-shorts/
├── input/videos/         # Put your source gameplay videos here (gitignored)
├── output/shorts/        # Rendered Shorts land here (gitignored)
├── processing/audio/     # Extracted audio (gitignored)
├── processing/temp/      # Whisper transcripts + generated .ass subtitles (gitignored)
├── scripts/
│   ├── transcribe.py     # Video -> audio -> Whisper transcript JSON
│   ├── make_short.py     # Clip -> vertical crop -> captions -> rendered Short
│   ├── detect_clips.py   # Rank explainable candidate moments for review
│   ├── batch_process.py   # Download/detect/review selected candidates/render
│   ├── youtube.py         # YouTube URL validation, download, and cache only
│   ├── utils.py          # Shared config/ffmpeg/validation helpers
│   └── detectors/
│       ├── transcript.py # Reaction and transcript signals
│       ├── audio.py      # Local RMS baseline and spike signals
│       └── scenes.py     # Lightweight frame-difference signals
├── config/settings.json  # All tunable values
├── requirements.txt
└── tests/                # Unit tests for the non-media logic
```

## Testing

Pure-Python logic (timestamp/duration validation, filename generation,
config loading, transcript parsing, caption chunking, V2 signal detection,
audio RMS analysis, candidate merging, and scoring) is covered by unit tests:

```powershell
python -m unittest discover -v
```

The detector's scene and FFmpeg extraction path still require a real media
file and FFmpeg. Verify those paths with a real authorized gameplay video.

## Troubleshooting

- **"FFmpeg was not found"** — install FFmpeg and ensure `ffmpeg`/`ffprobe`
  are on PATH, then open a new terminal.
- **"The 'openai-whisper' package is not installed"** — run
  `pip install -r requirements.txt` inside your activated virtual
  environment.
- **"No transcript found..."** — run `scripts/transcribe.py` for that video
  first, or pass `--no-captions`.
- **Verification failures** — the error output lists exactly what didn't
  match (resolution, missing stream, duration, etc.) so you can inspect the
  file or rerun with different settings.
- **YouTube download failures** — confirm yt-dlp is installed, the video is
   public and normally accessible, and that you have permission to reuse it.
   Retry with `--force-download` if a cached source is incomplete.

## What's outside V2 scope

- YouTube uploading, API integration, or automatic publishing
- Claims that a candidate is "viral"
- Automatic title/thumbnail generation or posting schedules
- Cloud processing or paid AI APIs
- Sophisticated machine-learning video understanding
