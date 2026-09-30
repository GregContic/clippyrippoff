export interface AnalyzeResponse {
  video_id: string;
  status: string;
  job_id?: string | null;
  title?: string | null;
  analysis_stage?: string | null;
  message?: string | null;
  candidate_count: number;
  rendered_count: number;
}

export interface ProjectSummary {
  video_id: string;
  title?: string | null;
  url?: string | null;
  source_thumbnail_url?: string | null;
  status: string;
  analysis_stage?: string | null;
  message?: string | null;
  candidate_count: number;
  rendered_count: number;
  source_duration?: number | null;
  source_cache_status?: string | null;
  project_created_at?: string | null;
  last_analyzed_at?: string | null;
  latest_activity_at?: string | null;
  saved_editing_state?: boolean;
  manual_trim_count?: number;
  render_job_count?: number;
  queued_render_jobs?: number;
  running_render_jobs?: number;
  completed_render_jobs?: number;
  failed_render_jobs?: number;
  interrupted_render_jobs?: number;
  generated_output_count?: number;
  source_url?: string | null;
  source_video_url?: string | null;
  transcript_url?: string | null;
  candidates_url?: string | null;
  rendered_urls: string[];
  created_at?: string | null;
  updated_at?: string | null;
  analysis_job_id?: string | null;
}

export interface Candidate {
  id: number;
  start: number;
  end: number;
  duration: number;
  candidate_score: number;
  transcript?: string | null;
  signals: Record<string, number>;
  audio_peak: number;
  relative_audio_peak: number;
  audio_level: string;
  reaction_detected: boolean;
  matched_keywords: string[];
  scene_change_score: number;
  trigger_time?: number | null;
  trigger_types: string[];
  start_reason?: string | null;
  end_reason?: string | null;
  setup_seconds?: number | null;
  payoff_seconds?: number | null;
  preview_url?: string | null;
  trim_start?: number | null;
  trim_end?: number | null;
  trim_saved?: boolean;
}

export interface CaptionSegmentEdit {
  start: number;
  end: number;
  text: string;
}

export interface RenderSettings {
  output_width?: number | null;
  output_height?: number | null;
  fps?: number | null;
  captions_enabled?: boolean | null;
  normalize_audio?: boolean | null;
  caption_font_name?: string | null;
  caption_font_size?: number | null;
  caption_primary_color?: string | null;
  caption_outline_color?: string | null;
  caption_shadow_color?: string | null;
  caption_outline_width?: number | null;
  caption_shadow_depth?: number | null;
  caption_vertical_margin_percent?: number | null;
  caption_bold?: boolean | null;
  caption_preset_id?: string | null;
  caption_animation?: 'none' | 'pop' | 'karaoke' | 'fade' | null;
  caption_animation_duration?: number | null;
  caption_highlight_color?: string | null;
}

export interface CandidateEditorState {
  trim?: { start: number; end: number } | null;
  caption_segments: CaptionSegmentEdit[];
  render_settings: RenderSettings;
  selected: boolean;
}

export interface ProjectEditorState {
  video_id: string;
  selected_candidate_id?: number | null;
  candidates: Record<string, CandidateEditorState>;
}

export interface CandidateListResponse {
  video_id: string;
  source_duration?: number | null;
  candidates: Candidate[];
  candidate_count: number;
}

export interface RenderJob {
  id: string;
  kind: string;
  video_id?: string | null;
  candidate_id?: number | null;
  retry_of?: string | null;
  status: string;
  stage?: string | null;
  message?: string | null;
  percent?: number | null;
  error?: string | null;
  output_path?: string | null;
  output_url?: string | null;
  result?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  review_status: 'pending_review' | 'approved' | 'needs_changes';
  review_notes: string;
}

export interface CaptionPreset {
  id: string;
  name: string;
  built_in: boolean;
  version: number;
  settings: RenderSettings;
}

export interface LibraryItem {
  filename: string;
  url: string;
  size_bytes: number;
  created_at?: string | null;
  duration?: number | null;
  review_status?: 'pending_review' | 'approved' | 'needs_changes';
  render_job_id?: string | null;
}

export interface LibraryResponse {
  items: LibraryItem[];
}

export interface ProjectFileItem {
  filename: string;
  url: string;
  size_bytes: number;
  created_at?: string | null;
  duration?: number | null;
  candidate_id?: number | null;
  render_job_id?: string | null;
}

export interface ProjectFilesResponse {
  items: ProjectFileItem[];
}

export interface Settings {
  whisper_model: string;
  clip_min_seconds: number;
  clip_max_seconds: number;
  max_candidates: number;
  context_before_seconds?: number | null;
  context_after_seconds?: number | null;
  candidate_merge_gap_seconds?: number | null;
  boundary_continuation_gap_seconds?: number | null;
  boundary_quiet_seconds?: number | null;
  boundary_scene_transition_threshold?: number | null;
  output_width?: number | null;
  output_height?: number | null;
  fps?: number | null;
  normalize_audio?: boolean | null;
}

export interface RenderResponse {
  video_id: string;
  render_job_ids: string[];
}

export interface TrimOverride {
  start: number;
  end: number;
}
