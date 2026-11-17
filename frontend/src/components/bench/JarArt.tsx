// Five hand-built SVG organs on a shared 96 x 120 viewBox (FRN decision 1). Each has a `glow`, `body` and
// `liquid` group; state variants only change the glow colour/opacity and the twitch transform (OrganJar).
import type { OrganId } from '@/api/types';

const GLASS = '#cfe7ef';

function JarGlass({ neck = 30 }: { neck?: number }) {
  const l = 48 - neck / 2;
  const r = 48 + neck / 2;
  return (
    <g className="jar-body">
      {/* lid */}
      <rect x={l - 4} y="8" width={neck + 8} height="9" rx="2.5" fill="#6b5430" stroke="#c9a24a" strokeWidth="1.2" />
      <path d={`M${l - 2} 11.5h${neck + 4}`} stroke="#e3c477" strokeOpacity=".55" strokeWidth="1" />
      {/* glass */}
      <path
        d={`M${l} 17V23C${l - 14} 26 12 32 12 43V95C12 104 18 110 27 110H69C78 110 84 104 84 95V43C84 32 ${r + 14} 26 ${r} 23V17`}
        fill="#9fd3ff0f"
        stroke={GLASS}
        strokeOpacity=".75"
        strokeWidth="1.6"
      />
      {/* highlights */}
      <path d="M17 46c0-5 3-9 8-11" stroke="#ffffff" strokeOpacity=".45" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M17 54v34" stroke="#ffffff" strokeOpacity=".22" strokeWidth="3" strokeLinecap="round" />
      <path d="M79 60v22" stroke="#ffffff" strokeOpacity=".12" strokeWidth="2" strokeLinecap="round" />
    </g>
  );
}

function Liquid({ color, level = 52 }: { color: string; level?: number }) {
  return (
    <g className="jar-liquid">
      <path d={`M15 ${level}c11-3 22 2 33 0s22-3 33 0V95c0 7-5 12-12 12H27c-7 0-12-5-12-12Z`} fill={color} fillOpacity=".32" />
      <path d={`M15 ${level}c11-3 22 2 33 0s22-3 33 0`} stroke={color} strokeOpacity=".7" strokeWidth="1.2" fill="none" />
      <circle cx="36" cy="88" r="1.6" fill="#ffffff" fillOpacity=".35" />
      <circle cx="58" cy="76" r="1.1" fill="#ffffff" fillOpacity=".3" />
      <circle cx="44" cy="68" r="0.9" fill="#ffffff" fillOpacity=".3" />
    </g>
  );
}

function Eye() {
  return (
    <>
      <Liquid color="#2cf5c0" level={44} />
      <g className="jar-organ">
        {/* optic nerve */}
        <path d="M50 82c2 6-4 9-1 15s-3 6-2 9" stroke="#c9707a" strokeWidth="3" strokeLinecap="round" fill="none" />
        <path d="M50 82c2 6-4 9-1 15" stroke="#ffb3ba" strokeOpacity=".5" strokeWidth="1" fill="none" />
        <circle cx="48" cy="68" r="15" fill="#ece6d8" stroke="#8a8172" strokeWidth="1" />
        {/* veins */}
        <path d="M34 66c4 0 6 2 8 1M61 72c-3-1-5 1-7 0M40 79c2-2 4-2 5-4" stroke="#c9707a" strokeOpacity=".7" strokeWidth=".8" fill="none" />
        <circle cx="50" cy="66" r="7.5" fill="#2a8c7a" />
        <circle cx="50" cy="66" r="7.5" fill="none" stroke="#2cf5c0" strokeWidth="1.2" />
        <circle cx="50" cy="66" r="3.4" fill="#05080a" />
        <circle cx="52.4" cy="63.6" r="1.6" fill="#ffffff" fillOpacity=".9" />
      </g>
    </>
  );
}

function Vial() {
  // A faceted crystal vial: narrower glass than the jars.
  return (
    <g>
      <g className="jar-body">
        <rect x="38" y="6" width="20" height="10" rx="2" fill="#8a6a43" stroke="#c9a24a" strokeWidth="1.1" />
        <path d="M41 16v10L28 46v46l20 20 20-20V46L55 26V16Z" fill="#9fd3ff12" stroke={GLASS} strokeOpacity=".8" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M28 46h40M48 26v86M28 92h40" stroke={GLASS} strokeOpacity=".22" strokeWidth="1" />
        <path d="M32 50v38" stroke="#ffffff" strokeOpacity=".35" strokeWidth="2" strokeLinecap="round" />
      </g>
      <g className="jar-liquid">
        <path d="M30 64c6-3 12 2 18 0s12-3 18 0v27L48 109 30 91Z" fill="#9fd3ff" fillOpacity=".3" />
        <path d="M30 64c6-3 12 2 18 0s12-3 18 0" stroke="#9fd3ff" strokeOpacity=".8" strokeWidth="1.2" fill="none" />
      </g>
      <g className="jar-organ">
        {/* a swirl of modeled futures */}
        <path d="M38 84c4-8 16-8 18-1s-8 10-12 6 0-8 4-7" stroke="#e8f6ff" strokeOpacity=".85" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        <path d="M48 30l1.2 2.6 2.8.4-2 2 .5 2.8-2.5-1.3-2.5 1.3.5-2.8-2-2 2.8-.4Z" fill="#e8f6ff" fillOpacity=".8" />
        <circle cx="40" cy="54" r="1" fill="#e8f6ff" fillOpacity=".7" />
        <circle cx="57" cy="50" r="0.8" fill="#e8f6ff" fillOpacity=".6" />
      </g>
    </g>
  );
}

function Book() {
  return (
    <>
      <Liquid color="#e8dfc8" level={50} />
      <g className="jar-organ">
        {/* an open book, slightly tilted */}
        <g transform="rotate(-6 48 76)">
          <path d="M28 62c7-3 14-3 20 2v30c-6-5-13-5-20-2Z" fill="#e8dfc8" stroke="#8d8571" strokeWidth="1" />
          <path d="M68 62c-7-3-14-3-20 2v30c6-5 13-5 20-2Z" fill="#d9ceb2" stroke="#8d8571" strokeWidth="1" />
          <path d="M31 69c5-1.5 10-1 14 1.5M31 74c5-1.5 10-1 14 1.5M31 79c5-1.5 10-1 14 1.5M31 84c5-1.5 10-1 14 1.5" stroke="#6b6352" strokeWidth=".8" fill="none" />
          <path d="M51 70.5c4-2.5 9-3 14-1.5M51 75.5c4-2.5 9-3 14-1.5M51 80.5c4-2.5 9-3 14-1.5" stroke="#6b6352" strokeWidth=".8" fill="none" />
          <path d="M60 63v13l2.5-2.5L65 76V62.5" fill="#ff4d5e" fillOpacity=".85" />
          <path d="M28 62l-3 1v31l3-2M68 62l3 1v31l-3-2" stroke="#5a3b22" strokeWidth="2" fill="none" />
        </g>
      </g>
    </>
  );
}

function Scales() {
  return (
    <g>
      <g className="jar-body">
        {/* base and post */}
        <path d="M28 110h40l-4-7H32Z" fill="#6b5430" stroke="#c9a24a" strokeWidth="1.2" strokeLinejoin="round" />
        <path d="M46 103V30h4v73Z" fill="#8a6a43" stroke="#c9a24a" strokeWidth="1" />
        <circle cx="48" cy="26" r="5" fill="#8a6a43" stroke="#e3c477" strokeWidth="1.2" />
        <path d="M44 103c0-4 8-4 8 0" fill="#6b5430" stroke="#c9a24a" strokeWidth="1" />
      </g>
      <g className="jar-organ">
        {/* beam tilted toward the heavier pan */}
        <path d="M14 34 82 28" stroke="#e3c477" strokeWidth="3" strokeLinecap="round" />
        <circle cx="48" cy="31" r="2" fill="#2a1d0f" />
        {/* chains */}
        <path d="M16 34 8 66M16 34l8 32M80 28l-8 30M80 28l8 30" stroke="#c9a24a" strokeWidth=".9" strokeDasharray="2 1.5" />
        {/* pans */}
        <path d="M4 66h24c-1 6-6 9-12 9S5 72 4 66Z" fill="#8a6a43" stroke="#e3c477" strokeWidth="1.2" />
        <path d="M68 58h24c-1 6-6 9-12 9s-11-3-12-9Z" fill="#8a6a43" stroke="#e3c477" strokeWidth="1.2" />
      </g>
      <g className="jar-liquid">
        {/* coins and a ration crate */}
        <ellipse cx="12" cy="64" rx="5" ry="1.8" fill="#e3c477" stroke="#8a6a43" strokeWidth=".6" />
        <ellipse cx="18" cy="62" rx="5" ry="1.8" fill="#e3c477" stroke="#8a6a43" strokeWidth=".6" />
        <ellipse cx="14" cy="60" rx="5" ry="1.8" fill="#f0d68f" stroke="#8a6a43" strokeWidth=".6" />
        <rect x="73" y="48" width="14" height="10" rx="1" fill="#2cf5c0" fillOpacity=".35" stroke="#2cf5c0" strokeWidth="1" />
        <path d="M73 53h14M80 48v10" stroke="#2cf5c0" strokeOpacity=".7" strokeWidth=".8" />
      </g>
    </g>
  );
}

function Horn() {
  return (
    <g>
      <g className="jar-body">
        {/* a gramophone-like horn grown from a throat */}
        <path d="M30 110h36l-4-8H34Z" fill="#6b5430" stroke="#c9a24a" strokeWidth="1.2" strokeLinejoin="round" />
        <path d="M44 102V80c0-8 4-12 10-16" stroke="#c9707a" strokeWidth="7" strokeLinecap="round" fill="none" />
        <path d="M44 100V80c0-8 4-12 10-16" stroke="#ffb3ba" strokeOpacity=".45" strokeWidth="1.5" fill="none" />
        <path d="M45 96h-2M45 90h-2M45 84h-2" stroke="#7a3d44" strokeWidth="1.2" />
      </g>
      <g className="jar-organ">
        <path d="M52 66 82 24c4 2 8 9 8 15L56 70Z" fill="#c9a24a" stroke="#e3c477" strokeWidth="1.2" strokeLinejoin="round" />
        <ellipse cx="85.5" cy="31.5" rx="4.5" ry="9" transform="rotate(35 85.5 31.5)" fill="#2a1d0f" stroke="#e3c477" strokeWidth="1.2" />
        <path d="M60 60 80 32" stroke="#fff3cc" strokeOpacity=".55" strokeWidth="1.2" />
      </g>
      <g className="jar-liquid">
        {/* sound rings */}
        <path d="M14 30c-4 6-4 14 0 20M8 26c-6 9-6 19 0 28" stroke="#9fd3ff" strokeOpacity=".55" strokeWidth="1.3" fill="none" strokeLinecap="round" />
      </g>
    </g>
  );
}

export function JarIllustration({ organ }: { organ: OrganId }) {
  switch (organ) {
    case 'eyes':
      return (
        <>
          <JarGlass />
          <Eye />
        </>
      );
    case 'library':
      return (
        <>
          <JarGlass neck={34} />
          <Book />
        </>
      );
    case 'oracle':
      return <Vial />;
    case 'ledger':
      return <Scales />;
    case 'voice':
      return <Horn />;
  }
}
