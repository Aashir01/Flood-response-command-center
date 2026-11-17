// Thin Web Audio interpreter for the recipes. The AudioContext is created only after the user turns sound on.
import { MASTER_GAIN, RECIPES, type Recipe, type SoundId } from './voices';

type Ctor = typeof AudioContext;

export class SoundEngine {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private hum: { stop: () => void } | null = null;
  constructor(private readonly Ctx: Ctor | undefined = typeof window !== 'undefined' ? (window.AudioContext ?? (window as unknown as { webkitAudioContext?: Ctor }).webkitAudioContext) : undefined) {}

  get created(): boolean {
    return this.ctx !== null;
  }

  async enable(): Promise<void> {
    if (!this.Ctx) return;
    if (!this.ctx) {
      this.ctx = new this.Ctx();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0;
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state === 'suspended') await this.ctx.resume();
    const now = this.ctx.currentTime;
    this.master?.gain.cancelScheduledValues(now);
    this.master?.gain.setTargetAtTime(MASTER_GAIN, now, 0.05);
    if (!this.hum) this.hum = this.start(RECIPES.hum);
  }

  async disable(): Promise<void> {
    if (!this.ctx || !this.master) return;
    const now = this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(now);
    this.master.gain.setTargetAtTime(0, now, 0.05);
    this.hum?.stop();
    this.hum = null;
    const ctx = this.ctx;
    setTimeout(() => void ctx.suspend(), 250);
  }

  play(id: SoundId): void {
    if (!this.ctx || this.ctx.state !== 'running') return;
    this.start(RECIPES[id]);
  }

  private start(r: Recipe): { stop: () => void } {
    const ctx = this.ctx as AudioContext;
    const out = this.master as GainNode;
    const t0 = ctx.currentTime;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0, t0);
    env.gain.linearRampToValueAtTime(r.env.peak, t0 + r.env.attackS);
    if (!r.env.sustain) env.gain.exponentialRampToValueAtTime(0.0001, t0 + r.env.attackS + r.env.decayS);
    let head: AudioNode = env;
    const stops: (() => void)[] = [];
    if (r.filter) {
      const f = ctx.createBiquadFilter();
      f.type = r.filter.type;
      f.frequency.setValueAtTime(r.filter.freq, t0);
      if (r.filter.q) f.Q.value = r.filter.q;
      if (r.filter.freqTo) f.frequency.exponentialRampToValueAtTime(r.filter.freqTo, t0 + (r.filter.sweepS ?? 1));
      if (r.filter.lfo) {
        const lfo = ctx.createOscillator();
        const depth = ctx.createGain();
        lfo.frequency.value = r.filter.lfo.rateHz;
        depth.gain.value = r.filter.lfo.depthHz;
        lfo.connect(depth).connect(f.frequency);
        lfo.start(t0);
        stops.push(() => lfo.stop());
      }
      f.connect(env);
      head = f;
    }
    env.connect(out);
    const end = t0 + r.env.attackS + r.env.decayS + 0.05;
    for (const s of r.sources) {
      if (s.kind === 'osc') {
        const o = ctx.createOscillator();
        o.type = s.type;
        o.frequency.setValueAtTime(s.freq, t0);
        if (s.freqTo) o.frequency.exponentialRampToValueAtTime(s.freqTo, t0 + (s.glideS ?? 0.3));
        o.connect(head);
        o.start(t0);
        if (!r.env.sustain) o.stop(end);
        stops.push(() => o.stop());
      } else {
        const len = Math.max(1, Math.floor(ctx.sampleRate * s.seconds));
        const buf = ctx.createBuffer(1, len, ctx.sampleRate);
        const ch = buf.getChannelData(0);
        for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(head);
        src.start(t0);
        stops.push(() => src.stop());
      }
    }
    return {
      stop: () => {
        const now = ctx.currentTime;
        env.gain.cancelScheduledValues(now);
        env.gain.setTargetAtTime(0, now, 0.2);
        setTimeout(() => stops.forEach((s) => s()), 900);
      },
    };
  }
}
