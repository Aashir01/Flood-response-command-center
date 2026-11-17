'use client';
import { useBench } from '@/state/BenchProvider';

export interface VoiceInfo {
  status: 'ready' | 'unwell' | 'disabled' | 'unknown';
  provider: string;
  hosted: boolean;
  canSpeak: boolean;
  canTranscribe: boolean;
}

export function useVoiceInfo(): VoiceInfo {
  const { health, state } = useBench();
  const info = health?.organs.find((o) => o.organ === 'voice');
  const meta = (info?.meta ?? {}) as { tts_provider?: string; hosted?: boolean; capabilities?: string[] };
  const caps = meta.capabilities ?? ['speak', 'transcribe'];
  const view = state.organs.voice.state;
  const status: VoiceInfo['status'] = !info ? 'unknown' : view === 'disabled' ? 'disabled' : view === 'unwell' ? 'unwell' : 'ready';
  return {
    status,
    provider: meta.tts_provider ?? 'azure',
    hosted: meta.hosted !== false,
    canSpeak: status === 'ready' && caps.includes('speak'),
    canTranscribe: status === 'ready' && caps.includes('transcribe'),
  };
}
