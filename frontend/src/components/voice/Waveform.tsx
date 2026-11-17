'use client';
import { useEffect, useRef } from 'react';

/** Decorative waveform from an AnalyserNode, redrawn at most 30 times a second. */
export function Waveform({ analyser, label }: { analyser: AnalyserNode | null; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const g = c.getContext('2d');
    if (!g) return;
    let raf = 0;
    let last = 0;
    const data = analyser ? new Uint8Array(analyser.fftSize) : null;
    const draw = (t: number) => {
      raf = requestAnimationFrame(draw);
      if (t - last < 33) return;
      last = t;
      const w = (c.width = c.clientWidth * devicePixelRatio);
      const h = (c.height = c.clientHeight * devicePixelRatio);
      g.clearRect(0, 0, w, h);
      g.strokeStyle = '#2cf5c0';
      g.lineWidth = 2 * devicePixelRatio;
      g.beginPath();
      if (analyser && data) {
        analyser.getByteTimeDomainData(data);
        for (let i = 0; i < data.length; i++) {
          const x = (i / (data.length - 1)) * w;
          const y = ((data[i] as number) / 255) * h;
          if (i) g.lineTo(x, y);
          else g.moveTo(x, y);
        }
      } else {
        g.moveTo(0, h / 2);
        g.lineTo(w, h / 2);
      }
      g.stroke();
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [analyser]);
  return <canvas ref={ref} className="wave" aria-hidden="true" title={label} />;
}
