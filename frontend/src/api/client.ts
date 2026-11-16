// Thin typed fetch wrapper for the Brain API. UI paths never see thrown exceptions: every call returns Result<T>.
import type {
  ApiError,
  AskResponse,
  BriefingAccepted,
  BriefingRequest,
  BriefingState,
  EvidenceValue,
  OrganList,
  Result,
  SpeakRequest,
  VoiceSpeakResponse,
  VoiceTranscribeResponse,
} from './types';

export const BRAIN_URL: string = (process.env.NEXT_PUBLIC_BRAIN_URL ?? '/api').replace(/\/$/, '');

export interface EvalMetric {
  id: string;
  label: string;
  value: number | null;
  target: number | null;
  direction: 'higher_is_better' | 'lower_is_better';
  unit?: string;
  passed?: boolean | null;
  dataset?: string;
  mode?: string;
  history?: { timestamp: string; value: number }[];
}
export interface EvalOrgan {
  status: 'ok' | 'not_run' | 'failed';
  metrics: EvalMetric[];
  note?: string;
}
export interface EvalsLatest {
  generated_at: string | null;
  git_sha?: string | null;
  mode?: string;
  organs: Record<string, EvalOrgan>;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 10_000): Promise<Result<T>> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BRAIN_URL}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
    });
    if (res.ok) {
      if (res.status === 204) return { ok: true, value: undefined as T };
      return { ok: true, value: (await res.json()) as T };
    }
    let message = res.statusText;
    let code: ApiError['code'] = 'INTERNAL';
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.message) message = body.error.message;
      if (body.error?.code) code = body.error.code as ApiError['code'];
    } catch {
      /* non-JSON body */
    }
    if (res.status === 429) code = 'RATE_LIMITED';
    else if (res.status === 404) code = 'NOT_FOUND';
    else if (res.status === 503) code = 'UPSTREAM_UNAVAILABLE';
    else if (res.status === 400 || res.status === 422) code = 'INVALID_INPUT';
    const retry = Number(res.headers.get('Retry-After'));
    return { ok: false, error: { code, message, status: res.status, retryAfterS: Number.isFinite(retry) && retry > 0 ? retry : undefined } };
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === 'AbortError';
    return { ok: false, error: { code: aborted ? 'TIMEOUT' : 'UNREACHABLE', message: aborted ? 'The request timed out.' : 'The Brain could not be reached.' } };
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  getOrgans: () => request<OrganList>('/organs'),
  startBriefing: (body: BriefingRequest) => request<BriefingAccepted>('/briefings', { method: 'POST', body: JSON.stringify(body) }),
  cancelBriefing: (id: string) => request<void>(`/briefings/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getBriefing: (id: string) => request<BriefingState>(`/briefings/${encodeURIComponent(id)}`),
  /** Pointer form only: `/data` returns the tool output, `/data/x/0` one value (Brain design §14). */
  getEvidence: (runId: string, pointer = '/data') =>
    request<EvidenceValue>(`/evidence/${encodeURIComponent(runId)}?pointer=${encodeURIComponent(pointer)}`),
  ask: (question: string, lang: 'auto' | 'en' | 'ur' = 'auto') => request<AskResponse>('/ask', { method: 'POST', body: JSON.stringify({ question, lang }) }, 30_000),
  transcribe: (audioB64: string, format: 'wav' | 'webm' | 'mp3' | 'ogg', langHint: 'en' | 'ur' | 'auto' = 'auto') =>
    request<VoiceTranscribeResponse>('/voice/transcribe', { method: 'POST', body: JSON.stringify({ audio_b64: audioB64, format, lang_hint: langHint }) }, 60_000),
  speak: (body: SpeakRequest) => request<VoiceSpeakResponse>('/voice/speak', { method: 'POST', body: JSON.stringify(body) }, 60_000),
  getEvals: () => request<EvalsLatest>('/evals/latest'),
  health: () => request<{ status: string }>('/healthz', {}, 4000),
};

export function eventsUrl(id: string, lastSeq = 0): string {
  const q = lastSeq > 0 ? `?last_event_id=${lastSeq}` : '';
  return `${BRAIN_URL}/briefings/${encodeURIComponent(id)}/events${q}`;
}