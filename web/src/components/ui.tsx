import {
  CircleHelp,
  Eye as EyeIcon,
  Glasses,
  Moon,
  Sun,
  SunDim,
  Telescope,
  Type,
  Undo2,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from 'lucide-react';
import type { ReactNode } from 'react';
import type { Sample } from '../store';

export const TOOL_META: Record<string, { label: string; verb: string; icon: LucideIcon }> = {
  enlarge_text: { label: 'Enlarge text', verb: 'Made text larger', icon: ZoomIn },
  reduce_text: { label: 'Reduce text', verb: 'Put text back one step', icon: ZoomOut },
  dim_screen: { label: 'Dim screen', verb: 'Dimmed the screen', icon: SunDim },
  brighten_screen: { label: 'Brighten screen', verb: 'Brightened the screen', icon: Sun },
  dark_mode: { label: 'Dark mode', verb: 'Switched to dark mode', icon: Moon },
  far_look_break: { label: 'Far-look break', verb: '20-second far look', icon: Telescope },
  glasses_reminder: { label: 'Glasses reminder', verb: 'Reminded you about glasses', icon: Glasses },
  ask_user: { label: 'Ask you', verb: 'Asked you', icon: CircleHelp },
  reset: { label: 'Reset', verb: 'Undid every change', icon: Undo2 },
  none: { label: 'Stay quiet', verb: 'Stayed quiet', icon: EyeIcon },
};

export function toolMeta(t: string) {
  return TOOL_META[t] ?? { label: t, verb: t, icon: Type };
}

export function fmtTime(t: number) {
  return new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function fmtDur(s: number) {
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** Progress ring (used for strain and the break countdown). */
export function Ring({
  value,
  size = 96,
  stroke = 10,
  children,
  tone = 'grad',
  label,
}: {
  value: number;
  size?: number;
  stroke?: number;
  children?: ReactNode;
  tone?: 'grad' | 'warn' | 'light';
  label?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const id = `rg${size}${tone}`;
  return (
    <div style={{ position: 'relative', width: size, height: size, flex: 'none' }} role={label ? 'img' : undefined} aria-label={label}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }} aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" x2="1" y1="0" y2="1">
            {tone === 'warn' ? (
              <>
                <stop offset="0" stopColor="#f6c66b" />
                <stop offset="1" stopColor="#ef6b5b" />
              </>
            ) : tone === 'light' ? (
              <>
                <stop offset="0" stopColor="#ffffff" />
                <stop offset="1" stopColor="#bff4ef" />
              </>
            ) : (
              <>
                <stop offset="0" stopColor="#2fd3c4" />
                <stop offset="1" stopColor="#3b6cf6" />
              </>
            )}
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone === 'light' ? 'rgba(255,255,255,0.18)' : 'var(--card-2)'} strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#${id})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v)}
          style={{ transition: 'stroke-dashoffset 0.6s cubic-bezier(.2,.8,.2,1)' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center' }}>{children}</div>
    </div>
  );
}

/** Distance over time, with the 30 cm and 40-70 cm bands shaded. */
export function DistanceChart({ samples, height = 220 }: { samples: Sample[]; height?: number }) {
  const W = 800;
  const H = height;
  const pad = { l: 36, r: 12, t: 12, b: 24 };
  const pts = samples.filter((s) => s.d !== null) as { t: number; d: number; s: number }[];
  const yMin = 15;
  const yMax = 85;
  const y = (cm: number) => pad.t + (1 - (Math.min(yMax, Math.max(yMin, cm)) - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);
  const t0 = pts[0]?.t ?? 0;
  const t1 = pts[pts.length - 1]?.t ?? 1;
  const x = (t: number) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - pad.l - pad.r);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'} ${x(p.t).toFixed(1)} ${y(p.d).toFixed(1)}`).join(' ');
  const area = pts.length ? `${line} L ${x(t1)} ${H - pad.b} L ${x(t0)} ${H - pad.b} Z` : '';
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Viewing distance over this session">
      <defs>
        <linearGradient id="areaG" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#3b8ff6" stopOpacity="0.32" />
          <stop offset="1" stopColor="#2fd3c4" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="lineG" x1="0" x2="1">
          <stop offset="0" stopColor="#2fd3c4" />
          <stop offset="1" stopColor="#3b6cf6" />
        </linearGradient>
      </defs>
      <rect x={pad.l} y={y(70)} width={W - pad.l - pad.r} height={y(40) - y(70)} fill="var(--zone-good)" opacity="0.1" />
      <rect x={pad.l} y={y(30)} width={W - pad.l - pad.r} height={y(yMin) - y(30)} fill="var(--zone-bad)" opacity="0.1" />
      {[20, 30, 40, 50, 60, 70, 80].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeDasharray={v === 30 ? '0' : '3 5'} />
          <text x={pad.l - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--muted)" fontWeight="700">
            {v}
          </text>
        </g>
      ))}
      {pts.length > 1 && (
        <>
          <path d={area} fill="url(#areaG)" />
          <path d={line} fill="none" stroke="url(#lineG)" strokeWidth="3" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </>
      )}
      {pts.length < 2 && (
        <text x={W / 2} y={H / 2} textAnchor="middle" fill="var(--muted)" fontSize="14" fontWeight="700">
          Waiting for distance readings
        </text>
      )}
    </svg>
  );
}

/** Tiny markdown: headings, quotes, bullet/numbered lists, bold, paragraphs. Escapes everything else. */
export function Markdown({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it)}</li>);
    out.push(list.ordered ? <ol key={out.length}>{items}</ol> : <ul key={out.length}>{items}</ul>);
    list = null;
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    let m: RegExpMatchArray | null;
    if ((m = l.match(/^\s*[-*]\s+(.*)$/))) {
      if (!list || list.ordered) {
        flush();
        list = { ordered: false, items: [] };
      }
      list.items.push(m[1]);
      continue;
    }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (!list || !list.ordered) {
        flush();
        list = { ordered: true, items: [] };
      }
      list.items.push(m[1]);
      continue;
    }
    flush();
    if (!l.trim()) continue;
    if ((m = l.match(/^#{1,6}\s+(.*)$/))) out.push(<h2 key={out.length}>{inline(m[1])}</h2>);
    else if ((m = l.match(/^>\s?(.*)$/))) out.push(<blockquote key={out.length}>{inline(m[1])}</blockquote>);
    else out.push(<p key={out.length}>{inline(l)}</p>);
  }
  flush();
  return <div className="md">{out}</div>;
}

function inline(s: string): ReactNode[] {
  const parts = s.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => (p.startsWith('**') && p.endsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>));
}
