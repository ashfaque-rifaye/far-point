import { useEffect, useMemo, useRef, useState } from 'react';
import type { SignalsData } from '../contract';

/**
 * The living eye. Everything here is drawn from the measured numbers:
 *  - lid aperture follows `squint` (1.0 = your calibrated baseline)
 *  - pupil follows room light, and narrows a little at near distance (the near reflex)
 *  - the iris looks aside when you look away from the screen
 *  - blink rate follows `blink_per_min`
 *  - the dial around it is your viewing distance, 20-80 cm
 * No camera frame reaches the browser; this is a drawing, not a picture of you.
 */

const D_MIN = 20;
const D_MAX = 80;
const A0 = -200; // dial start angle (deg, 0 = east, counter-clockwise negative)
const A1 = 20;

/** Frame-rate independent easing toward `target`; `rate` is roughly 1/time-constant in seconds. */
function useSpring(target: number, rate = 6) {
  const [v, setV] = useState(target);
  const cur = useRef(target);
  const goal = useRef(target);
  goal.current = target;
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = Math.min(0.5, (now - last) / 1000);
      last = now;
      const d = goal.current - cur.current;
      if (Math.abs(d) > 0.0005) {
        cur.current += d * (1 - Math.exp(-dt * rate));
        setV(cur.current);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [rate]);
  return v;
}

const rad = (deg: number) => (deg * Math.PI) / 180;
const polar = (r: number, deg: number) => [Math.cos(rad(deg)) * r, Math.sin(rad(deg)) * r] as const;
const angleFor = (cm: number) => A0 + ((Math.min(D_MAX, Math.max(D_MIN, cm)) - D_MIN) / (D_MAX - D_MIN)) * (A1 - A0);

function arc(r: number, a: number, b: number) {
  const [x0, y0] = polar(r, a);
  const [x1, y1] = polar(r, b);
  const large = Math.abs(b - a) > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

export function Iris({ s, compact = false }: { s?: SignalsData; compact?: boolean }) {
  const face = s?.face ?? false;
  const squint = face ? Math.max(0.45, Math.min(1.08, s?.squint ?? 1)) : 0.9;
  const dist = s?.distance_cm ?? null;
  const ambient = s?.ambient ?? 'normal';
  const pupilBase = { dark: 0.44, dim: 0.37, normal: 0.3, bright: 0.24 }[ambient];
  const nearPull = dist !== null ? Math.max(0, (45 - dist) / 25) * 0.05 : 0;
  const pupil = useSpring(pupilBase - nearPull, 2.5);
  const gaze = useSpring(s?.looking_at_screen === false ? 46 : 0, 4);
  const aperture = useSpring(squint, 7);
  const needle = useSpring(dist ?? 50, 5);

  const [blink, setBlink] = useState(false);
  const bpm = Math.max(4, Math.min(30, s?.blink_per_min ?? 14));
  useEffect(() => {
    let to = 0;
    const loop = () => {
      to = window.setTimeout(() => {
        setBlink(true);
        window.setTimeout(() => setBlink(false), 130);
        loop();
      }, (60000 / bpm) * (0.6 + Math.random() * 0.8));
    };
    loop();
    return () => window.clearTimeout(to);
  }, [bpm]);

  const fibers = useMemo(() => {
    const out: { a: number; r0: number; r1: number; w: number; o: number; c: number }[] = [];
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 180; i++) {
      out.push({ a: (i / 180) * 360 + rnd() * 2, r0: 0.34 + rnd() * 0.08, r1: 0.82 + rnd() * 0.17, w: 0.6 + rnd() * 1.8, o: 0.25 + rnd() * 0.55, c: rnd() });
    }
    return out;
  }, []);

  const W = 600;
  const H = 600;
  const eyeW = compact ? 190 : 205;
  const open = Math.pow(Math.max(0, Math.min(1, (aperture - 0.45) / 0.55)), 1.25) * 0.82 + 0.18;
  const lidH = 128 * (blink ? 0.04 : open);
  const irisR = 92;
  const lidPath = `M ${-eyeW} 0 C ${-eyeW * 0.55} ${-lidH * 1.25}, ${eyeW * 0.55} ${-lidH * 1.25}, ${eyeW} 0 C ${eyeW * 0.55} ${lidH * 1.02}, ${-eyeW * 0.55} ${lidH * 1.02}, ${-eyeW} 0 Z`;
  const R = 262;
  const zones = [
    { from: 20, to: 30, c: 'var(--zone-bad)' },
    { from: 30, to: 40, c: 'var(--zone-close)' },
    { from: 40, to: 70, c: 'var(--zone-good)' },
    { from: 70, to: 80, c: 'var(--muted)' },
  ];
  const needleA = angleFor(needle);
  const [nx, ny] = polar(R, needleA);
  const ticks = [20, 30, 40, 50, 60, 70, 80];
  const glasses = s?.glasses_on;

  return (
    <svg className="stage-svg" viewBox={`${-W / 2} ${-H / 2 + 20} ${W} ${H}`} role="img" aria-label={dist !== null ? `Viewing distance ${dist.toFixed(0)} centimetres` : 'No face in view'}>
      <defs>
        <radialGradient id="irisG" cx="0" cy="0" r={irisR} gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0b2d44" />
          <stop offset="0.42" stopColor="#127a86" />
          <stop offset="0.7" stopColor="#2fb6c4" />
          <stop offset="0.92" stopColor="#2c63c9" />
          <stop offset="1" stopColor="#0d1b3a" />
        </radialGradient>
        <radialGradient id="scleraG" cx="0" cy="-20" r="230" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--sclera)" />
          <stop offset="0.75" stopColor="var(--sclera)" />
          <stop offset="1" stopColor="#c9d3e6" />
        </radialGradient>
        <linearGradient id="dialG" x1="0" x2="1">
          <stop offset="0" stopColor="#2fd3c4" />
          <stop offset="1" stopColor="#3b6cf6" />
        </linearGradient>
        <clipPath id="lidClip">
          <path d={lidPath} />
        </clipPath>
        <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="10" />
        </filter>
      </defs>

      {/* distance dial */}
      <g aria-hidden="true">
        <path d={arc(R, A0, A1)} stroke="var(--line)" strokeWidth="22" fill="none" strokeLinecap="round" />
        {zones.map((z) => (
          <path key={z.from} d={arc(R, angleFor(z.from), angleFor(z.to))} stroke={z.c} strokeWidth="8" fill="none" opacity={z.from === 70 ? 0.35 : 0.9} />
        ))}
        {ticks.map((t) => {
          const [x0, y0] = polar(R - 24, angleFor(t));
          const [x1, y1] = polar(R - 34, angleFor(t));
          const [lx, ly] = polar(R - 54, angleFor(t));
          return (
            <g key={t}>
              <line x1={x0} y1={y0} x2={x1} y2={y1} stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" />
              <text x={lx} y={ly + 4} textAnchor="middle" fontSize="13" fontWeight="700" fill="var(--muted)" fontFamily="Manrope">
                {t}
              </text>
            </g>
          );
        })}
        {dist !== null && (
          <g>
            <circle cx={nx} cy={ny} r="20" fill="var(--card)" stroke="url(#dialG)" strokeWidth="5" />
            <circle cx={nx} cy={ny} r="7" fill="url(#dialG)" />
          </g>
        )}
      </g>

      {/* eye */}
      <g>
        <ellipse cx="0" cy="18" rx={eyeW * 0.92} ry="38" fill="#0d1b2a" opacity="0.18" filter="url(#soft)" />
        <path d={lidPath} fill="url(#scleraG)" />
        <g clipPath="url(#lidClip)">
          <g transform={`translate(${gaze} 0)`}>
            <circle r={irisR} fill="url(#irisG)" />
            {fibers.map((f, i) => {
              const [x0, y0] = polar(irisR * f.r0, f.a);
              const [x1, y1] = polar(irisR * f.r1, f.a + 3);
              return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} stroke={f.c > 0.6 ? '#8ff3ea' : f.c > 0.3 ? '#5fc8e6' : '#0b3550'} strokeOpacity={f.o * 0.55} strokeWidth={f.w} />;
            })}
            <circle r={irisR} fill="none" stroke="#071426" strokeWidth="7" opacity="0.85" />
            <circle r={irisR * pupil * 1.45} fill="#05080f" />
            <circle r={irisR * pupil * 1.45 + 5} fill="none" stroke="#36d6c8" strokeOpacity="0.35" strokeWidth="3" />
            <ellipse cx="30" cy="-34" rx="17" ry="12" fill="#fff" opacity="0.92" transform="rotate(-24 30 -34)" />
            <circle cx="-26" cy="30" r="5" fill="#fff" opacity="0.45" />
          </g>
          <path d={lidPath} fill="none" stroke="#0d1b2a" strokeOpacity="0.08" strokeWidth="24" />
        </g>
        <path d={lidPath} fill="none" stroke="var(--ink)" strokeOpacity="0.55" strokeWidth="3" />
        {glasses === true && (
          <rect x={-eyeW - 26} y={-140} width={(eyeW + 26) * 2} height={262} rx="110" fill="none" stroke="var(--ink)" strokeOpacity="0.28" strokeWidth="5" strokeDasharray="2 0" />
        )}
      </g>

      {!face && (
        <text x="0" y="200" textAnchor="middle" fontSize="18" fontWeight="700" fill="var(--muted)" fontFamily="Manrope">
          No face in view
        </text>
      )}
    </svg>
  );
}
