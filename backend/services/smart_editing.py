from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

from backend.core import PROJECT_ROOT  # noqa: F401 - ensures scripts/ is on sys.path
from backend.schemas import EditingSettings
from scripts.make_short import escape_ffmpeg_path, write_hook_ass
from scripts.utils import get_media_info, run_subprocess


def apply_caption_preset(config: dict[str, Any], settings: EditingSettings | None) -> dict[str, Any]:
    if settings is None or settings.caption_preset_id is None:
        return config
    from backend.services.caption_preset_service import list_presets

    preset = next((item for item in list_presets() if item.id == settings.caption_preset_id), None)
    if preset is None:
        raise ValueError("The selected caption preset was not found.")
    merged = dict(config)
    preset_settings = preset.settings.model_dump(exclude_none=True)
    for key in (
        "caption_font_name",
        "caption_font_size",
        "caption_primary_color",
        "caption_outline_color",
        "caption_shadow_color",
        "caption_outline_width",
        "caption_shadow_depth",
        "caption_vertical_margin_percent",
        "caption_bold",
        "caption_animation",
        "caption_animation_duration",
        "caption_highlight_color",
    ):
        if key in preset_settings:
            merged[key] = preset_settings[key]
    return merged


def validate_editing_timing(settings: EditingSettings, duration_seconds: float) -> None:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("The output duration must be known before editing effects can be validated.")
    if settings.hook is not None:
        if settings.hook.start_seconds + settings.hook.duration_seconds > duration_seconds + 1e-6:
            raise ValueError("The hook must fit within the final output duration.")
    for interval in settings.zoom_intervals:
        if interval.end_seconds > duration_seconds + 1e-6:
            raise ValueError("Every zoom interval must fit within the final output duration.")
    if settings.music is not None:
        if settings.music.fade_in_seconds > duration_seconds or settings.music.fade_out_seconds > duration_seconds:
            raise ValueError("Music fades cannot be longer than the final output duration.")


def _hook_filter(settings: EditingSettings, ass_path: Path) -> str | None:
    hook = settings.hook
    if hook is None:
        return None
    return f"subtitles='{escape_ffmpeg_path(ass_path)}'"


def build_effect_command(
    input_path: Path,
    output_path: Path,
    *,
    settings: EditingSettings,
    duration_seconds: float,
    config: dict[str, Any],
    has_original_audio: bool,
    music_path: Path | None = None,
    hook_ass_path: Path | None = None,
) -> list[str]:
    if settings.music is not None and music_path is None:
        raise ValueError("The selected project music asset is unavailable.")
    video_filters: list[str] = []
    if settings.zoom_intervals:
        zoom_expression = "1"
        for interval in reversed(settings.zoom_intervals):
            zoom_expression = (
                f"if(between(on/{float(config.get('fps', 30)):g}\\,"
                f"{interval.start_seconds:.3f}\\,{interval.end_seconds:.3f})\\,"
                f"{interval.scale:.4f}\\,{zoom_expression})"
            )
        video_filters.append(
            "zoompan="
            f"z='{zoom_expression}':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
            f"s={int(config['output_width'])}x{int(config['output_height'])}:"
            f"fps={float(config.get('fps', 30)):g}"
        )
    hook_filter = _hook_filter(settings, hook_ass_path) if hook_ass_path is not None else None
    if hook_filter:
        video_filters.append(hook_filter)

    args = ["ffmpeg", "-y", "-i", str(input_path)]
    if settings.music is not None and music_path is not None:
        if settings.music.loop:
            args.extend(["-stream_loop", "-1"])
        args.extend(["-i", str(music_path)])

    has_video_effects = bool(video_filters)
    has_music = settings.music is not None
    if has_video_effects or has_music:
        filters: list[str] = []
        if video_filters:
            filters.append(f"[0:v:0]{','.join(video_filters)}[v]")
        video_map = "[v]" if video_filters else "0:v:0"

        if has_music and settings.music is not None:
            duration = f"{duration_seconds:.3f}"
            if has_original_audio:
                filters.append(
                    f"[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS[original]"
                )
            music_chain = (
                f"[1:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"atrim=duration={duration},asetpts=PTS-STARTPTS"
            )
            if settings.music.fade_in_seconds > 0:
                music_chain += f",afade=t=in:st=0:d={settings.music.fade_in_seconds:.3f}"
            if settings.music.fade_out_seconds > 0:
                music_chain += (
                    f",afade=t=out:st={max(0.0, duration_seconds - settings.music.fade_out_seconds):.3f}"
                    f":d={settings.music.fade_out_seconds:.3f}"
                )
            music_chain += ",apad,atrim=duration=" + duration
            if settings.music.duck_original_audio and has_original_audio:
                filters.append(music_chain + "[music_raw]")
                filters.append(
                    "[music_raw][original]sidechaincompress=threshold=0.04:ratio=8:"
                    "attack=20:release=250[ducked]"
                )
                music_input = "[ducked]"
            else:
                filters.append(music_chain + "[music_raw]")
                music_input = "[music_raw]"
            filters.append(f"{music_input}volume={settings.music.volume:.4f}[music]")
            if has_original_audio:
                filters.append(
                    "[original][music]amix=inputs=2:duration=first:dropout_transition=0:"
                    "normalize=0,alimiter=limit=0.95[a]"
                )
            else:
                filters.append("[music]alimiter=limit=0.95[a]")
            args.extend(["-filter_complex", ";".join(filters), "-map", video_map, "-map", "[a]"])
            args.extend(["-c:a", str(config.get("audio_codec", "aac")), "-b:a", str(config.get("audio_bitrate", "192k")), "-ar", "48000", "-ac", "2"])
            if not has_video_effects:
                args.extend(["-c:v", "copy"])
        else:
            args.extend(["-vf", ",".join(video_filters), "-map", "0:v:0", "-map", "0:a?"])
            args.extend(["-c:a", "copy"])

        if has_video_effects:
            args.extend([
                "-c:v", str(config.get("video_codec", "libx264")),
                "-preset", str(config.get("video_preset", "medium")),
                "-crf", str(config.get("video_crf", 20)),
                "-r", f"{float(config.get('fps', 30)):g}",
                "-pix_fmt", "yuv420p",
            ])
    else:
        raise ValueError("No smart-editing effects were selected.")

    args.extend(["-movflags", "+faststart", str(output_path)])
    return args


def apply_smart_effects(
    input_path: Path,
    *,
    settings: EditingSettings,
    duration_seconds: float,
    config: dict[str, Any],
    has_original_audio: bool,
    temp_dir: Path,
    music_path: Path | None = None,
) -> None:
    if settings.hook is None and not settings.zoom_intervals and settings.music is None:
        return
    validate_editing_timing(settings, duration_seconds)
    temp_dir.mkdir(parents=True, exist_ok=True)
    effect_output = input_path.with_name(f"{input_path.stem}.effects-{uuid.uuid4().hex}.mp4")
    hook_ass_path: Path | None = None
    try:
        if settings.hook is not None:
            hook_ass_path = temp_dir / f"hook-{uuid.uuid4().hex}.ass"
            hook = settings.hook
            write_hook_ass(
                text=hook.text,
                start=hook.start_seconds,
                end=hook.start_seconds + hook.duration_seconds,
                position=hook.position,
                font_size=hook.font_size,
                color=hook.color,
                outline_width=hook.outline_width,
                background_box=hook.background_box,
                background_color=hook.background_color,
                config=config,
                ass_path=hook_ass_path,
            )
        command = build_effect_command(
            input_path,
            effect_output,
            settings=settings,
            duration_seconds=duration_seconds,
            config=config,
            has_original_audio=has_original_audio,
            music_path=music_path,
            hook_ass_path=hook_ass_path,
        )
        run_subprocess(command, "Smart editing effects")
        if not effect_output.is_file() or effect_output.stat().st_size == 0:
            raise RuntimeError("Smart editing output is missing or empty.")
        info = get_media_info(effect_output)
        if not info.get("has_video"):
            raise RuntimeError("Smart editing output has no video stream.")
        if info.get("width") != config["output_width"] or info.get("height") != config["output_height"]:
            raise RuntimeError("Smart editing output dimensions do not match the configured vertical format.")
        actual_duration = info.get("duration")
        if actual_duration is None or not math.isfinite(float(actual_duration)):
            raise RuntimeError("Could not determine smart editing output duration.")
        if abs(float(actual_duration) - duration_seconds) > 1.5:
            raise RuntimeError("Smart editing output duration is outside the expected range.")
        if settings.music is not None and not info.get("has_audio"):
            raise RuntimeError("Smart editing output has no audio stream after music mixing.")
        effect_output.replace(input_path)
    finally:
        effect_output.unlink(missing_ok=True)
        if hook_ass_path is not None:
            hook_ass_path.unlink(missing_ok=True)


def build_audio_filter_description(
    settings: EditingSettings, duration_seconds: float, *, has_original_audio: bool
) -> str:
    if settings.music is None:
        raise ValueError("Music settings are required to build an audio filter.")
    duration = f"{duration_seconds:.3f}"
    chain = (
        f"[1:a:0]aresample=48000,atrim=duration={duration},asetpts=PTS-STARTPTS"
    )
    if settings.music.fade_in_seconds:
        chain += f",afade=t=in:st=0:d={settings.music.fade_in_seconds:.3f}"
    if settings.music.fade_out_seconds:
        chain += (
            f",afade=t=out:st={max(0.0, duration_seconds - settings.music.fade_out_seconds):.3f}"
            f":d={settings.music.fade_out_seconds:.3f}"
        )
    chain += f",volume={settings.music.volume:.4f}[music]"
    if settings.music.duck_original_audio and has_original_audio:
        chain += ";[music][0:a:0]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=250[ducked]"
    return chain
