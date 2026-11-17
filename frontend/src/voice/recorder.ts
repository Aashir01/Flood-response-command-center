// Microphone capture (lazy chunk): AudioWorklet to 16 kHz mono WAV, MediaRecorder webm/opus as fallback.
import { downsample, encodeWav, MAX_RECORD_S, toBase64 } from './wav';

export type RecordError = 'denied' | 'missing' | 'insecure' | 'unsupported' | 'failed';
export interface Recording {
  b64: string;
  format: 'wav' | 'webm';
  seconds: number;
}
export interface RecorderHandle {
  stop: () => Promise<Recording>;
  analyser: AnalyserNode | null;
}

export function classifyError(e: unknown): RecordError {
  const name = (e as { name?: string } | null)?.name ?? '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'missing';
  return 'failed';
}

export async function startRecording(onTick?: (seconds: number) => void, onAutoStop?: () => void): Promise<RecorderHandle> {
  if (typeof window === 'undefined' || !window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error('insecure'), { kind: 'insecure' as RecordError });
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    throw Object.assign(new Error('mic'), { kind: classifyError(e) });
  }
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const t0 = performance.now();
  let tick: ReturnType<typeof setInterval> | null = setInterval(() => {
    const s = (performance.now() - t0) / 1000;
    onTick?.(s);
    if (s >= MAX_RECORD_S) onAutoStop?.();
  }, 250);
  const cleanup = () => {
    if (tick) clearInterval(tick);
    tick = null;
    stream.getTracks().forEach((t) => t.stop());
    void ctx.close();
  };

  if (ctx.audioWorklet) {
    try {
      await ctx.audioWorklet.addModule('/worklets/pcm-recorder.js');
      const node = new AudioWorkletNode(ctx, 'pcm-recorder');
      const chunks: Float32Array[] = [];
      let total = 0;
      const cap = Math.ceil(ctx.sampleRate * MAX_RECORD_S);
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        if (total >= cap) return;
        chunks.push(e.data);
        total += e.data.length;
      };
      src.connect(node);
      return {
        analyser,
        stop: async () => {
          src.disconnect();
          const all = new Float32Array(Math.min(total, cap));
          let o = 0;
          for (const c of chunks) {
            const take = Math.min(c.length, all.length - o);
            all.set(c.subarray(0, take), o);
            o += take;
          }
          const rate = ctx.sampleRate;
          cleanup();
          const pcm = downsample(all, rate);
          return { b64: toBase64(encodeWav(pcm)), format: 'wav', seconds: all.length / rate };
        },
      };
    } catch {
      /* fall through to MediaRecorder */
    }
  }
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
    cleanup();
    throw Object.assign(new Error('unsupported'), { kind: 'unsupported' as RecordError });
  }
  const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
  const parts: Blob[] = [];
  rec.ondataavailable = (e) => parts.push(e.data);
  rec.start();
  return {
    analyser,
    stop: () =>
      new Promise<Recording>((resolve) => {
        rec.onstop = async () => {
          const buf = await new Blob(parts, { type: 'audio/webm' }).arrayBuffer();
          const seconds = (performance.now() - t0) / 1000;
          cleanup();
          resolve({ b64: toBase64(buf), format: 'webm', seconds });
        };
        rec.stop();
      }),
  };
}
