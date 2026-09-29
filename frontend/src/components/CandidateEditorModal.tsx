import { useEffect, useMemo, useState } from 'react';
import { getEditorState, getSettings, resolveMediaUrl, saveEditorState } from '../api/client';
import type { Candidate, CaptionSegmentEdit, CandidateEditorState, ProjectEditorState, Settings } from '../api/types';
import { formatClock, formatDuration } from '../lib/format';
import { Button, Card } from './ui';

type CaptionRow = CaptionSegmentEdit;

function formatInputValue(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : '';
}

function parseInputValue(value: string) {
  if (!value.trim()) {
    return Number.NaN;
  }
  return Number(value);
}

function isFiniteNumber(value: number) {
  return Number.isFinite(value) && !Number.isNaN(value);
}

function cloneRows(rows: CaptionRow[]): CaptionRow[] {
  return rows.map((row) => ({ ...row }));
}

function overlaps(row: CaptionRow, start: number, end: number) {
  return row.end > start && row.start < end;
}

function buildDefaultCandidateState(candidate: Candidate): CandidateEditorState {
  return {
    trim: { start: candidate.trim_start ?? candidate.start, end: candidate.trim_end ?? candidate.end },
    caption_segments: [],
    render_settings: {
      output_width: null,
      output_height: null,
      fps: null,
      captions_enabled: true,
      normalize_audio: true,
    },
    selected: false,
  };
}

type CandidateEditorModalProps = {
  videoId: string;
  candidate: Candidate | null;
  previewUrl?: string | null;
  transcriptUrl?: string | null;
  sourceDuration?: number | null;
  onClose: () => void;
  onSavedTrim: (candidate: Candidate, start: number, end: number) => void;
  onRender: (candidate: Candidate, start: number, end: number, state: CandidateEditorState) => Promise<void>;
};

export function CandidateEditorModal(props: CandidateEditorModalProps) {
  if (!props.candidate) {
    return null;
  }
  return <CandidateEditorModalContent {...props} candidate={props.candidate} />;
}

function CandidateEditorModalContent({
  videoId,
  candidate,
  previewUrl,
  transcriptUrl,
  sourceDuration,
  onClose,
  onSavedTrim,
  onRender,
}: CandidateEditorModalProps & { candidate: Candidate }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [editorState, setEditorState] = useState<ProjectEditorState | null>(null);
  const [baseSegments, setBaseSegments] = useState<CaptionRow[]>([]);
  const [startText, setStartText] = useState('');
  const [endText, setEndText] = useState('');
  const [playbackTime, setPlaybackTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<'save' | 'render' | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [loadingState, setLoadingState] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getSettings()
      .then((response) => {
        if (active) {
          setSettings(response);
          setSettingsError(null);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setSettingsError(cause instanceof Error ? cause.message : 'Unable to load trim settings.');
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const selectedCandidate = candidate;
    if (!selectedCandidate) {
      return;
    }
    let active = true;
    setLoadingState(true);
    setLoadError(null);
    setMediaError(null);
    setSaveMessage(null);
    Promise.all([
      getEditorState(videoId).catch(() => ({ video_id: videoId, candidates: {} as Record<string, CandidateEditorState> } as ProjectEditorState)),
      transcriptUrl ? fetch(resolveMediaUrl(transcriptUrl) ?? transcriptUrl).then((response) => response.json()) : Promise.resolve(null),
    ])
      .then(([state, transcript]) => {
        if (!active) {
          return;
        }
        const currentCandidateState = state.candidates[String(selectedCandidate.id)] ?? buildDefaultCandidateState(selectedCandidate);
        const trim = currentCandidateState.trim ?? { start: selectedCandidate.start, end: selectedCandidate.end };
        setEditorState(state);
        setStartText(formatInputValue(trim.start));
        setEndText(formatInputValue(trim.end));
        setPlaybackTime(trim.start);
        const transcriptSegments = Array.isArray(transcript?.segments)
          ? transcript.segments
              .map((segment: { start: unknown; end: unknown; text: unknown }) => ({
                start: Number(segment.start),
                end: Number(segment.end),
                text: String(segment.text ?? ''),
              }))
              .filter((segment: CaptionRow) => Number.isFinite(segment.start) && Number.isFinite(segment.end) && segment.text.trim())
          : [];
        setBaseSegments(transcriptSegments);
      })
      .catch((cause: unknown) => {
        if (active) {
          setLoadError(cause instanceof Error ? cause.message : 'Unable to load editor state.');
        }
      })
      .finally(() => {
        if (active) {
          setLoadingState(false);
        }
      });
    return () => {
      active = false;
    };
  }, [candidate, transcriptUrl, videoId]);

  const selectedCandidate = candidate;

  const start = parseInputValue(startText);
  const end = parseInputValue(endText);
  const clipDuration = isFiniteNumber(start) && isFiniteNumber(end) ? end - start : Number.NaN;
  const candidateState = editorState?.candidates[String(selectedCandidate.id)] ?? buildDefaultCandidateState(selectedCandidate);

  const validationErrors = useMemo(() => {
    const issues: string[] = [];
    const minimum = settings?.clip_min_seconds;
    const maximum = settings?.clip_max_seconds;

    if (!isFiniteNumber(start)) {
      issues.push('Start time must be a finite number.');
    }
    if (!isFiniteNumber(end)) {
      issues.push('End time must be a finite number.');
    }
    if (isFiniteNumber(start) && start < 0) {
      issues.push('Start time must be at least 0 seconds.');
    }
    if (isFiniteNumber(start) && isFiniteNumber(end) && end <= start) {
      issues.push('End time must be greater than start time.');
    }
    if (isFiniteNumber(end) && sourceDuration != null && end > sourceDuration) {
      issues.push(`End time cannot exceed the source duration (${formatDuration(sourceDuration)}).`);
    }
    if (isFiniteNumber(clipDuration) && minimum != null && clipDuration < minimum) {
      issues.push(`Clip duration must be at least ${formatDuration(minimum)}.`);
    }
    if (isFiniteNumber(clipDuration) && maximum != null && clipDuration > maximum) {
      issues.push(`Clip duration must be no longer than ${formatDuration(maximum)}.`);
    }
    return issues;
  }, [clipDuration, end, settings?.clip_max_seconds, settings?.clip_min_seconds, sourceDuration, start]);

  const resolvedPreviewUrl = resolveMediaUrl(previewUrl);
  const currentSegments = useMemo(() => {
    const visible = baseSegments.filter((segment) => overlaps(segment, isFiniteNumber(start) ? start : 0, isFiniteNumber(end) ? end : Number.POSITIVE_INFINITY));
    const savedSegments = candidateState.caption_segments.length ? candidateState.caption_segments : visible;
    return cloneRows(savedSegments.filter((segment) => overlaps(segment, isFiniteNumber(start) ? start : 0, isFiniteNumber(end) ? end : Number.POSITIVE_INFINITY)));
  }, [baseSegments, candidateState.caption_segments, end, start]);
  const activeCaption = useMemo(() => {
    const matching = currentSegments.find((segment) => playbackTime >= segment.start && playbackTime <= segment.end);
    return matching?.text ?? '';
  }, [currentSegments, playbackTime]);
  const renderSnapshot: CandidateEditorState = {
    trim: isFiniteNumber(start) && isFiniteNumber(end) ? { start, end } : candidateState.trim,
    caption_segments: currentSegments,
    render_settings: candidateState.render_settings,
    selected: candidateState.selected,
  };

  async function handlePlayPause() {
    const video = document.querySelector<HTMLVideoElement>('video[data-candidate-editor-video="true"]');
    if (!video) {
      return;
    }
    if (video.paused) {
      try {
        await video.play();
      } catch {
        setMediaError('The browser blocked playback. You can still adjust and render the clip.');
      }
      return;
    }
    video.pause();
  }

  function updateCaption(index: number, patch: Partial<CaptionRow>) {
    setEditorState((current) => {
      if (!current) {
        return current;
      }
      const key = String(selectedCandidate.id);
      const candidateEntry = current.candidates[key] ?? buildDefaultCandidateState(selectedCandidate);
      const nextSegments = cloneRows(currentSegments);
      nextSegments[index] = { ...nextSegments[index], ...patch };
      return {
        ...current,
        candidates: {
          ...current.candidates,
          [key]: {
            ...candidateEntry,
            trim: { start: isFiniteNumber(start) ? start : candidateEntry.trim?.start ?? selectedCandidate.start, end: isFiniteNumber(end) ? end : candidateEntry.trim?.end ?? selectedCandidate.end },
            caption_segments: nextSegments,
            render_settings: candidateEntry.render_settings,
            selected: candidateEntry.selected,
          },
        },
      };
    });
  }

  function setRenderSetting<Key extends keyof CandidateEditorState['render_settings']>(key: Key, value: CandidateEditorState['render_settings'][Key]) {
    setEditorState((current) => {
      if (!current) {
        return current;
      }
      const candidateKey = String(selectedCandidate.id);
      const candidateEntry = current.candidates[candidateKey] ?? buildDefaultCandidateState(selectedCandidate);
      return {
        ...current,
        candidates: {
          ...current.candidates,
          [candidateKey]: {
            ...candidateEntry,
            trim: candidateEntry.trim ?? { start: selectedCandidate.start, end: selectedCandidate.end },
            caption_segments: currentSegments,
            render_settings: {
              ...candidateEntry.render_settings,
              [key]: value,
            },
            selected: true,
          },
        },
      };
    });
  }

  async function persistEditorState() {
    if (!editorState) {
      return;
    }
    const nextState: ProjectEditorState = {
      video_id: videoId,
      selected_candidate_id: selectedCandidate.id,
      candidates: {
        ...editorState.candidates,
        [String(selectedCandidate.id)]: {
          ...renderSnapshot,
          selected: true,
        },
      },
    };
    await saveEditorState(videoId, nextState);
    setEditorState(nextState);
  }

  async function handleSave() {
    if (!settings || validationErrors.length || busyAction) {
      return;
    }
    setBusyAction('save');
    setSaveMessage(null);
    try {
      await persistEditorState();
      onSavedTrim(selectedCandidate, start, end);
      setSaveMessage('Editing state saved.');
    } catch (cause) {
      setSaveMessage(cause instanceof Error ? cause.message : 'Unable to save editing state.');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRender() {
    if (!settings || validationErrors.length || busyAction) {
      return;
    }
    setBusyAction('render');
    try {
      await onRender(selectedCandidate, start, end, renderSnapshot);
    } finally {
      setBusyAction(null);
    }
  }

  const selectedStart = isFiniteNumber(start) ? start : candidate.start;
  const selectedEnd = isFiniteNumber(end) ? end : candidate.end;
  const canSeek = isFiniteNumber(selectedStart) && isFiniteNumber(selectedEnd) && selectedEnd > selectedStart;
  const duration = canSeek && sourceDuration != null ? Math.max(sourceDuration, 0.001) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/90 p-4" onClick={onClose} role="presentation">
      <Card className="max-h-[92vh] w-full max-w-6xl overflow-auto" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="candidate-editor-title">
        <div className="grid gap-0 lg:grid-cols-[1.35fr_1fr]">
          <div className="border-b border-surface-700 bg-surface-950 lg:border-b-0 lg:border-r">
            <div className="p-4 space-y-4">
              <div className="rounded-2xl border border-surface-700 bg-surface-950 p-3">
                {resolvedPreviewUrl ? (
                  <div className="relative">
                    <video
                      data-candidate-editor-video="true"
                      src={resolvedPreviewUrl}
                      className="h-full w-full max-h-[52vh] bg-surface-950 object-contain"
                      preload="metadata"
                      onTimeUpdate={(event) => {
                        const video = event.currentTarget;
                        if (!canSeek) {
                          return;
                        }
                        if (video.currentTime >= selectedEnd) {
                          video.pause();
                          video.currentTime = selectedEnd;
                        } else if (video.currentTime < selectedStart) {
                          video.currentTime = selectedStart;
                        }
                        setPlaybackTime(video.currentTime);
                      }}
                      onSeeked={(event) => {
                        const video = event.currentTarget;
                        if (!canSeek) {
                          return;
                        }
                        if (video.currentTime < selectedStart) {
                          video.currentTime = selectedStart;
                        }
                        if (video.currentTime > selectedEnd) {
                          video.currentTime = selectedEnd;
                        }
                        setPlaybackTime(video.currentTime);
                      }}
                      onPlay={() => setIsPlaying(true)}
                      onPause={() => setIsPlaying(false)}
                      onError={() => setMediaError('This source video cannot be previewed in the browser, but trimming and rendering still work.')}
                    />
                    {activeCaption ? (
                      <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-4">
                        <div className="max-w-[90%] rounded-2xl border border-surface-600 bg-surface-900 px-4 py-3 text-center text-sm font-semibold leading-6 text-white shadow-subtle">
                          {activeCaption}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="flex min-h-[40vh] items-center justify-center p-6 text-center text-sm text-slate-500">
                    Preview unavailable for this source.
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <Button type="button" variant="secondary" onClick={() => { void handlePlayPause(); }} disabled={!resolvedPreviewUrl}>
                    {isPlaying ? 'Pause preview' : 'Play preview'}
                  </Button>
                  <div className="text-xs text-slate-400">{formatClock(playbackTime)} / {sourceDuration != null ? formatDuration(sourceDuration) : 'unknown source length'}</div>
                </div>
                <label className="space-y-2 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.22em] text-slate-500">Seek within selected interval</span>
                  <input
                    type="range"
                    min={canSeek ? selectedStart : 0}
                    max={canSeek ? selectedEnd : 0}
                    step="0.01"
                    value={Math.min(Math.max(playbackTime, canSeek ? selectedStart : 0), canSeek ? selectedEnd : 0)}
                    onChange={(event) => setPlaybackTime(Number(event.target.value))}
                    className="w-full"
                    aria-label="Seek within the selected trim interval"
                    disabled={!canSeek}
                  />
                </label>
                <div className="relative h-4 overflow-hidden rounded-full bg-surface-800" aria-hidden="true">
                  {duration && sourceDuration && sourceDuration > 0 ? (
                    <>
                      <div
                        className="absolute inset-y-0 bg-surface-700/60"
                        style={{ left: `${(candidate.start / sourceDuration) * 100}%`, width: `${Math.max(candidate.end - candidate.start, 0) / sourceDuration * 100}%` }}
                      />
                      <div
                        className="absolute inset-y-0 bg-accent-400/80"
                        style={{ left: `${(selectedStart / sourceDuration) * 100}%`, width: `${Math.max(selectedEnd - selectedStart, 0) / sourceDuration * 100}%` }}
                      />
                      {candidate.trigger_time != null ? (
                        <div className="absolute top-0 h-full w-1 bg-warning-500" style={{ left: `${Math.min(Math.max(candidate.trigger_time / sourceDuration, 0), 1) * 100}%` }} />
                      ) : null}
                    </>
                  ) : null}
                </div>
                <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-3">
                  <div>AI start: {formatClock(candidate.start)}</div>
                  <div>AI end: {formatClock(candidate.end)}</div>
                  <div>AI trigger: {candidate.trigger_time != null ? formatClock(candidate.trigger_time) : '—'}</div>
                </div>
              </div>

              {mediaError ? <p className="text-sm text-amber-200">{mediaError}</p> : null}
              {loadError ? <p className="text-sm text-rose-200">{loadError}</p> : null}
              {loadingState ? <p className="text-sm text-slate-400">Loading editor state...</p> : null}
            </div>
          </div>

          <div className="space-y-5 p-5">
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-slate-500">Candidate #{String(candidate.id).padStart(2, '0')}</div>
              <h3 id="candidate-editor-title" className="mt-2 text-2xl font-semibold text-white">Short editor</h3>
              <p className="mt-2 text-sm text-slate-400">
                Original AI boundaries stay unchanged. Save keeps a project-sidecar edit state; Render This Clip uses the current snapshot for just this job.
              </p>
            </div>

            <div className="grid gap-3 rounded-2xl border border-surface-700 bg-surface-800 p-4 text-sm text-slate-300 sm:grid-cols-2">
              <InfoRow label="Original start" value={formatClock(candidate.start)} />
              <InfoRow label="Original end" value={formatClock(candidate.end)} />
              <InfoRow label="Current start" value={Number.isFinite(start) ? formatClock(start) : '—'} />
              <InfoRow label="Current end" value={Number.isFinite(end) ? formatClock(end) : '—'} />
              <InfoRow label="Current duration" value={Number.isFinite(clipDuration) ? formatDuration(clipDuration) : '—'} />
              <InfoRow label="Source duration" value={sourceDuration != null ? formatDuration(sourceDuration) : 'Unknown'} />
            </div>

            <div className="space-y-3 rounded-2xl border border-surface-700 bg-surface-800 p-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-2 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.22em] text-slate-500">Start time (seconds)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={startText}
                    onChange={(event) => setStartText(event.target.value)}
                    className="w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100 outline-none transition focus:border-accent-400"
                    aria-describedby="trim-validation"
                  />
                </label>
                <label className="space-y-2 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.22em] text-slate-500">End time (seconds)</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={endText}
                    onChange={(event) => setEndText(event.target.value)}
                    className="w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100 outline-none transition focus:border-accent-400"
                    aria-describedby="trim-validation"
                  />
                </label>
              </div>

              <div className="flex flex-wrap gap-2 text-xs text-slate-400">
                {candidate.trim_saved ? <span className="rounded-full border border-success-500/30 bg-success-500/10 px-3 py-1 text-success-100">Saved override</span> : <span className="rounded-full border border-surface-600 bg-surface-800 px-3 py-1">Using AI-detected bounds</span>}
                {candidate.trigger_types.map((trigger) => (
                  <span key={trigger} className="rounded-full border border-surface-600 bg-surface-800 px-3 py-1 uppercase tracking-[0.18em] text-slate-300">
                    {trigger}
                  </span>
                ))}
              </div>

              <div className="space-y-2 text-sm text-slate-300">
                <div><span className="text-slate-500">Score:</span> {candidate.candidate_score}</div>
                <div><span className="text-slate-500">Audio:</span> {candidate.audio_level}</div>
                <div><span className="text-slate-500">End reason:</span> {candidate.end_reason ?? '—'}</div>
                <div><span className="text-slate-500">Keywords:</span> {candidate.matched_keywords.join(', ') || '—'}</div>
                <div><span className="text-slate-500">Transcript:</span> {candidate.transcript ?? '—'}</div>
              </div>
            </div>

            <div className="space-y-3 rounded-2xl border border-surface-700 bg-surface-800 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Caption editor</div>
                  <div className="mt-1 text-sm text-slate-400">Edit the transcript segments that overlap the selected trim.</div>
                </div>
                <div className="text-xs text-slate-500">{currentSegments.length} segment(s)</div>
              </div>
              <div className="space-y-3 max-h-64 overflow-auto pr-1">
                {currentSegments.length ? currentSegments.map((segment, index) => (
                  <div key={`${segment.start}-${segment.end}-${index}`} className="rounded-xl border border-surface-700 bg-surface-900 p-3">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <label className="space-y-1 text-xs text-slate-400">
                        <span className="uppercase tracking-[0.18em]">Start</span>
                        <input type="number" step="0.01" value={segment.start} onChange={(event) => updateCaption(index, { start: Number(event.target.value) })} className="w-full rounded-lg border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm text-slate-100" />
                      </label>
                      <label className="space-y-1 text-xs text-slate-400">
                        <span className="uppercase tracking-[0.18em]">End</span>
                        <input type="number" step="0.01" value={segment.end} onChange={(event) => updateCaption(index, { end: Number(event.target.value) })} className="w-full rounded-lg border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm text-slate-100" />
                      </label>
                    </div>
                    <label className="mt-2 block space-y-1 text-xs text-slate-400">
                      <span className="uppercase tracking-[0.18em]">Caption text</span>
                      <textarea value={segment.text} onChange={(event) => updateCaption(index, { text: event.target.value })} rows={2} className="w-full rounded-lg border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm leading-6 text-slate-100" />
                    </label>
                  </div>
                )) : <div className="rounded-xl border border-surface-700 bg-surface-800 p-3 text-sm text-slate-500">No overlapping transcript segments found for this trim.</div>}
              </div>
            </div>

            <div className="space-y-3 rounded-2xl border border-surface-700 bg-surface-800 p-4">
              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Render settings</div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.18em] text-slate-500">Output width</span>
                  <input type="number" step="1" min="1" value={candidateState.render_settings.output_width ?? settings?.output_width ?? 1080} onChange={(event) => setRenderSetting('output_width', Number(event.target.value))} className="w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100" />
                </label>
                <label className="space-y-1 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.18em] text-slate-500">Output height</span>
                  <input type="number" step="1" min="1" value={candidateState.render_settings.output_height ?? settings?.output_height ?? 1920} onChange={(event) => setRenderSetting('output_height', Number(event.target.value))} className="w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100" />
                </label>
                <label className="space-y-1 text-sm text-slate-300">
                  <span className="block text-xs uppercase tracking-[0.18em] text-slate-500">Frame rate</span>
                  <input type="number" step="0.1" min="1" value={candidateState.render_settings.fps ?? settings?.fps ?? 30} onChange={(event) => setRenderSetting('fps', Number(event.target.value))} className="w-full rounded-xl border border-surface-600 bg-surface-900 px-3 py-2 text-slate-100" />
                </label>
                <label className="flex items-center gap-3 rounded-xl border border-surface-700 bg-surface-900 px-3 py-2 text-sm text-slate-300">
                  <input type="checkbox" checked={candidateState.render_settings.captions_enabled ?? true} onChange={(event) => setRenderSetting('captions_enabled', event.target.checked)} className="h-4 w-4 rounded border-surface-600 bg-surface-900 text-accent-500" />
                  Captions enabled
                </label>
                <label className="flex items-center gap-3 rounded-xl border border-surface-700 bg-surface-900 px-3 py-2 text-sm text-slate-300">
                  <input type="checkbox" checked={candidateState.render_settings.normalize_audio ?? settings?.normalize_audio ?? true} onChange={(event) => setRenderSetting('normalize_audio', event.target.checked)} className="h-4 w-4 rounded border-surface-600 bg-surface-900 text-accent-500" />
                  Normalize audio
                </label>
              </div>
              <div className="rounded-xl border border-surface-700 bg-surface-900 p-3 text-sm text-slate-300">
                <div className="font-semibold text-white">Render summary</div>
                <div className="mt-2 grid gap-1 text-sm text-slate-300">
                  <div>Candidate: #{String(candidate.id).padStart(2, '0')}</div>
                  <div>Selected: {formatClock(selectedStart)} → {formatClock(selectedEnd)}</div>
                  <div>Duration: {Number.isFinite(clipDuration) ? formatDuration(clipDuration) : '—'}</div>
                  <div>Output: {(candidateState.render_settings.output_width ?? settings?.output_width ?? 1080)} × {(candidateState.render_settings.output_height ?? settings?.output_height ?? 1920)} @ {(candidateState.render_settings.fps ?? settings?.fps ?? 30)}</div>
                  <div>Captions: {(candidateState.render_settings.captions_enabled ?? true) ? 'Enabled' : 'Disabled'}</div>
                  <div>Audio normalization: {(candidateState.render_settings.normalize_audio ?? settings?.normalize_audio ?? true) ? 'On' : 'Off'}</div>
                </div>
              </div>
            </div>

            <div id="trim-validation" className="space-y-2" aria-live="polite">
              {settingsError ? <p className="text-sm text-danger-100">{settingsError}</p> : null}
              {validationErrors.map((error) => (
                <p key={error} className="text-sm text-danger-100">{error}</p>
              ))}
              {saveMessage ? <p className="text-sm text-success-100">{saveMessage}</p> : null}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" onClick={() => {
                const resetStart = candidate.start;
                const resetEnd = candidate.end;
                setStartText(formatInputValue(resetStart));
                setEndText(formatInputValue(resetEnd));
                setPlaybackTime(resetStart);
                setEditorState((current) => {
                  if (!current) {
                    return current;
                  }
                  return {
                    ...current,
                    candidates: {
                      ...current.candidates,
                      [String(candidate.id)]: {
                        ...(current.candidates[String(candidate.id)] ?? buildDefaultCandidateState(candidate)),
                        trim: { start: resetStart, end: resetEnd },
                      },
                    },
                  };
                });
                setMediaError(null);
              }}>
                Reset to AI boundaries
              </Button>
              <Button type="button" variant="secondary" onClick={onClose}>
                Cancel / Close
              </Button>
              <div className="flex-1" />
              <Button type="button" variant="secondary" onClick={() => { void handleSave(); }} disabled={!settings || validationErrors.length > 0 || busyAction === 'save'}>
                {busyAction === 'save' ? 'Saving...' : 'Save Trim'}
              </Button>
              <Button type="button" onClick={() => { void handleRender(); }} disabled={!settings || validationErrors.length > 0 || busyAction === 'render'}>
                {busyAction === 'render' ? 'Rendering...' : 'Render This Clip'}
              </Button>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-1 font-semibold text-white">{value}</div>
    </div>
  );
}
