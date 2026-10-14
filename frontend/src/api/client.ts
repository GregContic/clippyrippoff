import type {
  AnalyzeResponse,
  BatchResponse,
  CaptionPreset,
  CandidateEditorState,
  CandidateListResponse,
  CompilationResponse,
  EditingSettings,
  LibraryResponse,
  ProjectFilesResponse,
  ProjectMusicAsset,
  ProjectEditorState,
  ProjectSummary,
  RenderJob,
  RenderResponse,
  TrimOverride,
  Settings,
  UploadConfig,
  UploadPart,
  UploadStartResponse,
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

export type UploadSessionState = {
  upload: UploadStartResponse;
  completedParts: UploadPart[];
};

type UploadProgress = (uploadedBytes: number, totalBytes: number) => void;
type UploadSessionChanged = (session: UploadSessionState) => void;

export function getUploadConfig(): Promise<UploadConfig> {
  return requestJson<UploadConfig>('/api/videos/upload/config');
}

function xhrUpload(
  url: string,
  body: XMLHttpRequestBodyInit,
  headers: Record<string, string>,
  signal: AbortSignal,
  onProgress: (loaded: number) => void,
): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const cleanup = () => signal.removeEventListener('abort', abort);
    const abort = () => xhr.abort();
    xhr.open('PUT', url);
    Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    };
    xhr.onerror = () => {
      cleanup();
      reject(new Error('Network error uploading to R2. Check the bucket CORS configuration and connection.'));
    };
    xhr.onabort = () => {
      cleanup();
      reject(new DOMException('Upload canceled.', 'AbortError'));
    };
    xhr.onload = () => {
      cleanup();
      if (xhr.status < 200 || xhr.status >= 300) {
        const message = xhr.status === 403
          ? 'R2 rejected the upload (403). The URL may have expired, or the bucket credentials/permissions are insufficient; retry to get a fresh URL and check R2 access.'
          : `R2 upload failed with status ${xhr.status}. Retry the upload.`;
        reject(new Error(message));
        return;
      }
      resolve(xhr.getResponseHeader('ETag'));
    };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) {
      abort();
      return;
    }
    xhr.send(body);
  });
}

function csrfHeaders(): Record<string, string> {
  const csrfToken = document.cookie.split('; ').find((item) => item.startsWith('clippy_csrf='))?.split('=').slice(1).join('=');
  return csrfToken ? { 'X-CSRF-Token': decodeURIComponent(csrfToken) } : {};
}

function xhrMultipartUpload(file: File, signal: AbortSignal, onProgress: UploadProgress): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append('file', file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const cleanup = () => signal.removeEventListener('abort', abort);
    const abort = () => xhr.abort();
    xhr.open('POST', `${API_BASE_URL}/api/videos/upload`);
    xhr.withCredentials = true;
    Object.entries(csrfHeaders()).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => onProgress(event.loaded, file.size);
    xhr.onerror = () => {
      cleanup();
      reject(new Error('Network error sending the local-development upload.'));
    };
    xhr.onabort = () => {
      cleanup();
      reject(new DOMException('Upload canceled.', 'AbortError'));
    };
    xhr.onload = () => {
      cleanup();
      let payload: AnalyzeResponse | { detail?: string };
      try {
        payload = JSON.parse(xhr.responseText) as AnalyzeResponse | { detail?: string };
      } catch {
        reject(new Error(xhr.responseText || `Request failed with status ${xhr.status}`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error('detail' in payload ? payload.detail ?? `Request failed with status ${xhr.status}` : `Request failed with status ${xhr.status}`));
        return;
      }
      resolve(payload as AnalyzeResponse);
    };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) {
      abort();
      return;
    }
    xhr.send(form);
  });
}

export function cancelVideoUpload(uploadId: string): Promise<void> {
  return requestJson<void>(`/api/videos/uploads/${encodeURIComponent(uploadId)}`, { method: 'DELETE' });
}

export async function uploadVideo(
  file: File,
  signal: AbortSignal,
  onProgress: UploadProgress,
  onSessionChanged: UploadSessionChanged,
  resumed?: UploadSessionState,
): Promise<AnalyzeResponse> {
  const config = await getUploadConfig();
  if (file.size > config.max_upload_bytes) {
    throw new Error(`File exceeds the maximum supported size of ${formatUploadBytes(config.max_upload_bytes)}.`);
  }
  const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
  if (!config.allowed_extensions.includes(extension)) {
    throw new Error(`Unsupported video format. Accepted formats: ${config.allowed_extensions.join(', ')}.`);
  }
  if (!config.direct_upload) {
    if (import.meta.env.PROD) {
      throw new Error('Direct R2 uploads are unavailable. The video was not sent through the backend; check upload configuration and retry.');
    }
    return xhrMultipartUpload(file, signal, onProgress);
  }

  let session = resumed;
  try {
    if (!session) {
      const contentType = file.type || fallbackVideoContentType(extension);
      const upload = await requestJson<UploadStartResponse>('/api/videos/uploads', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, size_bytes: file.size, content_type: contentType }),
      });
      session = { upload, completedParts: [] };
      onSessionChanged(session);
    }
    if (!session) {
      throw new Error('Upload session could not be created.');
    }
    const uploadSession = session;
    if (signal.aborted) throw new DOMException('Upload canceled.', 'AbortError');

    if (uploadSession.upload.upload_mode === 'put') {
      let lastError: unknown;
      for (let attempt = 0; attempt < 4; attempt += 1) {
        try {
          const url = attempt === 0 && uploadSession.upload.upload_url
            ? uploadSession.upload.upload_url
            : (await requestJson<{ url: string }>(`/api/videos/uploads/${uploadSession.upload.upload_id}/url`, { method: 'POST' })).url;
          await xhrUpload(url, file, { 'Content-Type': file.type || fallbackVideoContentType(extension) }, signal, (loaded) => onProgress(loaded, file.size));
          lastError = undefined;
          break;
        } catch (cause) {
          lastError = cause;
          if (signal.aborted || attempt === 3) break;
          await new Promise((resolve) => window.setTimeout(resolve, 300 * (attempt + 1)));
        }
      }
      if (lastError) throw lastError;
    } else {
      const partSize = uploadSession.upload.part_size_bytes;
      const totalParts = Math.ceil(file.size / partSize);
      const completed = new Map(uploadSession.completedParts.map((part) => [part.part_number, part]));
      const inFlight = new Map<number, number>();
      const partLength = (number: number) => Math.min(partSize, file.size - (number - 1) * partSize);
      const reportProgress = () => {
        const transferred = [...completed.keys()].reduce((sum, number) => sum + partLength(number), 0)
          + [...inFlight.values()].reduce((sum, amount) => sum + amount, 0);
        onProgress(Math.min(file.size, transferred), file.size);
      };
      let nextPart = 1;
      let failure: unknown;
      const worker = async () => {
        while (!signal.aborted && !failure) {
          while (completed.has(nextPart) && nextPart <= totalParts) nextPart += 1;
          if (nextPart > totalParts) return;
          const partNumber = nextPart++;
          const start = (partNumber - 1) * partSize;
          const part = file.slice(start, Math.min(file.size, start + partSize));
          for (let attempt = 0; attempt < 4 && !signal.aborted; attempt += 1) {
            try {
              const { url } = await requestJson<{ url: string }>(
                `/api/videos/uploads/${uploadSession.upload.upload_id}/parts/${partNumber}/url`,
                { method: 'POST' },
              );
              const etag = await xhrUpload(url, part, {}, signal, (loaded) => {
                inFlight.set(partNumber, loaded);
                reportProgress();
              });
              if (!etag) throw new Error('R2 did not return an ETag. Confirm the bucket exposes the ETag response header.');
              completed.set(partNumber, { part_number: partNumber, etag });
              inFlight.delete(partNumber);
              session = {
                upload: uploadSession.upload,
                completedParts: [...completed.values()].sort((left, right) => left.part_number - right.part_number),
              };
              onSessionChanged(session);
              reportProgress();
              break;
            } catch (cause) {
              inFlight.delete(partNumber);
              reportProgress();
              if (signal.aborted || attempt === 3) {
                failure = cause;
                return;
              }
              await new Promise((resolve) => window.setTimeout(resolve, 300 * (attempt + 1)));
            }
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(3, totalParts) }, () => worker()));
      if (signal.aborted) throw new DOMException('Upload canceled.', 'AbortError');
      if (failure) throw failure;
    }

    if (signal.aborted) throw new DOMException('Upload canceled.', 'AbortError');
    onProgress(file.size, file.size);
    return requestJson<AnalyzeResponse>(`/api/videos/uploads/${uploadSession.upload.upload_id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ parts: session.completedParts }),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError' && session) {
      try {
        await cancelVideoUpload(session.upload.upload_id);
      } catch (cleanupError) {
        throw new Error(`Upload canceled, but R2 cleanup failed: ${cleanupError instanceof Error ? cleanupError.message : 'unknown error'}`);
      }
    }
    throw cause;
  }
}

function formatUploadBytes(bytes: number): string {
  const gib = bytes / (1024 * 1024 * 1024);
  return gib >= 1 ? `${gib.toFixed(1)} GiB` : `${Math.ceil(bytes / (1024 * 1024))} MiB`;
}

function fallbackVideoContentType(extension: string): string {
  const types: Record<string, string> = {
    '.avi': 'video/x-msvideo',
    '.m4v': 'video/x-m4v',
    '.mkv': 'video/x-matroska',
    '.mov': 'video/quicktime',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
  };
  return types[extension] ?? 'application/octet-stream';
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

export function renderCandidates(videoId: string, candidateIds: number[], editing?: EditingSettings): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/videos/${encodeURIComponent(videoId)}/render`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds, ...(editing ? { editing } : {}) }),
  });
}

export function renderCandidateOverride(
  videoId: string,
  candidateIds: number[],
  overrides: Record<string, TrimOverride>,
  candidateStates?: Record<string, CandidateEditorState>,
  editing?: EditingSettings,
): Promise<RenderResponse> {
  return requestJson<RenderResponse>(`/api/videos/${encodeURIComponent(videoId)}/render`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds, overrides, candidate_states: candidateStates ?? {}, ...(editing ? { editing } : {}) }),
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

export function deleteLibraryArtifact(artifactId: string): Promise<void> {
  return requestJson<void>(`/api/library/artifacts/${encodeURIComponent(artifactId)}`, {
    method: 'DELETE',
  });
}

export function createBatch(
  videoId: string,
  request: {
    target_duration_seconds: number;
    minimum_spacing_seconds: number;
    max_clips?: number;
    candidate_ids?: number[];
    render_settings?: Record<string, unknown>;
    editing?: EditingSettings;
  },
): Promise<BatchResponse> {
  return requestJson<BatchResponse>(`/api/projects/${encodeURIComponent(videoId)}/batches`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function getBatch(batchId: string): Promise<BatchResponse> {
  return requestJson<BatchResponse>(`/api/batches/${encodeURIComponent(batchId)}`);
}

export function createCompilation(
  videoId: string,
  request: {
    segments: Array<{ candidate_id: number; start: number; end: number }>;
    max_total_duration_seconds: number;
    render_settings: { captions_enabled: boolean };
    editing?: EditingSettings;
  },
): Promise<CompilationResponse> {
  return requestJson<CompilationResponse>(`/api/projects/${encodeURIComponent(videoId)}/compilations`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function getCompilation(compilationId: string): Promise<CompilationResponse> {
  return requestJson<CompilationResponse>(`/api/compilations/${encodeURIComponent(compilationId)}`);
}

export function getProjectMusic(videoId: string): Promise<ProjectMusicAsset[]> {
  return requestJson<ProjectMusicAsset[]>(`/api/projects/${encodeURIComponent(videoId)}/music`);
}

export function uploadProjectMusic(videoId: string, file: File): Promise<ProjectMusicAsset> {
  const form = new FormData();
  form.append('file', file);
  const csrfToken = document.cookie.split('; ').find((item) => item.startsWith('clippy_csrf='))?.split('=').slice(1).join('=');
  const headers: Record<string, string> = {};
  if (csrfToken) {
    headers['X-CSRF-Token'] = decodeURIComponent(csrfToken);
  }
  return fetch(`${API_BASE_URL}/api/projects/${encodeURIComponent(videoId)}/music`, {
    method: 'POST',
    body: form,
    credentials: 'include',
    headers,
  }).then(async (response) => {
    const text = await response.text();
    if (!response.ok) {
      let message = text;
      try {
        message = (JSON.parse(text) as { detail?: string }).detail ?? message;
      } catch {
        // Surface non-JSON server errors as-is.
      }
      throw new Error(message || `Request failed with status ${response.status}`);
    }
    return JSON.parse(text) as ProjectMusicAsset;
  });
}

export function getSettings(): Promise<Settings> {
  return requestJson<Settings>('/api/settings');
}
