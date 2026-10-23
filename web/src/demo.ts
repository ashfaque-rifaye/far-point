/**
 * Offline demo story (`?demo=1`, or the button on the offline screen).
 * It replays the glasses-off moment through the same contract events the backend sends,
 * so the UI can be shown with no backend running. Every event is labelled DEMO in `hello`.
 * The numbers are scripted, not measured.
 */
import type {
  ActionData,
  ClientCommand,
  DoctrineData,
  ServerEvent,
  ServerEventDataMap,
  ServerEventType,
  SignalsData,
  AppCategory,
  Tool,
} from './contract';
import { ingest, setState } from './store';

const LOOP_S = 128;
const TICK_MS = 100;

const DOCTRINE: DoctrineData = {
  version: 1,
  source_text: '',
  approved: true,
  rules: [
    ['The Viewing distance line says enlarging needed.', 'Clouclip pilot: under 30 cm for more than 5 s counts as unhealthy near work.'],
    ['The Glasses line says reminder due.', 'Leaning in and squinting at once is a common sign of reading without your glasses.'],
    ['The Theme line says dark mode needed.', 'A bright light page in a dark room is a common glare complaint.'],
    ['The Screen brightness line says dimming needed.', 'A screen much brighter than a dark room adds glare.'],
    ['The Screen brightness line says brightening needed.', 'A dim screen in a bright room makes you lean in and squint.'],
    ['The Near-work bout line says break is due.', 'Clouclip pilot: under 60 cm for more than 45 min counts as unhealthy near work.'],
    ['The Relaxed reading line says text can go back one step.', "Undo Myrmidon's own zoom once you read comfortably."],
    ['The Squint despite zoom line says yes.', 'If enlarging has not helped, ask instead of guessing.'],
  ].map(([text, basis], i) => ({ n: i + 1, text, basis, origin: 'default' as const, status: 'active' as const })),
};
const RULE_TOOLS: Tool[] = ['enlarge_text', 'glasses_reminder', 'dark_mode', 'dim_screen', 'brighten_screen', 'far_look_break', 'reduce_text', 'ask_user'];

let timer: number | null = null;
let t0 = 0;
let seq = 0;
let fired = new Set<string>();
let zoom = 0;
let dark = false;
let streak = 2;
let stats = {
  under30_min: 6.4,
  longest_bout_min: 52,
  breaks_offered: 3,
  breaks_verified: 2,
  squint_episodes: 4,
  glasses_off_min: 11,
  adaptations: 5,
  adaptations_worked: 4,
  decisions: 1180,
  bedrock_calls: 3,
  bedrock_tokens: 14200,
};
let under30 = 384;
let breakId = '';

function send<K extends ServerEventType>(type: K, data: ServerEventDataMap[K]) {
  ingest({ v: 1, type, t: Date.now(), data } as ServerEvent);
}

const lerp = (a: number, b: number, k: number) => a + (b - a) * Math.max(0, Math.min(1, k));
const ease = (k: number) => (k <= 0 ? 0 : k >= 1 ? 1 : k * k * (3 - 2 * k));

function scene(s: number) {
  // distance (cm), squint ratio, glasses, ambient, app, looking at screen
  let d = 55;
  let sq = 0.98;
  let glasses: boolean | null = true;
  let ambient: SignalsData['ambient'] = 'normal';
  let app: { name: string; category: AppCategory } = { name: 'Chrome', category: 'browser' };
  let looking: boolean | null = true;
  if (s >= 8 && s < 30) glasses = false;
  if (s >= 9) d = lerp(55, 26.5, ease((s - 9) / 6));
  if (s >= 9) sq = lerp(0.98, 0.71, ease((s - 9) / 6));
  if (s >= 22) d = lerp(26.5, 46, ease((s - 22) / 5));
  if (s >= 22) sq = lerp(0.71, 0.95, ease((s - 22) / 5));
  if (s >= 30) glasses = true;
  if (s >= 40 && s < 70) ambient = 'dark';
  if (s >= 42 && s < 52) sq = lerp(0.95, 0.72, ease((s - 42) / 3));
  if (s >= 50 && s < 60) sq = lerp(0.72, 0.94, ease((s - 50) / 4));
  if (s >= 62 && s < 80) app = { name: 'Teams', category: 'meeting' };
  if (s >= 84 && s < 106) {
    looking = false;
    d = 58;
  }
  if (s >= 106) d = lerp(58, 50, ease((s - 106) / 4));
  const wobble = Math.sin(s * 2.1) * 0.6 + Math.sin(s * 0.7) * 0.4;
  return { d: d + wobble, sq: Math.min(1.05, sq + Math.sin(s * 3.3) * 0.01), glasses, ambient, app, looking };
}

function band(d: number): SignalsData['distance_band'] {
  if (d < 30) return 'too_close';
  if (d < 40) return 'close';
  if (d <= 70) return 'healthy';
  return 'far';
}

function decide(s: number, sc: ReturnType<typeof scene>) {
  const bout = 2700 + s * 4;
  const p = RULE_TOOLS.map(() => 0.03 + Math.random() * 0.04);
  let fire: number | null = null;
  if (s >= 16 && s < 23 && zoom === 0) fire = 0;
  if (s >= 44 && s < 52 && !dark) fire = 2;
  if (s >= 64 && s < 82) fire = 5;
  if (s >= 82 && s < 86) fire = 5;
  if (fire !== null) p[fire] = 0.93 + Math.random() * 0.05;
  const meeting = sc.app.name === 'Teams';
  const interruptP = meeting ? 0.17 : 0.92;
  const rules = RULE_TOOLS.map((tool, i) => ({
    n: i + 1,
    tool,
    p: Math.round(p[i] * 1000) / 1000,
    state: p[i] >= 0.65 ? ('fires' as const) : p[i] <= 0.35 ? ('clear' as const) : ('unsure' as const),
    escalated: null,
  }));
  const tool = fire !== null ? RULE_TOOLS[fire] : 'none';
  const probs: Record<string, number> = {};
  let none = 1;
  rules.forEach((r) => {
    probs[r.tool] = r.p;
    none *= 1 - r.p;
  });
  probs.none = none;
  const sum = Object.values(probs).reduce((a, b) => a + b, 0);
  Object.keys(probs).forEach((k) => (probs[k] = probs[k] / sum));
  const id = `d_demo${++seq}`;
  const tooClose = sc.d < 30;
  const stateText = [
    `Viewing distance: ${sc.d.toFixed(0)} cm${tooClose ? ', under 30 cm for 8 s (limit 5 s): too close, enlarging needed.' : ': no enlarging needed.'}`,
    `Glasses: prescribed for screen work: yes. ${sc.glasses === false ? 'Signs of glasses off: yes, but zoom comes first: no reminder needed.' : 'Signs of glasses off: no: no reminder needed.'}`,
    `Theme: room ${sc.ambient}, app theme ${dark ? 'dark' : 'light'}: ${sc.ambient === 'dark' && !dark ? 'mismatch, dark mode needed.' : 'no change needed.'}`,
    `Near-work bout: ${(bout / 60).toFixed(0)} min under 60 cm (limit 45 min): ${s >= 62 ? 'break is due.' : 'break not due yet.'}`,
    `Activity: ${sc.app.name}${meeting ? ', on a call: not a good moment to interrupt.' : ', reading, no typing: fine to interrupt.'}`,
  ].join('\n');
  send('decision', {
    id,
    latency_ms: Math.round(445 + Math.random() * 90),
    source: 'decider',
    state_text: stateText,
    answers: {
      next_action: { choice: tool, confidence: fire !== null ? p[fire] : none, probs },
      strain: tooClose || sc.sq < 0.8
        ? { level: 'mild', expected: 1, probs: { relaxed: 0, mild: 1, strong: 0 } }
        : { level: 'relaxed', expected: 0, probs: { relaxed: 1, mild: 0, strong: 0 } },
      interrupt_ok: { p: interruptP },
      rules,
    } as never,
    policy: fire !== null ? 'act' : 'quiet',
    rule_ref: fire !== null ? `rule ${fire + 1}` : undefined,
    reason: fire !== null ? `rule ${fire + 1} fires (p=${p[fire].toFixed(2)})` : 'no rule fires: stay quiet',
  } as never);
  stats.decisions += 1;

  if (fire === null) return;
  const key = `${RULE_TOOLS[fire]}:${Math.floor(s / LOOP_S)}`;
  if (fire === 5) {
    if (meeting && !fired.has('deny')) {
      fired.add('deny');
      send('action', {
        id: `a_demo${seq}`,
        decision_id: id,
        tool: 'far_look_break',
        args: { seconds: 20 },
        gate: { name: 'InterruptGate', verdict: 'deny', p: interruptP },
        status: 'denied',
        message: 'Break held: you are on a call.',
      });
    } else if (!meeting && !fired.has(key)) {
      fired.add(key);
      breakId = `b_demo${seq}`;
      send('action', {
        id: `a_demo${seq}`,
        decision_id: id,
        tool: 'far_look_break',
        args: { seconds: 20 },
        gate: { name: 'InterruptGate', verdict: 'proceed', p: interruptP },
        status: 'done',
        message: 'Time for a 20-second far look.',
      });
      send('break', { id: breakId, phase: 'offered', target_s: 20, looking_away_s: 0, streak });
      stats.breaks_offered += 1;
    }
    return;
  }
  if (fired.has(key)) return;
  fired.add(key);
  const tool2 = RULE_TOOLS[fire];
  const a: ActionData = {
    id: `a_demo${seq}`,
    decision_id: id,
    tool: tool2,
    args: tool2 === 'enlarge_text' ? { steps: 1 } : {},
    gate: { name: null, verdict: null, p: null },
    status: 'done',
    message: tool2 === 'enlarge_text' ? 'Text one step larger in Chrome.' : 'Switched apps to dark mode.',
  };
  if (tool2 === 'enlarge_text') zoom = 1;
  if (tool2 === 'dark_mode') dark = true;
  send('action', a);
  stats.adaptations += 1;
  const before = { distance_cm: Math.round(sc.d * 10) / 10, squint: Math.round(sc.sq * 100) / 100 };
  window.setTimeout(() => {
    const s2 = scene(elapsed());
    send('verification', {
      action_id: a.id,
      outcome: 'worked',
      before,
      after: { distance_cm: Math.round(s2.d * 10) / 10, squint: Math.round(s2.sq * 100) / 100 },
      window_s: 12,
    });
    stats.adaptations_worked += 1;
  }, 12000);
}

function elapsed() {
  return ((Date.now() - t0) / 1000) % LOOP_S;
}

let lastDecision = -10;
let lastLoop = 0;

function tick() {
  const raw = (Date.now() - t0) / 1000;
  const loop = Math.floor(raw / LOOP_S);
  if (loop !== lastLoop) {
    lastLoop = loop;
    fired = new Set();
    zoom = 0;
    dark = false;
    lastDecision = -10;
  }
  const s = raw % LOOP_S;
  const sc = scene(s);
  if (sc.d < 30) under30 += TICK_MS / 1000;
  const bout = s >= 84 && s < 106 ? 0 : 2700 + s * 4;
  send('signals', {
    face: true,
    distance_cm: Math.round(sc.d * 10) / 10,
    distance_band: band(sc.d),
    squint: Math.round(sc.sq * 1000) / 1000,
    squinting: sc.sq < 0.78,
    blink_per_min: Math.round(13 + Math.sin(s / 7) * 3),
    looking_at_screen: sc.looking,
    ambient: sc.ambient,
    glasses_on: sc.glasses,
    bout_s: Math.round(bout),
    under30_today_s: Math.round(under30),
    app: { ...sc.app, zoom_step: zoom },
  });

  if (breakId && s >= 86 && s < 108) {
    const away = Math.min(20, Math.max(0, s - 86));
    const phase = away >= 20 ? 'verified' : away > 0 ? (away < 0.15 ? 'started' : 'tick') : 'offered';
    if (phase === 'verified') {
      streak += 1;
      stats.breaks_verified += 1;
      send('break', { id: breakId, phase: 'verified', target_s: 20, looking_away_s: 20, streak });
      breakId = '';
    } else if (Math.round(s * 10) % 5 === 0) {
      send('break', { id: breakId, phase, target_s: 20, looking_away_s: Math.round(away * 10) / 10, streak });
    }
  }

  if (s - lastDecision >= 2.5) {
    lastDecision = s;
    decide(s, sc);
  }
  if (Math.round(s * 10) % 30 === 0) {
    send('stats', {
      day: new Date().toISOString().slice(0, 10),
      ...stats,
      under30_min: Math.round((under30 / 60) * 10) / 10,
      streak,
      decider_p50_ms: 474,
      decider_p95_ms: 571,
      face_images_uploaded: 0,
    });
  }
  if (s >= 110 && s < 110.1 && !fired.has(`proposal:${loop}`)) {
    fired.add(`proposal:${loop}`);
    send('proposal', {
      id: 'p_demo_glare',
      rule_text: 'After 21:00 in a dark room, switch to dark mode before you start squinting.',
      reason: 'Two evenings this week you squinted in a dark room before dark mode switched on.',
      moments: [
        { t: Date.now() - 86400000, note: 'Squint 0.71 at 44 cm in Chrome, dark room, 21:40' },
        { t: Date.now() - 2 * 86400000, note: 'Squint 0.69 at 47 cm in Acrobat, dark room, 22:05' },
      ],
      status: 'pending',
    });
  }
}

export function startDemo() {
  if (timer !== null) return;
  t0 = Date.now();
  send('hello', {
    mode: 'replay',
    app_version: '0.1.0 DEMO',
    profile_name: 'Demo',
    decider: { status: 'ready', model: 'DEMO story (scripted numbers)', device: 'browser', vision: false },
    bedrock: { status: 'off', model: null },
    camera: { status: 'off' },
  });
  send('doctrine', DOCTRINE);
  timer = window.setInterval(tick, TICK_MS);
  setState({ conn: 'demo' });
}

export function demoCommand(cmd: ClientCommand) {
  const toast = (text: string, level: 'info' | 'success' | 'warning' = 'info') => send('toast', { level, text });
  switch (cmd.name) {
    case 'approve_proposal':
      send('proposal', { ...fakeProposal(), id: cmd.args.id, status: 'approved' });
      toast('Rule added above "ask you". (demo)', 'success');
      break;
    case 'reject_proposal':
      send('proposal', { ...fakeProposal(), id: cmd.args.id, status: 'rejected' });
      break;
    case 'request_report':
      window.setTimeout(
        () =>
          send('report', {
            id: 'r_demo',
            period: cmd.args.period,
            model: 'DEMO (no Bedrock call)',
            generated_at: Date.now(),
            markdown:
              '> Behavioral observations, not a diagnosis.\n\n## Today at the screen\n\n- **6.4 min** closer than 30 cm, mostly in two stretches after 21:00.\n- Longest unbroken near-work bout: **52 min**. 2 of 3 far-look breaks were verified by the camera.\n- Text was enlarged once; you sat back from 27 cm to 46 cm within 12 s.\n\n## Questions to bring to your optometrist\n\n1. I lean in more at night without glasses. Is my screen prescription still right?\n2. Would anti-glare coating help in a dark room?',
          }),
        900,
      );
      break;
    case 'draft_exam_email':
      send('email_draft', {
        id: 'e_demo',
        subject: 'Request for an eye exam',
        body: 'Hello,\n\nI would like to book a routine eye exam. Over the last week I noticed I lean in closer to my screen in the evening.\n\nThank you.',
        status: 'draft',
        to: null,
      });
      break;
    case 'set_eye_description':
      send('doctrine', { ...DOCTRINE, version: 2, approved: false, source_text: cmd.args.text });
      toast('Draft rulebook ready to review. (demo: rules unchanged)');
      break;
    case 'approve_doctrine':
      send('doctrine', { ...DOCTRINE, version: cmd.args.version, approved: true });
      toast('Rulebook adopted. (demo)', 'success');
      break;
    case 'skip_break':
      send('break', { id: cmd.args.id, phase: 'skipped', target_s: 20, looking_away_s: 0, streak: 0 });
      breakId = '';
      break;
    default:
      toast(`${cmd.name}: not available in demo mode.`, 'warning');
  }
}

function fakeProposal(): { rule_text: string; reason: string; moments: { t: number; note: string }[] } {
  return {
    rule_text: 'After 21:00 in a dark room, switch to dark mode before you start squinting.',
    reason: 'Two evenings this week you squinted in a dark room before dark mode switched on.',
    moments: [],
  };
}
