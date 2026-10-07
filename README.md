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

## Web UI V1

ClippyRipoff now includes a local web UI that wraps the existing Python engine
instead of replacing it.

### Development commands

Recommended on Windows:

```powershell
.\start.ps1
```

The launcher starts the FastAPI backend in one PowerShell window, the Vite frontend in another, waits for both HTTP endpoints to respond, and then opens Firefox to `http://127.0.0.1:5173`.

If you want to run the services manually, use these commands from the repository root:

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Authentication

All API routes except `/api/health` and `/api/auth/login` require the
server-managed owner session. Passwords use Argon2id-compatible
`argon2-cffi` hashing; session cookies are HttpOnly and session tokens are
stored only as hashes. State-changing browser requests also require the
session-bound CSRF token and an allowed Origin.

Create the first account once with:

```powershell
python scripts/create_owner.py
```

The command prompts for credentials and refuses to overwrite an existing
owner. Never put bootstrap credentials in tracked files. Local development
uses `AUTH_DATA_DIR=processing/auth` and `AUTH_COOKIE_SECURE=false`.
Production must use HTTPS, set `AUTH_COOKIE_SECURE=true`, provide exact
`AUTH_ALLOWED_ORIGINS` values, and place `AUTH_DATA_DIR` on durable private
storage. The filesystem repository is replaceable; a database-backed
repository is still required before horizontal scaling or multi-user access.

Authentication is separate from authorization. This release has one owner, so
all authenticated projects are in the owner workspace. Before supporting
multiple users, persist project, render/job, and storage ownership IDs and
enforce them throughout project, render, library, settings, and media
services.

Terminal 2:

```powershell
cd frontend
npm run dev
```

The frontend runs at `http://127.0.0.1:5173` and the backend API runs at
`http://127.0.0.1:8000` by default. The frontend Vite config binds to
`127.0.0.1` directly, so no extra host flags are required.

If a clean checkout is missing dependencies, install them once with:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
```

Frontend dependencies (`node_modules/`) and generated production files
(`frontend/dist/`) are local build outputs and are not committed.

Troubleshooting:

- If the launcher reports that port 8000 or 5173 is already in use, stop the existing local server or close the old window before retrying.
- If the backend cannot import Uvicorn, confirm you are using the repo's `.venv` and reinstall `requirements.txt`.
- If the frontend does not open in Firefox, check whether `firefox.exe` is on PATH; the launcher falls back to the default browser if needed.

### Notes

- Analysis and rendering run in local background threads.
- Job status is persisted to disk, so completed, failed, and interrupted render jobs survive restarts.
- Jobs that were queued or running during a restart are restored as interrupted and can be retried from the queue.
- Source videos, transcripts, candidates, and rendered Shorts still live on the filesystem cache.
- Candidate cards now include a trim editor for manual start/end adjustments before rendering.
- Manual trims are stored in a project-only sidecar file and do not modify `candidates.json`.
- Render jobs can use either the saved trim or a one-off override from the editor; the chosen boundaries are kept with that render job, along with the render settings snapshot used for retries.

### API highlights

- `POST /api/videos/analyze`
- `GET /api/videos/{video_id}`
- `GET /api/videos/{video_id}/candidates`
- `PUT /api/videos/{video_id}/candidates/{candidate_id}/trim`
- `POST /api/videos/{video_id}/render`
- `GET /api/renders`
- `GET /api/library`
- `DELETE /api/library/{filename}`

### Manual trim workflow

Open a project on the Analysis page and click **Trim** on any candidate card. The editor shows the AI-detected boundaries, the current manual boundaries, candidate metadata, and a preview of the cached source video.

Use the start/end time fields to adjust the clip. The editor enforces the configured `clip_min_seconds` and `clip_max_seconds`, requires `end > start`, and rejects values outside the known source duration when that duration is available.

Click **Save Trim** to store the clip boundaries for that candidate in the current project only. Click **Render This Clip** to render immediately with the current boundaries without changing the detector output. Clicking **Reset to AI boundaries** restores the original candidate start/end.

The CLI scripts continue to work unchanged, including `python scripts/detect_clips.py --url "..." --top 10`.

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
| `candidate_window_*` / `context_*` | Signal context and the gap used to merge nearby signals |
| `boundary_continuation_gap_seconds` | Maximum speech gap treated as continuing setup or payoff |
| `boundary_quiet_seconds` | Maximum trailing context retained after a quiet boundary |
| `boundary_scene_transition_threshold` | Frame-difference score required to end after a completed payoff |
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
## Storage and deployment

For a Render deployment, create a **Docker** web service with the repository
root as its root directory and `Dockerfile` as its Dockerfile path. The
Dockerfile installs FFmpeg and the Python dependencies, and starts Uvicorn on
Render's `PORT`; leave the build and start commands unset. A native Python
service cannot use `apt-get` to install FFmpeg.

The backend uses private storage by default. Set `STORAGE_BACKEND=local` (or
leave it unset) for the existing filesystem workflow. For Render, set
`STORAGE_BACKEND=r2` and provide the R2 variables shown in
[.env.example](./.env.example). `R2_ENDPOINT_URL` must be the S3-compatible
endpoint for the account; credentials are read only from the environment.

Source videos and completed renders are transferred with streaming S3 APIs, not
loaded into memory. FFmpeg always works on seekable local files under
`TEMP_DIR`, which are safe to remove after a job finishes. Object access is
served through backend-controlled routes; the bucket must remain private.

For production, configure the Render service environment variables and a
persistent private R2 bucket. No Cloudflare, Render, or Vercel settings are
modified by this repository.
