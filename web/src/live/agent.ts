/**
 * Live mode for the hosted page: the Myrmidon loop in the visitor's browser.
 *
 * - Measure: MediaPipe Face Landmarker on the visitor's webcam, in this tab (WebAssembly, frames
 *   never leave the device). Distance from iris width, eye opening against a learned baseline,
 *   blinks, head turn, room light: the same maths as myrmidon/sense.py and signals.py.
 * - Decide: the same verdict sentences (myrmidon/facts.py) and the same typed questions
 *   (patterns/reflex_gate) go to Strands Decider 2B on AWS (SageMaker Serverless behind a capped
 *   Lambda proxy, VITE_DECIDER_URL); code applies the priority order
 *   and the fire / unsure / clear thresholds. Unsure means stay quiet (no Bedrock here).
 * - Act: reversible changes to this page only (text zoom, dark theme, a far-look break verified by
 *   the camera), behind the same interrupt gate. Verify 30 s later.
 * Everything is emitted as the backend's contract events, so every dashboard screen works unchanged.
 */
import { FaceLandmarker, FilesetResolver, type NormalizedLandmark } from '@mediapipe/tasks-vision';
import type { ClientCommand, ServerEvent, ServerEventDataMap, ServerEventType, Tool } from '../contract';
import { ingest, pushToast, setState } from '../store';
import doctrineJson from './doctrine.json';

// The capped public front door from scripts/deploy_decider_sagemaker.py; VITE_DECIDER_URL overrides it.
const DECIDER_URL = (import.meta.env.VITE_DECIDER_URL as string | undefined) ?? 'https://6oyyvmmguamqnpylrvlwydi6hu0iuslr.lambda-url.us-east-1.on.aws/';
const IRIS_MM = 11.7;
const RIGHT_IRIS_H = [469, 471];
const LEFT_IRIS_H = [474, 476];
const RIGHT_EYE = [33, 160, 158, 133, 153, 144];
const LEFT_EYE = [362, 385, 387, 263, 373, 380];
const FIRE_P = 0.65;
const CLEAR_P = 0.35;
const INTERRUPT_P = 0.5;
const VERIFY_S = 30;
const BREAK_S = 20;
const ZOOM_CAP = 3;
const COOLDOWN_S = 30;
const INTERRUPTIVE: Tool[] = ['far_look_break', 'glasses_reminder', 'ask_user'];

type Rule = { n: number; tool: Tool; text: string; when_true: string; when_false: string; basis: string };
// Live demo pace: the desktop default is a break after 45 min of near work; a visitor will not wait that long.
const L = { ...doctrineJson.limits, bout_min: 2 };
const RULES = doctrineJson.rules as Rule[];

function send<K extends ServerEventType>(type: K, data: ServerEventDataMap[K]) {
  ingest({ v: 1, type, t: Date.now(), data } as ServerEvent);
}

/* ------------------------------------------------------------------ measuring */
let landmarker: FaceLandmarker | null = null;
let video: HTMLVideoElement | null = null;
let stream: MediaStream | null = null;
const lumaCanvas = document.createElement('canvas');
lumaCanvas.width = 32;
lumaCanvas.height = 24;

const dist = (a: NormalizedLandmark, b: NormalizedLandmark, w: number, h: number) => Math.hypot((a.x - b.x) * w, (a.y - b.y) * h);
const median = (xs: number[]) => {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};

function earOf(p: NormalizedLandmark[], idx: number[], w: number, h: number) {
  const [p1, p2, p3, p4, p5, p6] = idx.map((i) => p[i]);
  return (dist(p2, p6, w, h) + dist(p3, p5, w, h)) / (2 * dist(p1, p4, w, h));
}

function yawOf(p: NormalizedLandmark[]) {
  // nose tip against the midpoint of the face edges: about +/-60 degrees at a full profile
  const left = p[234];
  const right = p[454];
  const half = Math.abs(right.x - left.x) / 2 || 1e-3;
  return Math.max(-90, Math.min(90, ((p[1].x - (left.x + right.x) / 2) / half) * 60));
}

function frameLuma(v: HTMLVideoElement): number | null {
  const ctx = lumaCanvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(v, 0, 0, 32, 24);
  const d = ctx.getImageData(0, 0, 32, 24).data;
  let s = 0;
  for (let i = 0; i < d.length; i += 4) s += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
  return s / (d.length / 4);
}

/* ------------------------------------------------------------------ the loop's state */
const st = {
  running: false,
  focal: 0, // px; from an assumed 60-degree field of view until the visitor calibrates
  calibrated: false,
  earBase: 0,
  earSamples: [] as number[],
  irisHist: [] as number[],
  ratioHist: [] as number[],
  face: false,
  d: null as number | null,
  ratio: null as number | null,
  rawRatio: null as number | null,
  yaw: 0,
  luma: null as number | null,
  underNear: 0,
  bout: 0,
  awayFor: 0,
  squinting: false,
  squintS: 0,
  relaxed: 0,
  inBlink: false,
  blinkS: 0,
  blinks: [] as number[],
  observedS: 0,
  under30Today: 0,
  zoom: 0,
  dark: false,
  lastKey: 0,
  lastTool: {} as Record<string, number>,
  breakId: '',
  breakAway: 0,
  breakStart: 0,
  seq: 0,
  latencies: [] as number[],
  stats: { decisions: 0, adaptations: 0, adaptations_worked: 0, breaks_offered: 0, breaks_verified: 0, squint_episodes: 0 },
  lastFrame: 0,
  deciding: false,
  warm: false,
  limited: false,
  fallbackSince: 0,
};

function room(): 'dark' | 'dim' | 'normal' | 'bright' {
  const y = st.luma ?? 120;
  return y < 45 ? 'dark' : y < 80 ? 'dim' : y < 185 ? 'normal' : 'bright';
}

function band(d: number | null) {
  if (d == null) return 'healthy' as const;
  return d < 30 ? ('too_close' as const) : d < 40 ? ('close' as const) : d <= 70 ? ('healthy' as const) : ('far' as const);
}

function measure(now: number, dt: number) {
  if (!landmarker || !video || video.readyState < 2) return;
  const w = video.videoWidth;
  const h = video.videoHeight;
  const res = landmarker.detectForVideo(video, now);
  const p = res.faceLandmarks?.[0];
  st.luma = frameLuma(video);
  st.face = !!p;
  if (!p) {
    st.d = null;
    st.ratio = st.rawRatio = null;
    st.underNear = 0;
    st.squinting = false;
    st.squintS = 0;
  } else {
    if (!st.focal) st.focal = w / 2 / Math.tan((30 * Math.PI) / 180);
    const iris = (dist(p[RIGHT_IRIS_H[0]], p[RIGHT_IRIS_H[1]], w, h) + dist(p[LEFT_IRIS_H[0]], p[LEFT_IRIS_H[1]], w, h)) / 2;
    const ear = (earOf(p, RIGHT_EYE, w, h) + earOf(p, LEFT_EYE, w, h)) / 2;
    st.yaw = yawOf(p);
    st.irisHist = [...st.irisHist.slice(-9), iris];
    st.d = (st.focal * IRIS_MM) / median(st.irisHist) / 10;
    // Baseline: the visitor's own normal eye opening, learned over the first seconds facing the camera.
    if (!st.earBase && Math.abs(st.yaw) < 20) {
      st.earSamples.push(ear);
      if (st.earSamples.length >= 40) st.earBase = median(st.earSamples) * 1.03;
    }
    if (st.earBase) {
      st.rawRatio = ear / st.earBase;
      st.ratioHist = [...st.ratioHist.slice(-14), st.rawRatio];
      st.ratio = median(st.ratioHist);
    }
  }
  const d = st.d;
  st.underNear = d != null && d < L.near_cm ? st.underNear + dt : 0;
  if (d != null && d < 30) st.under30Today += dt;
  // Near-work bout: time closer than bout_cm, reset by bout_reset_s away or farther.
  if (d != null && d < L.bout_cm) {
    st.bout += dt;
    st.awayFor = 0;
  } else {
    st.awayFor += dt;
    if (st.awayFor >= L.bout_reset_s) st.bout = 0;
  }
  const sq = st.ratio != null && st.ratio < L.squint_ratio;
  if (sq) {
    st.squintS += dt;
    if (!st.squinting && st.squintS >= L.squint_s) {
      st.squinting = true;
      st.stats.squint_episodes += 1;
    }
  } else {
    st.squintS = 0;
    st.squinting = false;
  }
  st.relaxed = d != null && d >= L.relaxed_cm && !st.squinting ? st.relaxed + dt : 0;
  // Blinks on the raw eye opening: under 0.6 x baseline starts one, back over 0.7 ends it.
  if (st.rawRatio != null) {
    st.observedS = Math.min(60, st.observedS + dt);
    if (!st.inBlink && st.rawRatio < 0.6) {
      st.inBlink = true;
      st.blinkS = 0;
    } else if (st.inBlink) {
      st.blinkS += dt;
      if (st.rawRatio > 0.7) {
        st.inBlink = false;
        if (st.blinkS < 1) st.blinks.push(now);
      }
    }
  }
  st.blinks = st.blinks.filter((t) => now - t < 60000);
}

function blinkPerMin(): number | null {
  return st.observedS >= 20 ? (st.blinks.length * 60) / st.observedS : null;
}

function emitSignals() {
  send('signals', {
    face: st.face,
    distance_cm: st.d == null ? null : Math.round(st.d * 10) / 10,
    distance_band: band(st.d),
    squint: st.ratio == null ? null : Math.round(st.ratio * 1000) / 1000,
    squinting: st.squinting,
    blink_per_min: blinkPerMin() == null ? null : Math.round(blinkPerMin()!),
    looking_at_screen: st.face ? Math.abs(st.yaw) < 25 : false,
    ambient: room(),
    glasses_on: null,
    bout_s: Math.round(st.bout),
    under30_today_s: Math.round(st.under30Today),
    app: { name: 'this page', category: 'browser', zoom_step: st.zoom },
  } as never);
}

/* ------------------------------------------------------------------ facts in words (myrmidon/facts.py) */
const n0 = (x: number) => x.toFixed(0);

function activity(): [string, boolean] {
  const sinceKey = (Date.now() - st.lastKey) / 1000;
  if (sinceKey < 3) return ['typing in a burst', false];
  if (document.hidden) return ['between tasks (this tab is in the background)', true];
  return [`idle, reading this page (no typing for ${n0(Math.min(sinceKey, 999))} s)`, true];
}

/**
 * The desktop renderer's lines, word for word. `asked` is the rules in this request: lines that no
 * asked rule reads (glasses, screen brightness, clock) are left out to save CPU time on the hosted
 * Decider; the Activity line always stays for interrupt_ok.
 */
function renderState(asked: Set<Tool> = new Set(RULES.map((r) => r.tool))): string {
  const lines = ['Measured now (code computed every number and comparison):'];
  const d = st.d;
  const tooClose = st.face && d != null && d < L.near_cm && st.underNear > L.near_s;
  if (!st.face || d == null) lines.push('- Viewing distance: no face visible.');
  else if (tooClose)
    lines.push(`- Viewing distance: ${n0(d)} cm, under ${n0(L.near_cm)} cm for ${n0(st.underNear)} s (limit ${n0(L.near_s)} s): too close, enlarging needed.`);
  else if (d < L.near_cm)
    lines.push(`- Viewing distance: ${n0(d)} cm for ${n0(st.underNear)} s (limit ${n0(L.near_s)} s under ${n0(L.near_cm)} cm): no enlarging needed yet.`);
  else lines.push(`- Viewing distance: ${n0(d)} cm: no enlarging needed.`);
  const boutMin = st.bout / 60;
  lines.push(`- Near-work bout: ${n0(boutMin)} min closer than ${n0(L.bout_cm)} cm (break due at ${n0(L.bout_min)} min): ${boutMin >= L.bout_min ? 'break is due.' : 'break not due yet.'}`);
  if (!st.face || st.ratio == null) lines.push('- Eyes: not measured (no face visible).');
  else if (st.squinting) lines.push(`- Eyes: squinting for ${n0(st.squintS)} s (eye opening ${n0(st.ratio * 100)}% of your baseline).`);
  else lines.push(`- Eyes: not squinting (eye opening ${n0(st.ratio * 100)}% of your baseline).`);
  const b = blinkPerMin();
  lines.push(b == null ? '- Blink rate: still measuring.' : `- Blink rate: ${n0(b)} per minute (normal is ${n0(L.low_blink_per_min)} or more): ${b < L.low_blink_per_min ? 'low.' : 'normal.'}`);
  if (asked.has('glasses_reminder'))
    lines.push('- Glasses: prescribed for screen work: unknown; worn: not checked (text-only mode); signs consistent with glasses off: no (usual distance not learned yet): no reminder needed.');
  const r = room();
  lines.push(`- Room light: ${{ dark: 'dark', dim: 'dim', normal: 'normal indoor light', bright: 'bright' }[r]} (estimated from camera brightness).`);
  lines.push(r === 'dark' && !st.dark ? '- Theme: light, in a dark room: mismatch, dark mode needed.' : `- Theme: ${st.dark ? 'dark' : 'light'}: no change needed.`);
  if (asked.has('dim_screen') || asked.has('brighten_screen')) lines.push('- Screen brightness: not adjustable on this display.');
  const z = `${st.zoom >= 0 ? '+' : ''}${st.zoom}`;
  lines.push(`- Text zoom: Myrmidon zoom ${z} in this page (browser); zoom control available.`);
  const relaxedMin = st.relaxed / 60;
  lines.push(`- Relaxed reading: ${n0(relaxedMin)} min at ${n0(L.relaxed_cm)} cm or more without squinting (limit ${n0(L.relaxed_min)} min), Myrmidon zoom ${z}: ${st.zoom > 0 && relaxedMin >= L.relaxed_min ? 'text can go back one step.' : 'no change needed.'}`);
  lines.push(st.squinting && st.squintS > 60 && st.zoom >= 2
    ? `- Squint despite zoom: squinting for ${n0(st.squintS)} s at Myrmidon zoom ${z} (ask after 60 s at +2 or more): yes.`
    : '- Squint despite zoom (ask after 60 s of squinting at Myrmidon zoom +2 or more): no.');
  const [act, ok] = activity();
  lines.push(`- Activity: ${act}: ${ok ? 'a good moment to interrupt' : 'not a good moment to interrupt'}.`);
  return lines.join('\n');
}

/* ------------------------------------------------------------------ questions + policy (patterns/reflex_gate) */
function skipReason(r: Rule): string | null {
  const since = (Date.now() - (st.lastTool[r.tool] ?? 0)) / 1000;
  if (since < COOLDOWN_S) return 'cooldown';
  if (r.tool === 'enlarge_text' && st.zoom >= ZOOM_CAP) return 'zoom at cap';
  if (r.tool === 'reduce_text' && st.zoom <= 0) return 'nothing to undo';
  if (r.tool === 'dark_mode' && st.dark) return 'already dark';
  if (r.tool === 'far_look_break' && st.breakId) return 'break running';
  if (r.tool === 'dim_screen' || r.tool === 'brighten_screen') return 'not adjustable in a browser';
  if (r.tool === 'glasses_reminder') return 'glasses not prescribed';
  return null;
}

let lastErrorToast = 0;

/**
 * Fallback while the hosted Decider is unavailable (not deployed yet, warming up, over budget):
 * the conditions code already used to write each verdict line, as crisp 0.99 / 0.01 answers.
 * Decisions made this way carry source 'fallback' and say so in the reason.
 */
function codeAnswers(candidates: Rule[]): Record<string, { noul: number }> {
  const d = st.d;
  const truth: Partial<Record<Tool, boolean>> = {
    enlarge_text: st.face && d != null && d < L.near_cm && st.underNear > L.near_s,
    dark_mode: room() === 'dark' && !st.dark,
    far_look_break: st.bout / 60 >= L.bout_min,
    reduce_text: st.zoom > 0 && st.relaxed / 60 >= L.relaxed_min,
    ask_user: st.squinting && st.squintS > 60 && st.zoom >= 2,
  };
  const out: Record<string, { noul: number }> = {};
  candidates.forEach((r) => (out[`rule_${r.n}`] = { noul: truth[r.tool] ? 0.99 : 0.01 }));
  out.interrupt_ok = { noul: activity()[1] ? 0.99 : 0.01 };
  return out;
}

function fallback(stateText: string, candidates: Rule[], skipped: unknown[], before: { distance_cm: number | null; squint: number | null }, why: string) {
  if (!st.fallbackSince) {
    st.fallbackSince = Date.now();
    helloLive('down', `${why}; deciding with code rules until it answers`);
  }
  handleAnswers(stateText, codeAnswers(candidates), candidates, skipped, 0, before, 'fallback');
}

async function decide() {
  if (st.deciding || !st.running) return;
  st.deciding = true;
  const candidates = RULES.filter((r) => !skipReason(r));
  const stateText = renderState(new Set(candidates.map((r) => r.tool)));
  if (!DECIDER_URL || st.limited) {
    fallback(stateText, candidates, [], { distance_cm: st.d, squint: st.ratio },
      st.limited ? 'hosted Decider budget used up' : 'no hosted Decider configured');
    st.deciding = false;
    return;
  }
  const skipped = RULES.filter((r) => skipReason(r)).map((r) => ({ n: r.n, tool: r.tool, reason: skipReason(r) }));
  const questions: Record<string, unknown> = {};
  candidates.forEach((r) => {
    questions[`rule_${r.n}`] = {
      type: 'noul',
      instructions: `Does rule ${r.n} apply right now? Rule ${r.n}: ${r.text}`,
      criteria: { true: r.when_true, false: r.when_false },
    };
  });
  questions.interrupt_ok = { ...doctrineJson.interrupt_ok, criteria: { ...doctrineJson.interrupt_ok.criteria } };
  const before = { distance_cm: st.d, squint: st.ratio };
  const t0 = performance.now();
  try {
    const r = await fetch(DECIDER_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ state: stateText, questions }),
    });
    const body = await r.json();
    if (r.status === 429) {
      if (!st.limited) pushToast('warning', `${body?.detail ?? 'The hosted Decider has used its free budget.'} Deciding with code rules meanwhile.`);
      st.limited = true;
      fallback(stateText, candidates, skipped, before, 'hosted Decider budget used up');
      return;
    }
    if (r.status === 503) {
      // not deployed yet, or a cold start loading the model: decide with code rules and keep asking
      fallback(stateText, candidates, skipped, before,
        body?.error === 'not_deployed' ? 'hosted Decider not running yet' : 'hosted Decider warming up (about 1-2 min)');
      return;
    }
    if (!r.ok) throw new Error(body?.detail || `HTTP ${r.status}`);
    if (!st.warm || st.fallbackSince) {
      st.warm = true;
      st.fallbackSince = 0;
      helloLive('ready');
    }
    const ms = body.latency_ms ?? performance.now() - t0;
    st.latencies = [...st.latencies.slice(-49), ms];
    handleAnswers(stateText, body.answers, candidates, skipped, ms, before);
  } catch (e) {
    if (Date.now() - lastErrorToast > 60000) {
      lastErrorToast = Date.now();
      pushToast('warning', `Hosted Decider unreachable (${(e as Error).message}); deciding with code rules meanwhile.`);
    }
    fallback(stateText, candidates, skipped, before, 'hosted Decider unreachable');
  } finally {
    st.deciding = false;
  }
}

function handleAnswers(stateText: string, answers: Record<string, { noul: number }>, candidates: Rule[], skipped: unknown[], ms: number,
  before: { distance_cm: number | null; squint: number | null }, source: 'decider' | 'fallback' = 'decider') {
  const pInt = answers.interrupt_ok?.noul ?? 0;
  const rules = candidates.map((r) => {
    const p = answers[`rule_${r.n}`]?.noul ?? 0;
    return { n: r.n, tool: r.tool, p: Math.round(p * 1000) / 1000, state: p >= FIRE_P ? 'fires' : p <= CLEAR_P ? 'clear' : 'unsure', escalated: null };
  });
  // Walk the rules in priority order: the first one that fires wins, unless a rule above it is unsure.
  let winner: (typeof rules)[number] | null = null;
  let unsureAbove = false;
  for (const r of rules) {
    if (r.state === 'fires') {
      winner = r;
      break;
    }
    if (r.state === 'unsure') unsureAbove = true;
  }
  const act = winner && !unsureAbove;
  const probs: Record<string, number> = {};
  let none = 1;
  rules.forEach((r) => {
    probs[r.tool] = Math.max(probs[r.tool] ?? 0, r.p);
    none *= 1 - r.p;
  });
  probs.none = none;
  const sum = Object.values(probs).reduce((a, b) => a + b, 0) || 1;
  Object.keys(probs).forEach((k) => (probs[k] /= sum));
  const id = `d_live${++st.seq}`;
  const signs = [st.squinting, rules.some((r) => r.tool === 'enlarge_text' && r.state === 'fires'), st.bout / 60 >= L.bout_min].filter(Boolean).length;
  const level = signs >= 2 ? 'strong' : signs === 1 ? 'mild' : 'relaxed';
  const tag = source === 'fallback' ? ' [code rules: hosted Decider not available]' : '';
  send('decision', {
    id,
    latency_ms: Math.round(ms),
    source,
    state_text: stateText,
    answers: {
      next_action: { choice: act ? winner!.tool : 'none', confidence: act ? winner!.p : none, probs },
      strain: { level, expected: Math.min(signs, 2), probs: { relaxed: +(level === 'relaxed'), mild: +(level === 'mild'), strong: +(level === 'strong') } },
      interrupt_ok: { p: Math.round(pInt * 1000) / 1000 },
      rules,
    },
    policy: act ? 'act' : 'quiet',
    rule_ref: act ? `rule ${winner!.n}` : undefined,
    reason: (act ? `rule ${winner!.n} fires (p=${winner!.p.toFixed(2)})` : winner ? 'a higher rule is unsure: stay quiet' : 'no rule applies') + tag,
    skipped,
  } as never);
  st.stats.decisions += 1;
  if (act) runTool(id, winner!.tool, pInt, before);
  emitStats();
}

/* ------------------------------------------------------------------ tools (reversible, this page only) */
function applyPage() {
  (document.body.style as CSSStyleDeclaration & { zoom: string }).zoom = String(1 + 0.12 * st.zoom);
}

function runTool(decisionId: string, tool: Tool, pInt: number, before: { distance_cm: number | null; squint: number | null }) {
  const aid = `a_live${st.seq}`;
  if (INTERRUPTIVE.includes(tool) && pInt < INTERRUPT_P) {
    send('action', { id: aid, decision_id: decisionId, tool, args: {}, gate: { name: 'InterruptGate', verdict: 'deny', p: pInt }, status: 'denied',
      message: 'Held back: not a good moment to interrupt.' } as never);
    st.lastTool[tool] = Date.now();
    return;
  }
  st.lastTool[tool] = Date.now();
  let message = '';
  if (tool === 'enlarge_text') {
    st.zoom = Math.min(ZOOM_CAP, st.zoom + 1);
    applyPage();
    message = 'Text one step larger on this page, so you can sit back.';
  } else if (tool === 'reduce_text') {
    st.zoom = Math.max(0, st.zoom - 1);
    applyPage();
    message = 'Text back one step: you have been reading comfortably.';
  } else if (tool === 'dark_mode') {
    st.dark = true;
    window.dispatchEvent(new CustomEvent('myrmidon:theme', { detail: 'night' }));
    message = 'Switched this page to dark mode: less glare in a dark room.';
  } else if (tool === 'far_look_break') {
    st.breakId = `b_live${st.seq}`;
    st.breakAway = 0;
    st.breakStart = Date.now();
    st.stats.breaks_offered += 1;
    send('break', { id: st.breakId, phase: 'offered', target_s: BREAK_S, looking_away_s: 0, streak: st.stats.breaks_verified } as never);
    message = 'Time for a 20-second far look.';
  } else if (tool === 'ask_user') {
    pushToast('info', 'Still squinting with larger text. Do you need your glasses, or a break?');
    message = 'Asked you instead of guessing.';
  } else {
    message = `${tool} is not available in a browser.`;
  }
  send('action', { id: aid, decision_id: decisionId, tool, args: tool.endsWith('_text') ? { steps: 1 } : {},
    gate: { name: INTERRUPTIVE.includes(tool) ? 'InterruptGate' : null, verdict: INTERRUPTIVE.includes(tool) ? 'proceed' : null,
      p: INTERRUPTIVE.includes(tool) ? pInt : null }, status: 'done', message } as never);
  st.stats.adaptations += 1;
  if (tool === 'enlarge_text' || tool === 'dark_mode' || tool === 'reduce_text') {
    window.setTimeout(() => {
      const after = { distance_cm: st.d, squint: st.ratio };
      const bd = before.distance_cm;
      const ad = after.distance_cm;
      const worked = (bd != null && ad != null && bd < 40 && ad >= 40) ||
        (before.squint != null && after.squint != null && after.squint - before.squint >= 0.1);
      if (worked) st.stats.adaptations_worked += 1;
      send('verification', {
        action_id: aid,
        outcome: worked ? 'worked' : tool === 'reduce_text' ? 'n/a' : 'no_change',
        before: { distance_cm: bd == null ? null : Math.round(bd * 10) / 10, squint: before.squint == null ? null : Math.round(before.squint * 100) / 100 },
        after: { distance_cm: ad == null ? null : Math.round(ad * 10) / 10, squint: after.squint == null ? null : Math.round(after.squint * 100) / 100 },
        window_s: VERIFY_S,
      } as never);
    }, VERIFY_S * 1000);
  }
}

function tickBreak(dt: number) {
  if (!st.breakId) return;
  const away = !st.face || Math.abs(st.yaw) > 25;
  if (away) st.breakAway += dt;
  const phase = st.breakAway >= BREAK_S ? 'verified' : st.breakAway > 0 ? 'tick' : 'offered';
  if (phase === 'verified') {
    st.stats.breaks_verified += 1;
    st.bout = 0;
    send('break', { id: st.breakId, phase: 'verified', target_s: BREAK_S, looking_away_s: BREAK_S, streak: st.stats.breaks_verified } as never);
    st.breakId = '';
  } else {
    send('break', { id: st.breakId, phase, target_s: BREAK_S, looking_away_s: Math.round(st.breakAway * 10) / 10, streak: st.stats.breaks_verified } as never);
  }
}

function emitStats() {
  const lat = [...st.latencies].sort((a, b) => a - b);
  send('stats', {
    day: new Date().toISOString().slice(0, 10),
    under30_min: Math.round((st.under30Today / 60) * 10) / 10,
    longest_bout_min: Math.round(st.bout / 6) / 10,
    breaks_offered: st.stats.breaks_offered,
    breaks_verified: st.stats.breaks_verified,
    squint_episodes: st.stats.squint_episodes,
    glasses_off_min: 0,
    adaptations: st.stats.adaptations,
    adaptations_worked: st.stats.adaptations_worked,
    streak: st.stats.breaks_verified,
    decisions: st.stats.decisions,
    decider_p50_ms: lat.length ? Math.round(lat[Math.floor(lat.length / 2)]) : null,
    decider_p95_ms: lat.length ? Math.round(lat[Math.min(lat.length - 1, Math.floor(lat.length * 0.95))]) : null,
    bedrock_calls: 0,
    bedrock_tokens: 0,
    face_images_uploaded: 0,
  } as never);
}

function helloLive(decider: 'ready' | 'loading' | 'down', note = '') {
  send('hello', {
    mode: 'live',
    app_version: '0.2.0 live (browser)',
    profile_name: 'Visitor',
    decider: { status: decider, model: `Strands Decider 2B on AWS (SageMaker Serverless, CPU)${note ? ` · ${note}` : st.warm ? '' : ' · first call loads the model, about 1-2 min'}`, device: 'AWS, CPU', vision: false },
    bedrock: { status: 'off', model: null },
    camera: { status: st.running ? 'on' : 'off' },
  } as never);
}

/* ------------------------------------------------------------------ lifecycle */
let frameTimer = 0;
let decideTimer = 0;

export async function startLive(): Promise<void> {
  if (st.running) return;
  setState({ conn: 'live' } as never);
  helloLive('loading');
  send('doctrine', {
    version: 1,
    source_text: 'Live demo pace: a far-look break is due after 2 min of near work (45 min on the desktop).',
    approved: true,
    rules: RULES.map((r) => ({ n: r.n, text: r.text, basis: r.basis, origin: 'default', status: 'active' })),
  } as never);
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false });
  } catch (e) {
    pushToast('warning', `Camera not available: ${(e as Error).message}`);
    send('hello', { mode: 'live', app_version: '0.2.0 live (browser)', profile_name: 'Visitor',
      decider: { status: 'ready', model: 'Strands Decider 2B on AWS (SageMaker Serverless, CPU)', device: 'AWS, CPU', vision: false },
      bedrock: { status: 'off', model: null }, camera: { status: 'error' } } as never);
    return;
  }
  video = document.createElement('video');
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  await video.play();
  const base = `${import.meta.env.BASE_URL}mediapipe`;
  const fileset = await FilesetResolver.forVisionTasks(base);
  const opts = (delegate: 'GPU' | 'CPU') => ({
    baseOptions: { modelAssetPath: `${base}/face_landmarker.task`, delegate },
    runningMode: 'VIDEO' as const,
    numFaces: 1,
  });
  try {
    landmarker = await FaceLandmarker.createFromOptions(fileset, opts('GPU'));
  } catch {
    landmarker = await FaceLandmarker.createFromOptions(fileset, opts('CPU'));
  }
  st.running = true;
  helloLive('loading');
  window.addEventListener('keydown', onKey);
  st.lastFrame = performance.now();
  let sinceSignals = 0;
  frameTimer = window.setInterval(() => {
    const now = performance.now();
    const dt = Math.min(0.5, (now - st.lastFrame) / 1000);
    st.lastFrame = now;
    measure(now, dt);
    tickBreak(dt);
    sinceSignals += dt;
    if (sinceSignals >= 0.2) {
      sinceSignals = 0;
      emitSignals();
    }
  }, 66);
  // One decision at a time; the next goes 2.5 s after the last answer (the Lambda sets the pace).
  const loop = async () => {
    if (!st.running) return;
    await decide();
    // over budget: code rules every 2.5 s, and ask the hosted Decider again only every 10 minutes
    if (st.limited && Date.now() - st.fallbackSince > 600000) {
      st.limited = false;
      st.fallbackSince = 0;
    }
    decideTimer = window.setTimeout(loop, 2500);
  };
  decideTimer = window.setTimeout(loop, 3000);
  pushToast('info', 'Live: your webcam is measured in this tab only. Hold still for a few seconds while it learns your normal eye opening.');
}

export function stopLive() {
  st.running = false;
  window.clearInterval(frameTimer);
  window.clearTimeout(decideTimer);
  stream?.getTracks().forEach((t) => t.stop());
  st.zoom = 0;
  applyPage();
  window.removeEventListener('keydown', onKey);
}

function onKey() {
  st.lastKey = Date.now();
}

export function liveCommand(cmd: ClientCommand) {
  if (cmd.name === 'start_calibration') {
    const iris = median(st.irisHist);
    if (!st.face || !iris) {
      pushToast('warning', 'Face the camera first, then calibrate.');
      return;
    }
    st.focal = (iris * cmd.args.distance_cm * 10) / IRIS_MM;
    st.calibrated = true;
    st.earBase = 0;
    st.earSamples = [];
    pushToast('success', `Calibrated at ${cmd.args.distance_cm} cm. Relearning your normal eye opening: look at the screen for a few seconds.`);
  } else if (cmd.name === 'skip_break') {
    send('break', { id: cmd.args.id, phase: 'skipped', target_s: BREAK_S, looking_away_s: st.breakAway, streak: st.stats.breaks_verified } as never);
    st.breakId = '';
  } else if (cmd.name === 'pause_camera') {
    if (cmd.args.paused) stopLive();
    else void startLive();
  } else {
    pushToast('info', 'In the hosted live demo, Amazon Nova (rulebook, reports) is not connected. Run Myrmidon on your laptop for the coach.');
  }
}
