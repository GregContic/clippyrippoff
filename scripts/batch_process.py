"""Interactive candidate-review workflow for local videos or YouTube URLs.

Nothing is rendered until the user selects candidate IDs and confirms.
Nothing is uploaded or published.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from detect_clips import detect_candidates, print_candidates
from make_short import main as render_short
from utils import ensure_directories, load_config, transcript_path_for_video
from youtube import YouTubeError, cache_paths, download_youtube_video


def _parse_ids(value: str, available: set[int]) -> list[int]:
    selected: list[int] = []
    for part in value.replace(",", " ").split():
        try:
            candidate_id = int(part)
        except ValueError:
            continue
        if candidate_id in available and candidate_id not in selected:
            selected.append(candidate_id)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download or open gameplay, find candidates, and interactively render selected Shorts.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", type=Path, default=None, help="Local gameplay video path.")
    parser.add_argument("--url", type=str, default=None, help="Public YouTube URL.")
    parser.add_argument("--top", type=int, default=10, help="Maximum candidates to display and select.")
    parser.add_argument("--force-download", action="store_true", help="Redownload a YouTube source even when cached.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_directories()
    if args.video is not None and args.url is not None:
        print("ERROR: Provide either --video or --url, not both.", file=sys.stderr)
        return 2
    if args.video is None and args.url is None:
        print("ERROR: Provide --video or --url.", file=sys.stderr)
        return 2
    if args.top < 1:
        print("ERROR: --top must be at least 1.", file=sys.stderr)
        return 2

    video_path = args.video
    transcript_path: Path | None = None
    if args.url:
        try:
            downloaded = download_youtube_video(args.url, force_download=args.force_download)
        except YouTubeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        video_path = Path(downloaded["filepath"])
        transcript_path = cache_paths(downloaded["video_id"])["transcript"]
    if video_path is None or not video_path.exists():
        print(f"Video not found: {video_path}", file=sys.stderr)
        return 1

    try:
        config = load_config()
        candidates = detect_candidates(video_path, config, transcript_path)
    except Exception as exc:
        print(f"Batch processing failed: {exc}", file=sys.stderr)
        return 1

    candidates = candidates[:args.top]
    print_candidates(candidates)
    if not candidates:
        return 0

    available = {candidate["id"] for candidate in candidates}
    print("\nSelect clips to render (IDs separated by spaces or commas; blank cancels):")
    selected = _parse_ids(input("> "), available)
    if not selected:
        print("No clips selected. Nothing was rendered.")
        return 0
    print(f"\nSelected: {', '.join(str(candidate_id) for candidate_id in selected)}")
    confirmation = input("Render these clips? [y/N]: ").strip().lower()
    if confirmation not in {"y", "yes"}:
        print("Rendering cancelled.")
        return 0

    candidate_by_id = {candidate["id"]: candidate for candidate in candidates}
    for candidate_id in selected:
        candidate = candidate_by_id[candidate_id]
        render_args = [
            "--video", str(video_path),
            "--start", str(candidate["start"]),
            "--end", str(candidate["end"]),
        ]
        if transcript_path is not None:
            render_args.extend(["--transcript", str(transcript_path)])
        result = render_short(render_args)
        if result != 0:
            print(f"Rendering stopped after candidate {candidate_id} failed.", file=sys.stderr)
            return result
    return 0


if __name__ == "__main__":
    sys.exit(main())
