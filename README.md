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

All API routes except `/api/health`, `/api/auth/login`, and
`/api/auth/register` require the server-managed session. Passwords use
Argon2id-compatible `argon2-cffi` hashing; session cookies are HttpOnly and
only hashes of random session tokens are stored. State-changing browser
requests also require the session-bound CSRF token and an allowed Origin.

### Auto-Compilation

The authenticated project workspace can submit an ordered compilation with
`POST /api/projects/{video_id}/compilations`. The JSON body contains a
`segments` array (`candidate_id` and optional `start`/`end` overrides),
`max_total_duration_seconds`, and optional compatible `render_settings`.
Array order is preserved exactly; moments are joined with hard cuts. When the
total exceeds the preferred maximum, only the final moment may be shortened,
and only when it remains at least the configured minimum clip duration.
Otherwise the request is rejected. Each trim must stay within its candidate
and source-video bounds, and duplicate candidate IDs are not supported.

Poll `GET /api/compilations/{compilation_id}` for job status, progress,
effective segment bounds and duration, and the output artifact URL after
completion. The output is registered in the project's artifact metadata and
appears in the Library. In-flight jobs are marked interrupted after a backend
restart; they are not automatically resumed.

### Smart Editing

Render, batch, and compilation requests can optionally include a versioned
`editing` object (`schema_version: 1`). Omitting it preserves the existing
render path. It supports an opening hook, up to 12 non-overlapping bounded
zoom intervals, an existing caption preset ID, and project-owned background
music. Hook and zoom times are relative to each final clip or compilation.
Zoom is applied to the rendered vertical frame, so already-burned captions
also move with the image during a zoom interval.

The project workspace's **Smart Editing** section exposes these settings.
Authenticated clients can also upload and list project music with
`POST /api/projects/{video_id}/music` (multipart field `file`) and
`GET /api/projects/{video_id}/music`. Uploads are limited to 50 MiB and 30
minutes, accept MP3, WAV, AAC, M4A, OGG, or FLAC, and are stored under a
generated project-scoped key. The client selects an asset by its returned
`asset_id`; storage keys and local paths are never accepted from requests.
Music may loop, fade in/out, and use predictable audio-activity ducking:
original audio is retained while it controls compression of the music. This
is not speech recognition. When the source has no audio, selected music is
the output audio track; without music, the output remains silent.

Compilations remain hard cuts by default. Setting
`editing.transition` to `crossfade` enables bounded video/audio overlap at
each segment boundary; the overlap is deducted from the reported effective
duration and preferred-duration calculation. Segment order is unchanged.
Transition effects are compilation-only, while hooks, zoom, caption presets,
and music are available on individual renders, batch children, and
compilations. Caption presets use the existing ASS generation path, keeping
source transcript cues relative to their trimmed segment. Hook text is
escaped into a generated ASS subtitle file rather than interpolated into an
FFmpeg filter expression.

Phase 1 stores users and sessions in PostgreSQL through SQLAlchemy 2.x and
Psycopg 3. The application uses the pooled `DATABASE_URL`; use the direct
`DATABASE_URL_UNPOOLED` for Alembic migrations. Email addresses are trimmed
and case-folded before storage, and duplicate registrations are rejected.
The existing filesystem owner data is not deleted or migrated automatically.

Create the first account once with:

```powershell
.\.venv\Scripts\python.exe scripts/create_admin.py
```

The command prompts for credentials and refuses to overwrite an existing
owner. Never put bootstrap credentials in tracked files.

To migrate the existing filesystem owner deliberately, first configure
`DATABASE_URL`, review the command, and run:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_owner.py
```

The command asks for a destination email and a new password, leaves
`processing/auth/users.json` and `sessions.json` untouched, and refuses to
overwrite a non-empty database. It does not migrate existing sessions.

### Database migrations

Use `DATABASE_URL` for application traffic and the direct
`DATABASE_URL_UNPOOLED` for schema changes. Review the SQL before applying it:

```powershell
$env:DATABASE_URL = $env:DATABASE_URL_UNPOOLED
.\.venv\Scripts\alembic.exe upgrade head --sql > migration.sql
Get-Content migration.sql
.\.venv\Scripts\alembic.exe upgrade head
```

Do not run the final command against production until the generated migration
has been reviewed and the rollout has been approved. `neon deploy` provisions
Neon services but does not create these application tables.

For local development, copy `.env.example` to an ignored `.env.local`, replace
only the placeholders with local or Neon values, then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
cd frontend
npm run dev
```

The backend loads `.env.local` automatically without overriding environment
variables supplied by the deployment or shell.

If YouTube blocks extraction, the Analyze page also accepts direct video
uploads (`.mp4`, `.mkv`, `.mov`, `.webm`, `.m4v`, or `.avi`). Set
`MAX_UPLOAD_BYTES` to cap uploads (20 GiB by default). In local development,
uploads use the authenticated FastAPI multipart endpoint and are streamed to
temporary disk. In production, the frontend disables video upload unless
`STORAGE_BACKEND=r2` is enabled: the browser obtains a short-lived upload
authorization from FastAPI and sends video bytes directly to the private R2
bucket, bypassing Vercel and Render request-body limits. Large files use
retryable multipart uploads. Successful uploads are size-verified in R2 and
then start the existing analysis job; the worker downloads the source to
temporary storage only for transcription and clip detection.

Set these Render environment variables for R2 direct uploads:

| Variable | Required/default | Purpose |
| --- | --- | --- |
| `STORAGE_BACKEND` | `r2` | Select the existing R2 storage adapter. |
| `MAX_UPLOAD_BYTES` | `21474836480` (20 GiB) | Maximum authorized file size. |
| `R2_ACCOUNT_ID` | Required | Cloudflare account identifier. |
| `R2_BUCKET_NAME` | Required | Private R2 bucket name. |
| `R2_ACCESS_KEY_ID` | Required | R2 S3-compatible access key ID. |
| `R2_SECRET_ACCESS_KEY` | Required | R2 S3-compatible secret key. |
| `R2_ENDPOINT_URL` | Required | `https://<account-id>.r2.cloudflarestorage.com`. |
| `R2_MULTIPART_THRESHOLD_BYTES` | `104857600` (100 MiB) | At/above this size, use multipart upload. |
| `R2_MULTIPART_PART_SIZE_BYTES` | `67108864` (64 MiB) | Multipart part size; must be 5 MiB–5 GiB. |
| `R2_UPLOAD_URL_TTL_SECONDS` | `300` | Presigned URL lifetime; allowed range 60–3600 seconds. |
| `R2_UPLOAD_SESSION_TTL_SECONDS` | `86400` (24 hours) | Incomplete upload session lifetime; allowed range 10 minutes–7 days and must exceed the URL lifetime by 60 seconds. |

Keep the bucket private and configure its **CORS** policy to allow `PUT` from
each exact frontend origin (for example, `https://<your-vercel-domain>` and
`http://localhost:5173` for local development), allow the `Content-Type`
request header, and expose the `ETag` response header. Multipart completion
depends on the browser reading each part's ETag. Configure the bucket's
multipart-upload lifecycle rule to abort incomplete multipart uploads after
one day. The application also sweeps expired upload sessions/objects on
startup and when a new upload is initialized.

Deployment steps:

1. Create a private R2 bucket and an R2 API token limited to that bucket's
   object read/write permissions; set the R2 variables above on Render.
2. Set `AUTH_ALLOWED_ORIGINS` to the exact deployed Vercel origin and retain
   the existing secure-cookie, database, and durable auth settings.
3. Add the matching bucket CORS rule (and incomplete-multipart lifecycle
   rule), then deploy the backend and frontend. Existing Vercel `/api/*`
   rewrites carry only small authenticated control requests; video bytes are
   sent to R2, never retried through the backend if direct upload fails.
4. In the deployed app, confirm the upload panel says files upload directly
   to private R2 storage, upload a small and a multipart-sized test video,
   then confirm project analysis and a rendered clip work.

For local development, `STORAGE_BACKEND=local` continues to use the bounded
FastAPI multipart path. The browser obtains the current maximum and accepted
formats from the backend and reports progress, speed, and failures. To test
the real direct-R2 path locally, configure the R2 values and add the local
frontend origin to bucket CORS. R2 integration must be verified against an
actual bucket; mocked tests do not verify credentials, CORS, or provider
behavior.

#### Manual R2 verification

Use a non-production test account and a disposable source video after
configuring an actual private bucket:

1. Upload a small MP4. In browser developer tools, verify the authorization
   calls go to the app and the `PUT` containing the video bytes goes to the
   R2 S3 endpoint, with an `ETag` response header. Confirm progress reaches
   100%, the project enters its queued/running state, and analysis completes.
2. Upload a video larger than `R2_MULTIPART_THRESHOLD_BYTES`. Verify several
   numbered R2 part requests, visible byte/speed progress, successful retry
   after interrupting one failed part, and successful multipart completion.
3. Start another multipart upload and cancel it. Confirm the multipart
   upload no longer appears in the bucket's multipart-upload listing. For an
   expired-session check, use a short test-only
   `R2_UPLOAD_SESSION_TTL_SECONDS`, leave a transfer unfinished, restart the
   backend or initialize another upload after expiry, and confirm its
   pending object/session is removed.
4. Try an unsupported extension and a file above `MAX_UPLOAD_BYTES`; both
   must be rejected before a browser-to-R2 transfer begins. Temporarily
   remove R2 write permission and confirm the app reports an authorization
   or storage error without sending the video to FastAPI.
5. Open the completed project, review candidates/transcript/captions, render
   a clip, and confirm the source and generated output remain available from
   the private bucket after a backend restart.

Render must provide `DATABASE_URL`, `AUTH_SESSION_TTL_SECONDS`,
`AUTH_COOKIE_NAME`, `AUTH_COOKIE_SECURE=true`, `AUTH_ALLOWED_ORIGINS` with the
exact Vercel origin, `APP_ENV=production`, and a durable private
`AUTH_DATA_DIR` until filesystem project state is migrated. Keep the existing
R2 variables unchanged.

Authentication is separate from authorization. Phase 1 supports multiple
database users and sessions, but the existing project, render/job, and
storage endpoints still read filesystem or in-memory state. They are
protected by authentication but are not yet ownership-filtered by database
user. Do not claim project, job, or asset ownership enforcement is complete
until those endpoints are migrated to the Phase 1 tables.

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

All YouTube entry points use `scripts/youtube.py`: `POST /api/videos/analyze`,
`scripts/detect_clips.py --url`, and `scripts/batch_process.py --url`. The
downloader enables Node through `js_runtimes`, selects an MP4-compatible source
up to 1080p, disables playlists, and uses a 20-second socket timeout. yt-dlp's
internal request, fragment, extractor, and file-access retries are disabled so
the application owns one predictable policy:

- Transient network failures receive at most three total attempts. Delays are
  exponential with bounded jitter: 1.0-1.5 seconds, then 2.0-2.5 seconds.
- HTTP 429 stops immediately and applies a five-minute source cooldown.
- A confirmed sign-in/bot challenge or terminal missing Visitor Data/GVS
  PO-token error stops immediately and applies a 15-minute source cooldown.
- Cooldown details are stored with the failed project/job metadata. API retries
  during that window return HTTP 429 with `Retry-After`; a valid cached source
  remains usable without contacting YouTube.
- Concurrent extraction of the same video is rejected in-process, and queued
  or running analysis metadata suppresses duplicate API submissions.

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
   Reinstall `requirements.txt` after downloader updates so yt-dlp's EJS and
   `curl_cffi` extras remain available, and rebuild/redeploy the Docker service
   after dependency changes. Retry with `--force-download` if a cached source
   is incomplete. HTTP 429, missing Visitor Data, and sign-in verification can
   still be imposed by YouTube on a server IP; use the direct Upload video
   workflow rather than supplying browser cookies, credentials, or tokens.

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

The container also includes Node.js 22 and installs
`yt-dlp[default,curl-cffi]` with its YouTube JavaScript challenge scripts and
the supported curl impersonation backend. Rebuild and redeploy the Docker
service after updating this configuration. This supplies yt-dlp's documented
runtime requirements but does not guarantee that YouTube will permit downloads
from Render's IP address; bot-verification failures are reported as failed
analysis jobs rather than continuing to appear in progress.

### Optional PO-token provider assessment (not enabled)

The official [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
recommends a provider plugin when a selected YouTube client requires a
Proof-of-Origin token. The featured
[`bgutil-ytdlp-pot-provider`](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
can run an HTTP provider, but this repository does not install, configure, or
start it. Enabling it would require an explicit deployment decision and all of
the following:

1. Deploy `brainicism/bgutil-ytdlp-pot-provider:<version>` as a separate Render
   **Private Service** in the same workspace and region as the backend. Keep
   port 4416 private; never expose it publicly. Render does not run Docker
   Compose, so this cannot be an implicit sidecar in the existing web service.
2. Set the provider health check to `GET /ping`. This endpoint returns provider
   uptime and version; treating it as Render's health check is an architectural
   recommendation based on the provider source, not a provider-documented
   Render recipe.
3. Add the matching `bgutil-ytdlp-pot-provider==<version>` Python plugin to the
   backend image. The provider image and Python plugin must be upgraded
   together and kept compatible with yt-dlp.
4. Add an opt-in backend setting such as
   `YOUTUBE_POT_PROVIDER_URL=http://<render-private-host>:4416`. The proposed
   Python yt-dlp configuration would be:

   ```python
   "extractor_args": {
       "youtubepot-bgutilhttp": {
           "base_url": ["http://<render-private-host>:4416"],
       },
       "youtube": {"player_client": ["mweb"]},
   }
   ```

   The equivalent documented CLI provider argument is
   `--extractor-args "youtubepot-bgutilhttp:base_url=http://<host>:4416"`.
   None of these settings are currently accepted or activated by the app.

The HTTP provider has no documented API-key authentication. Its own
documentation warns that exposing it beyond a trusted interface can permit
untrusted token generation, resource exhaustion, and potentially remote code
execution; Render's private network would therefore be the primary access
control. Node 22 or Deno 2 is required by the provider, and its BotGuard logic
is an ongoing maintenance dependency that can change as YouTube changes.

A PO token does not guarantee successful extraction, does not bypass an
IP-based “Sign in to confirm you're not a bot” restriction, and is especially
unlikely to resolve every failure from a datacenter IP. Manual/fabricated
Visitor Data, static PO tokens, browser cookies, proxy rotation, CAPTCHA
automation, and account/session collection remain deliberately unsupported.
Direct upload is the supported fallback for authorized media.

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
