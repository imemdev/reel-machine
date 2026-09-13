export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

export type Stage = "inbox" | "processing" | "processed" | "error" | "done" | "complete";
export type JobState = "queued" | "running" | "succeeded" | "failed";
export type JobAction = "process" | "retry" | "reprocess";
export type StageAction = "done" | "move_to_processed" | "complete";

export interface Segment {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface Transcript {
  id: string;
  origin: string;
  model_key: string;
  is_manual: boolean;
  created_at: string;
  version: number;
  segments: Segment[];
}

export interface Job {
  id: string;
  action: JobAction;
  state: JobState;
  model_key: string;
  model_label: string;
  current_step: string | null;
  failed_step: string | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  attempt_count: number;
  updated_at: string;
}

export interface Run extends Job {
  video_id: string;
  model_source: string;
  owner_asserted: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface Video {
  id: string;
  platform: "instagram" | "facebook" | "tiktok" | "fixture" | string;
  canonical_id: string;
  canonical_url: string;
  source_url: string;
  source_page_url: string | null;
  title: string;
  creator: string;
  thumbnail_url: string | null;
  duration_ms: number | null;
  stage: Stage;
  paused: boolean;
  error_code: string | null;
  error_message: string | null;
  failed_step: string | null;
  saved_at: string;
  updated_at: string;
  tags: string[];
  manual_edits: boolean;
  version: number;
  transcript: Transcript | null;
  job: Job | null;
  estimate?: { status: string; sample_count: number; transcription_seconds: number | null; remaining_seconds: number | null; estimated_finish_at: string | null; queue_position: number | null; ahead_seconds: number | null } | null;
  runs?: Run[] | null;
}

export interface ModelOption {
  key: "farukstt";
  label: "FarukSTT" | "Whisper Large-v3 (Full)" | string;
  description: string;
  source: string;
  available: boolean;
  availability_note: string;
}

export interface Preview {
  url: string;
  canonical_url: string;
  canonical_id: string;
  platform: string;
  status: "ready" | "private" | "unknown";
  title: string | null;
  creator: string | null;
  thumbnail_url: string | null;
  source_page_url: string | null;
  duration_ms: number | null;
  metadata_source: string | null;
  message: string;
}

export interface Activity {
  id: string;
  video_id: string | null;
  kind: string;
  message: string;
  created_at: string;
  display_title: string | null;
  platform: string | null;
}

export interface Counts {
  total: number;
  inbox: number;
  processing: number;
  processed: number;
  error: number;
  done: number;
  complete: number;
  [key: string]: number;
}

export interface Config {
  stages: Stage[];
  models: ModelOption[];
  suggested_tags: string[];
  privacy: {
    local_only: boolean;
    storage: string;
    processing: string;
  };
}

export interface Dashboard {
  counts: Counts;
  recent_activity: Activity[];
  processing: Video[];
}

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  status: number;

  constructor(message: string, code = "request_failed", status = 0, retryable = false) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.retryable = retryable;
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError("The local API is offline. Start FastAPI on port 8001 and try again.", "api_offline");
  }

  const raw = await response.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : payload;
    const errorDetail = typeof detail === "object" && detail !== null ? detail as Record<string, unknown> : {};
    const validationMessage = Array.isArray(detail)
      ? detail.map((issue: { loc?: unknown[]; msg?: string }) => {
        const field = issue.loc?.filter((part) => part !== "body").join(".");
        return issue.msg ? `${field ? `${field}: ` : ""}${issue.msg}` : "";
      }).filter(Boolean).join("; ")
      : "";
    const message = typeof errorDetail.message === "string"
      ? errorDetail.message
      : validationMessage
        ? validationMessage
      : typeof detail === "string"
        ? detail
        : `Request failed (${response.status}).`;
    throw new ApiError(
      message,
      typeof errorDetail.code === "string" ? errorDetail.code : "request_failed",
      response.status,
      Boolean(errorDetail.retryable),
    );
  }
  if (response.status === 204) return undefined as T;
  return payload as T;
}

export interface Note {
  id: string;
  title: string;
  description: string;
  script: string;
  done: boolean;
  created_at: string;
  updated_at: string;
}

export type NoteDraft = Pick<Note, "title" | "description" | "script">;

export const api = {
  getNotes: () => request<{ items: Note[]; count: number }>("/api/notes"),
  createNote: (payload: NoteDraft) => request<Note>("/api/notes", { method: "POST", body: JSON.stringify(payload) }),
  updateNote: (id: string, payload: Partial<NoteDraft & { done: boolean }>) => request<Note>(`/api/notes/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteNote: (id: string) => request<void>(`/api/notes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getConfig: () => request<Config>("/api/config"),
  getDashboard: () => request<Dashboard>("/api/dashboard"),
  getVideos: (query = "") => request<{ items: Video[]; count: number }>(`/api/videos${query}`),
  getVideo: (id: string) => request<Video>(`/api/videos/${encodeURIComponent(id)}`),
  preview: (url: string) => request<Preview>("/api/videos/preview", {
    method: "POST",
    body: JSON.stringify({ url }),
  }),
  createVideo: (payload: {
    url: string;
    source_page_url?: string | null;
    title?: string | null;
    creator?: string | null;
    thumbnail_url?: string | null;
    duration_ms?: number | null;
    tags: string[];
  }) => request<{ duplicate: boolean; video: Video }>("/api/videos", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateVideo: (id: string, payload: { title?: string; creator?: string; thumbnail_url?: string | null; tags?: string[] }) => request<Video>(`/api/videos/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  pauseVideo: (id: string) => request<Video>(`/api/videos/${encodeURIComponent(id)}/pause`, { method: "POST" }),
  resumeVideo: (id: string) => request<Video>(`/api/videos/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  deleteVideo: (id: string) => request<void>(`/api/videos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createJobs: (payload: {
    video_ids: string[];
    action: JobAction;
    model_key: "farukstt";
    owner_asserted_tunisian: boolean;
  }) => request<{ action: JobAction; model_key: string; accepted: Run[]; rejected: { video_id: string; message: string }[] }>("/api/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  stageAction: (id: string, action: StageAction) => request<Video>(`/api/videos/${encodeURIComponent(id)}/action`, {
    method: "POST",
    body: JSON.stringify({ action }),
  }),
  batchStageAction: (video_ids: string[], action: StageAction) => request<{ action: StageAction; items: { video_id: string; ok: boolean; message?: string; video?: Video }[] }>("/api/videos/actions", {
    method: "POST",
    body: JSON.stringify({ video_ids, action }),
  }),
  updateTranscript: (id: string, expected_revision_id: string, segments: Segment[]) => request<Video>(`/api/videos/${encodeURIComponent(id)}/transcript`, {
    method: "PATCH",
    body: JSON.stringify({ expected_revision_id, segments }),
  }),
};

export function exportUrl(id: string, format: "txt" | "srt" | "vtt" | "timestamped") {
  return `${API_BASE}/api/videos/${encodeURIComponent(id)}/export?format=${format}`;
}
