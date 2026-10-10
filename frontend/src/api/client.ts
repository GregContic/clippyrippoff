import type {
  AnalyzeResponse,
  CaptionPreset,
  CandidateEditorState,
  CandidateListResponse,
  LibraryResponse,
  ProjectFilesResponse,
  ProjectEditorState,
  ProjectSummary,
  RenderJob,
  RenderResponse,
  TrimOverride,
  Settings,
} from './types';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? window.location.origin : 'http://127.0.0.1:8000');
export type AuthUser = { id: string; username: string };

export function resolveMediaUrl(path?: string | null): string | null {
  if (!path) {
    return null;
  }
  return new URL(path, API_BASE_URL).toString();
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const csrfToken = document.cookie.split('; ').find((item) => item.startsWith('clippy_csrf='))?.split('=').slice(1).join('=');
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-CSRF-Token': decodeURIComponent(csrfToken) } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login') {
      window.dispatchEvent(new Event('clippy:unauthorized'));
    }
    let message = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      message = parsed.detail ?? message;
    } catch {
      // Ignore JSON parse errors and surface the raw message.
    }

    throw new Error(message || `Request failed with status ${response.status}`);
  }

  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

export function login(username: string, password: string): Promise<{ user: AuthUser }> {
  return requestJson<{ user: AuthUser }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
}

export function register(email: string, password: string): Promise<{ user: AuthUser }> {
  return requestJson<{ user: AuthUser }>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) });
}

export function logout(): Promise<void> {
  return requestJson<void>('/api/auth/logout', { method: 'POST' });
}

export function getCurrentUser(): Promise<{ user: AuthUser }> {
  return requestJson<{ user: AuthUser }>('/api/auth/me');
}

export function analyzeVideo(url: string, forceDownload = false): Promise<AnalyzeResponse> {
  return requestJson<AnalyzeResponse>('/api/videos/analyze', {
    method: 'POST',
    body: JSON.stringify({ url, force_download: forceDownload }),
  });
}

export function listVideos(): Promise<{ items: ProjectSummary[] }> {
  return requestJson<{ items: ProjectSummary[] }>('/api/videos');
}

export function listProjects(): Promise<{ items: ProjectSummary[] }> {
  return requestJson<{ items: ProjectSummary[] }>('/api/projects');
}

export function getVideo(videoId: string): Promise<ProjectSummary> {
  return requestJson<ProjectSummary>(`/api/videos/${encodeURIComponent(videoId)}`);
}

export function getProject(videoId: string): Promise<ProjectSummary> {
  return requestJson<ProjectSummary>(`/api/projects/${encodeURIComponent(videoId)}`);
}

export function getProjectSummary(videoId: string): Promise<ProjectSummary> {
  return requestJson<ProjectSummary>(`/api/projects/${encodeURIComponent(videoId)}/summary`);
}

export function getProjectRenders(videoId: string): Promise<RenderJob[]> {
  return requestJson<RenderJob[]>(`/api/projects/${encodeURIComponent(videoId)}/renders`);
}

export function getProjectFiles(videoId: string): Promise<ProjectFilesResponse> {
  return requestJson<ProjectFilesResponse>(`/api/projects/${encodeURIComponent(videoId)}/files`);
}

export function getCandidates(videoId: string): Promise<CandidateListResponse> {
  return requestJson<CandidateListResponse>(`/api/videos/${encodeURIComponent(videoId)}/candidates`);
}

export function getEditorState(videoId: string): Promise<ProjectEditorState> {
  return requestJson<ProjectEditorState>(`/api/videos/${encodeURIComponent(videoId)}/editor-state`);
}

export function saveEditorState(videoId: string, state: ProjectEditorState): Promise<ProjectEditorState> {
  return requestJson<ProjectEditorState>(`/api/videos/${encodeURIComponent(videoId)}/editor-state`, {
    method: 'PUT',
    body: JSON.stringify(state),
  });
}

export function renderCandidates(videoId: string, candidateIds: number[]): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/videos/${encodeURIComponent(videoId)}/render`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
}

export function renderCandidateOverride(
  videoId: string,
  candidateIds: number[],
  overrides: Record<string, TrimOverride>,
  candidateStates?: Record<string, CandidateEditorState>,
): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/videos/${encodeURIComponent(videoId)}/render`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds, overrides, candidate_states: candidateStates ?? {} }),
  });
}

export function saveCandidateTrim(videoId: string, candidateId: number, start: number, end: number): Promise<CandidateListResponse['candidates'][number]> {
  return requestJson<CandidateListResponse['candidates'][number]>(`/api/videos/${encodeURIComponent(videoId)}/candidates/${candidateId}/trim`, {
    method: 'PUT',
    body: JSON.stringify({ start, end }),
  });
}

export function listRenders(): Promise<RenderJob[]> {
  return requestJson<RenderJob[]>('/api/renders');
}

export function deleteRender(renderId: string): Promise<void> {
  return requestJson<void>(`/api/renders/${encodeURIComponent(renderId)}`, {
    method: 'DELETE',
  });
}

export function retryRender(renderId: string): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/renders/${encodeURIComponent(renderId)}/retry`, {
    method: 'POST',
  });
}

export function updateRenderReview(renderId: string, status: RenderJob['review_status'], notes: string): Promise<RenderJob> {
  return requestJson<RenderJob>(`/api/renders/${encodeURIComponent(renderId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify({ status, notes }),
  });
}

export function listCaptionPresets(): Promise<CaptionPreset[]> {
  return requestJson<CaptionPreset[]>('/api/caption-presets');
}

export function createCaptionPreset(name: string, settings: CaptionPreset['settings']): Promise<CaptionPreset> {
  return requestJson<CaptionPreset>('/api/caption-presets', { method: 'POST', body: JSON.stringify({ name, settings }) });
}

export function updateCaptionPreset(id: string, name: string, settings: CaptionPreset['settings']): Promise<CaptionPreset> {
  return requestJson<CaptionPreset>(`/api/caption-presets/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify({ name, settings }) });
}

export function deleteCaptionPreset(id: string): Promise<void> {
  return requestJson<void>(`/api/caption-presets/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function listLibrary(): Promise<LibraryResponse> {
  return requestJson<LibraryResponse>('/api/library');
}

export function deleteLibraryFile(filename: string): Promise<void> {
  return requestJson<void>(`/api/library/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
}

export function getSettings(): Promise<Settings> {
  return requestJson<Settings>('/api/settings');
}
