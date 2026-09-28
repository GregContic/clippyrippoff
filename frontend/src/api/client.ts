import type {
  AnalyzeResponse,
  CandidateListResponse,
  LibraryResponse,
  ProjectSummary,
  RenderJob,
  RenderResponse,
  Settings,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  if (!response.ok) {
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

export function analyzeVideo(url: string, forceDownload = false): Promise<AnalyzeResponse> {
  return requestJson<AnalyzeResponse>('/api/videos/analyze', {
    method: 'POST',
    body: JSON.stringify({ url, force_download: forceDownload }),
  });
}

export function listVideos(): Promise<{ items: ProjectSummary[] }> {
  return requestJson<{ items: ProjectSummary[] }>('/api/videos');
}

export function getVideo(videoId: string): Promise<ProjectSummary> {
  return requestJson<ProjectSummary>(`/api/videos/${encodeURIComponent(videoId)}`);
}

export function getCandidates(videoId: string): Promise<CandidateListResponse> {
  return requestJson<CandidateListResponse>(`/api/videos/${encodeURIComponent(videoId)}/candidates`);
}

export function renderCandidates(videoId: string, candidateIds: number[]): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/videos/${encodeURIComponent(videoId)}/render`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds }),
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
