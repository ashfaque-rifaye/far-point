/**
 * Myrmidon UI <-> local backend data contract (protocol v1).
 *
 * Single source of truth for the web UI. Mirrors:
 *   - web/contract.schema.json   (JSON Schema, draft 2020-12)
 *   - docs/ui-contract.md        (human-readable spec with worked examples)
 *
 * Transport: ONE WebSocket, default ws://127.0.0.1:8765/ws.
 *   Override order: ?ws=<url> query param  >  VITE_WS_URL env  >  default.
 * The page itself is served by the backend at http://127.0.0.1:8765/ from web/dist.
 *
 * Every server -> client message is an Envelope: { v: 1, type, t: epoch_ms, data }.
 * Every client -> server message is a Command:   { v: 1, type: "cmd", name, args }.
 *
 * Compatibility rules (both sides):
 *   - Receivers MUST ignore unknown fields.
 *   - The UI MUST ignore (not crash on) unknown event `type`s; the guards below
 *     report them as `unknown_type` so callers can log and drop them.
 *   - The backend MUST answer an unknown command `name` with a `toast` (level "warning").
 *   - Fields marked "EXTENSION" are additions to the original brief; all are optional.
 *
 * This file has no runtime dependencies so it can be imported by the app, tests and a mock server.
 */

/* ------------------------------------------------------------------------------------------------
 * Transport
 * ---------------------------------------------------------------------------------------------- */

export const PROTOCOL_VERSION = 1 as const;
export const DEFAULT_WS_URL = 'ws://127.0.0.1:8765/ws';

/**
 * Resolve the WebSocket URL. Pass `window.location.search` and `import.meta.env.VITE_WS_URL`.
 * Only ws:// and wss:// URLs are accepted; anything else falls through to the next source.
 */
export function resolveWsUrl(search?: string, envUrl?: string | null): string {
  const isWs = (u: string | null | undefined): u is string => {
    if (!u) return false;
    try {
      const p = new URL(u);
      return p.protocol === 'ws:' || p.protocol === 'wss:';
    } catch {
      return false;
    }
  };
  if (search) {
    const q = new URLSearchParams(search).get('ws');
    if (isWs(q)) return q;
  }
  if (isWs(envUrl)) return envUrl;
  return DEFAULT_WS_URL;
}

/* ------------------------------------------------------------------------------------------------
 * Enumerations (runtime arrays + derived literal types, so guards and types never drift)
 * ---------------------------------------------------------------------------------------------- */

export const MODES = ['live', 'replay'] as const;
export type Mode = (typeof MODES)[number];

export const SERVICE_STATUSES = ['ready', 'loading', 'down'] as const;
export type ServiceStatus = (typeof SERVICE_STATUSES)[number];

/** EXTENSION: Bedrock may also be 'off' (no credentials / disabled by user). */
export const BEDROCK_STATUSES = ['ready', 'loading', 'down', 'off'] as const;
export type BedrockStatus = (typeof BEDROCK_STATUSES)[number];

export const CAMERA_STATUSES = ['on', 'off', 'paused', 'error'] as const;
export type CameraStatus = (typeof CAMERA_STATUSES)[number];

export const DISTANCE_BANDS = ['too_close', 'close', 'healthy', 'far'] as const;
export type DistanceBand = (typeof DISTANCE_BANDS)[number];

export const AMBIENT_LEVELS = ['dark', 'dim', 'normal', 'bright'] as const;
export type Ambient = (typeof AMBIENT_LEVELS)[number];

export const APP_CATEGORIES = ['browser', 'editor', 'office', 'pdf', 'video', 'meeting', 'other'] as const;
export type AppCategory = (typeof APP_CATEGORIES)[number];

export const DECISION_SOURCES = ['decider', 'fallback'] as const;
export type DecisionSource = (typeof DECISION_SOURCES)[number];

export const STRAIN_LEVELS = ['relaxed', 'mild', 'strong'] as const;
export type StrainLevel = (typeof STRAIN_LEVELS)[number];

export const POLICIES = ['act', 'quiet', 'ask'] as const;
export type Policy = (typeof POLICIES)[number];

export const TOOLS = [
  'enlarge_text',
  'reduce_text',
  'dim_screen',
  'brighten_screen',
  'dark_mode',
  'far_look_break',
  'glasses_reminder',
  'ask_user',
  'reset',
] as const;
export type Tool = (typeof TOOLS)[number];

export const GATE_NAMES = ['InterruptGate', 'Confirm'] as const;
export type GateName = (typeof GATE_NAMES)[number];

export const GATE_VERDICTS = ['proceed', 'deny', 'defer', 'pending'] as const;
export type GateVerdict = (typeof GATE_VERDICTS)[number];

export const ACTION_STATUSES = ['done', 'denied', 'deferred', 'pending_confirm', 'failed'] as const;
export type ActionStatus = (typeof ACTION_STATUSES)[number];

export const OUTCOMES = ['worked', 'no_change', 'worse', 'n/a'] as const;
export type Outcome = (typeof OUTCOMES)[number];

export const BREAK_PHASES = ['offered', 'started', 'tick', 'verified', 'skipped', 'abandoned'] as const;
export type BreakPhase = (typeof BREAK_PHASES)[number];

export const RULE_ORIGINS = ['bedrock', 'user', 'proposal', 'default'] as const;
export type RuleOrigin = (typeof RULE_ORIGINS)[number];

export const RULE_STATUSES = ['active', 'pending', 'rejected'] as const;
export type RuleStatus = (typeof RULE_STATUSES)[number];

export const PROPOSAL_STATUSES = ['pending', 'approved', 'rejected'] as const;
export type ProposalStatus = (typeof PROPOSAL_STATUSES)[number];

export const REPORT_PERIODS = ['today', 'week'] as const;
export type ReportPeriod = (typeof REPORT_PERIODS)[number];

export const EMAIL_STATUSES = ['draft', 'pending_confirm', 'opened'] as const;
export type EmailStatus = (typeof EMAIL_STATUSES)[number];

export const TOAST_LEVELS = ['info', 'success', 'warning'] as const;
export type ToastLevel = (typeof TOAST_LEVELS)[number];

/* ------------------------------------------------------------------------------------------------
 * Envelope
 * ---------------------------------------------------------------------------------------------- */

export interface Envelope<T extends string = string, D = unknown> {
  /** Protocol version, always 1. */
  v: typeof PROTOCOL_VERSION;
  type: T;
  /** Server send time, epoch milliseconds. */
  t: number;
  data: D;
}

/** Probability in [0, 1]. */
export type Prob = number;
/** Map of option -> probability. Values are in [0, 1] and should sum to ~1. */
export type ProbMap = Record<string, Prob>;

/* ------------------------------------------------------------------------------------------------
 * Server -> client event payloads
 * ---------------------------------------------------------------------------------------------- */

/** Sent once immediately after the socket opens, and again whenever any status changes. */
export interface HelloData {
  mode: Mode;
  app_version: string;
  profile_name: string;
  decider: {
    status: ServiceStatus;
    /** Local model id, e.g. "qwen2.5-vl-3b-instruct-q4". */
    model: string;
    /** Execution device, e.g. "cuda", "cpu", "npu". */
    device: string;
    /** True when the decider also answers the optional `vision` questions. */
    vision: boolean;
  };
  bedrock: {
    status: BedrockStatus;
    /** Bedrock model id, or null when Bedrock is off. */
    model: string | null;
  };
  camera: {
    status: CameraStatus;
  };
}

export interface AppContext {
  /** Foreground app display name, e.g. "Code", "Chrome". */
  name: string;
  category: AppCategory;
  /** Zoom steps applied by Myrmidon relative to the user's default; 0 = untouched, +n larger, -n smaller. */
  zoom_step: number;
}

/** Per-frame perception summary, 5-10 Hz. */
export interface SignalsData {
  face: boolean;
  /** Eye-to-screen distance in cm; null when no face. */
  distance_cm: number | null;
  distance_band: DistanceBand | null;
  /** Eye-opening ratio vs calibrated baseline. 1.0 = baseline; lower = more squint. */
  squint: number;
  squinting: boolean;
  blink_per_min: number;
  /** null when unknown (no face / low confidence). */
  looking_at_screen: boolean | null;
  ambient: Ambient;
  /** null when unknown. */
  glasses_on: boolean | null;
  /** Seconds of the current continuous near-work bout. */
  bout_s: number;
  /** Seconds spent closer than 30 cm today. */
  under30_today_s: number;
  app: AppContext;
}

export interface DecisionAnswers {
  next_action: {
    /** Winning option. Options are Tool names plus "none". */
    choice: string;
    confidence: Prob;
    probs: ProbMap;
  };
  strain: {
    level: StrainLevel;
    /** Expected strain score in [0, 2]: 0 = relaxed, 1 = mild, 2 = strong (probability-weighted). */
    expected: number;
    /** Keys: "relaxed" | "mild" | "strong". */
    probs: ProbMap;
  };
  interrupt_ok: {
    /** Probability that interrupting the user right now is acceptable. */
    p: Prob;
  };
  /** Present only when hello.decider.vision is true. Each value is a probability. */
  vision?: {
    glasses_on: Prob;
    rubbing_eyes: Prob;
    looking_far: Prob;
    video_call: Prob;
  };
}

/** One decider pass, every 2-3 s. */
export interface DecisionData {
  id: string;
  latency_ms: number;
  source: DecisionSource;
  /** Natural-language state the decider was given (shown in the "what it sees" panel). */
  state_text: string;
  answers: DecisionAnswers;
  policy: Policy;
  /** Doctrine rule that drove the policy, e.g. "rule 3". */
  rule_ref?: string;
}

export interface ActionGate {
  name: GateName | null;
  verdict: GateVerdict | null;
  /** Gate probability (interrupt_ok.p for InterruptGate); null when no gate applied. */
  p: Prob | null;
}

export interface ActionData {
  id: string;
  decision_id: string;
  tool: Tool;
  /** Tool arguments, e.g. { steps: 1 } for enlarge_text, { level: 0.7 } for dim_screen. */
  args: Record<string, unknown>;
  gate: ActionGate;
  status: ActionStatus;
  /** Short user-facing sentence. */
  message: string;
}

export interface Measure {
  distance_cm: number | null;
  squint: number | null;
}

/** Closed-loop check of an action's effect after window_s seconds. */
export interface VerificationData {
  action_id: string;
  outcome: Outcome;
  before: Measure;
  after: Measure;
  window_s: number;
}

/** 20-20-20 far-look break lifecycle. */
export interface BreakData {
  id: string;
  phase: BreakPhase;
  /** Required looking-away seconds (normally 20). */
  target_s: number;
  /** Verified looking-away seconds so far. */
  looking_away_s: number;
  /** Consecutive verified breaks today. */
  streak: number;
}

export interface DoctrineRule {
  /** 1-based rule number. */
  n: number;
  text: string;
  origin: RuleOrigin;
  status: RuleStatus;
  /** Why the rule exists, e.g. "Your description: 'myopia -3.5, worse at night'". */
  basis: string;
}

/** The user's personal care doctrine compiled (by Bedrock) from their eye description. */
export interface DoctrineData {
  /** Monotonic integer version; approve_doctrine must echo it. */
  version: number;
  /** The user's own eye description the doctrine was compiled from. */
  source_text: string;
  approved: boolean;
  rules: DoctrineRule[];
}

export interface ProposalMoment {
  /** Epoch ms of the observed moment. */
  t: number;
  /** One-line description, e.g. "Squint 0.62 at 24 cm in PDF, dim room". */
  note: string;
}

/** A rule change the agent learned from observed moments and wants approved. */
export interface ProposalData {
  id: string;
  rule_text: string;
  reason: string;
  /** Evidence moments that motivated the proposal. */
  moments: ProposalMoment[];
  status: ProposalStatus;
}

export interface StatsData {
  /** Local date, "YYYY-MM-DD". */
  day: string;
  under30_min: number;
  longest_bout_min: number;
  breaks_offered: number;
  breaks_verified: number;
  streak: number;
  squint_episodes: number;
  glasses_off_min: number;
  adaptations: number;
  adaptations_worked: number;
  decisions: number;
  decider_p50_ms: number;
  decider_p95_ms: number;
  /** Privacy counter. Always 0 in normal use: frames never leave the machine. */
  face_images_uploaded: number;
  bedrock_calls: number;
  bedrock_tokens: number;
}

export interface ReportData {
  id: string;
  period: ReportPeriod;
  markdown: string;
  model: string;
  /** Epoch ms. */
  generated_at: number;
}

export interface EmailDraftData {
  id: string;
  subject: string;
  body: string;
  status: EmailStatus;
  /** EXTENSION: recipient address if known (eye clinic), else null/absent. */
  to?: string | null;
}

/** Backend asks the user to approve a consequential step. Answer with the `confirm` command. */
export interface ConfirmRequestData {
  request_id: string;
  title: string;
  detail: string;
}

export interface ToastData {
  level: ToastLevel;
  text: string;
}

/* ------------------------------------------------------------------------------------------------
 * Server event union
 * ---------------------------------------------------------------------------------------------- */

export interface ServerEventDataMap {
  hello: HelloData;
  signals: SignalsData;
  decision: DecisionData;
  action: ActionData;
  verification: VerificationData;
  break: BreakData;
  doctrine: DoctrineData;
  proposal: ProposalData;
  stats: StatsData;
  report: ReportData;
  email_draft: EmailDraftData;
  confirm_request: ConfirmRequestData;
  toast: ToastData;
}

export type ServerEventType = keyof ServerEventDataMap;

export const SERVER_EVENT_TYPES = [
  'hello',
  'signals',
  'decision',
  'action',
  'verification',
  'break',
  'doctrine',
  'proposal',
  'stats',
  'report',
  'email_draft',
  'confirm_request',
  'toast',
] as const satisfies readonly ServerEventType[];

export type ServerEventOf<K extends ServerEventType> = Envelope<K, ServerEventDataMap[K]>;
export type ServerEvent = { [K in ServerEventType]: ServerEventOf<K> }[ServerEventType];

export type HelloEvent = ServerEventOf<'hello'>;
export type SignalsEvent = ServerEventOf<'signals'>;
export type DecisionEvent = ServerEventOf<'decision'>;
export type ActionEvent = ServerEventOf<'action'>;
export type VerificationEvent = ServerEventOf<'verification'>;
export type BreakEvent = ServerEventOf<'break'>;
export type DoctrineEvent = ServerEventOf<'doctrine'>;
export type ProposalEvent = ServerEventOf<'proposal'>;
export type StatsEvent = ServerEventOf<'stats'>;
export type ReportEvent = ServerEventOf<'report'>;
export type EmailDraftEvent = ServerEventOf<'email_draft'>;
export type ConfirmRequestEvent = ServerEventOf<'confirm_request'>;
export type ToastEvent = ServerEventOf<'toast'>;

/* ------------------------------------------------------------------------------------------------
 * Client -> server commands
 * ---------------------------------------------------------------------------------------------- */

export interface CommandArgsMap {
  /** Free-text description of the user's eyes; backend recompiles the doctrine and emits `doctrine`. */
  set_eye_description: { text: string };
  approve_doctrine: { version: number };
  approve_proposal: { id: string };
  reject_proposal: { id: string };
  /** User sits at a known distance; backend records baseline (distance + eye opening). */
  start_calibration: { distance_cm: number };
  request_report: { period: ReportPeriod };
  draft_exam_email: Record<string, never>;
  confirm: { request_id: string; approve: boolean };
  pause_camera: { paused: boolean };
  skip_break: { id: string };
}

export type CommandName = keyof CommandArgsMap;

export const COMMAND_NAMES = [
  'set_eye_description',
  'approve_doctrine',
  'approve_proposal',
  'reject_proposal',
  'start_calibration',
  'request_report',
  'draft_exam_email',
  'confirm',
  'pause_camera',
  'skip_break',
] as const satisfies readonly CommandName[];

export interface CommandOf<K extends CommandName> {
  v: typeof PROTOCOL_VERSION;
  type: 'cmd';
  name: K;
  args: CommandArgsMap[K];
  /** EXTENSION: client send time, epoch ms. Optional; backend must not require it. */
  t?: number;
}

export type ClientCommand = { [K in CommandName]: CommandOf<K> }[CommandName];

/** Build a well-formed command. */
export function makeCommand<K extends CommandName>(name: K, args: CommandArgsMap[K]): CommandOf<K> {
  return { v: PROTOCOL_VERSION, type: 'cmd', name, args, t: Date.now() };
}

/* ------------------------------------------------------------------------------------------------
 * Runtime guard primitives
 * ---------------------------------------------------------------------------------------------- */

type Obj = Record<string, unknown>;

const isObj = (x: unknown): x is Obj => typeof x === 'object' && x !== null && !Array.isArray(x);
const isStr = (x: unknown): x is string => typeof x === 'string';
const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const isInt = (x: unknown): x is number => isNum(x) && Number.isInteger(x);
const isNonNeg = (x: unknown): x is number => isNum(x) && x >= 0;
const isBool = (x: unknown): x is boolean => typeof x === 'boolean';
const isProb = (x: unknown): x is number => isNum(x) && x >= 0 && x <= 1;
const nullable =
  <T>(g: (x: unknown) => x is T) =>
  (x: unknown): x is T | null =>
    x === null || g(x);
const oneOf =
  <T extends string>(values: readonly T[]) =>
  (x: unknown): x is T =>
    typeof x === 'string' && (values as readonly string[]).includes(x);
const isProbMap = (x: unknown): x is ProbMap => isObj(x) && Object.values(x).every(isProb);
const isArrayOf =
  <T>(g: (x: unknown) => x is T) =>
  (x: unknown): x is T[] =>
    Array.isArray(x) && x.every(g);

/* ------------------------------------------------------------------------------------------------
 * Payload guards
 * ---------------------------------------------------------------------------------------------- */

export function isHelloData(x: unknown): x is HelloData {
  if (!isObj(x)) return false;
  const { decider, bedrock, camera } = x;
  return (
    oneOf(MODES)(x.mode) &&
    isStr(x.app_version) &&
    isStr(x.profile_name) &&
    isObj(decider) &&
    oneOf(SERVICE_STATUSES)(decider.status) &&
    isStr(decider.model) &&
    isStr(decider.device) &&
    isBool(decider.vision) &&
    isObj(bedrock) &&
    oneOf(BEDROCK_STATUSES)(bedrock.status) &&
    nullable(isStr)(bedrock.model) &&
    isObj(camera) &&
    oneOf(CAMERA_STATUSES)(camera.status)
  );
}

export function isAppContext(x: unknown): x is AppContext {
  return isObj(x) && isStr(x.name) && oneOf(APP_CATEGORIES)(x.category) && isInt(x.zoom_step);
}

export function isSignalsData(x: unknown): x is SignalsData {
  return (
    isObj(x) &&
    isBool(x.face) &&
    nullable(isNonNeg)(x.distance_cm) &&
    nullable(oneOf(DISTANCE_BANDS))(x.distance_band) &&
    isNonNeg(x.squint) &&
    isBool(x.squinting) &&
    isNonNeg(x.blink_per_min) &&
    nullable(isBool)(x.looking_at_screen) &&
    oneOf(AMBIENT_LEVELS)(x.ambient) &&
    nullable(isBool)(x.glasses_on) &&
    isNonNeg(x.bout_s) &&
    isNonNeg(x.under30_today_s) &&
    isAppContext(x.app)
  );
}

export function isDecisionAnswers(x: unknown): x is DecisionAnswers {
  if (!isObj(x)) return false;
  const { next_action: na, strain: st, interrupt_ok: io, vision: vi } = x;
  return (
    isObj(na) &&
    isStr(na.choice) &&
    isProb(na.confidence) &&
    isProbMap(na.probs) &&
    isObj(st) &&
    oneOf(STRAIN_LEVELS)(st.level) &&
    isNum(st.expected) &&
    st.expected >= 0 &&
    st.expected <= 2 &&
    isProbMap(st.probs) &&
    isObj(io) &&
    isProb(io.p) &&
    (vi === undefined ||
      (isObj(vi) &&
        isProb(vi.glasses_on) &&
        isProb(vi.rubbing_eyes) &&
        isProb(vi.looking_far) &&
        isProb(vi.video_call)))
  );
}

export function isDecisionData(x: unknown): x is DecisionData {
  return (
    isObj(x) &&
    isStr(x.id) &&
    isNonNeg(x.latency_ms) &&
    oneOf(DECISION_SOURCES)(x.source) &&
    isStr(x.state_text) &&
    isDecisionAnswers(x.answers) &&
    oneOf(POLICIES)(x.policy) &&
    (x.rule_ref === undefined || isStr(x.rule_ref))
  );
}

export function isActionData(x: unknown): x is ActionData {
  if (!isObj(x)) return false;
  const g = x.gate;
  return (
    isStr(x.id) &&
    isStr(x.decision_id) &&
    oneOf(TOOLS)(x.tool) &&
    isObj(x.args) &&
    isObj(g) &&
    nullable(oneOf(GATE_NAMES))(g.name) &&
    nullable(oneOf(GATE_VERDICTS))(g.verdict) &&
    nullable(isProb)(g.p) &&
    oneOf(ACTION_STATUSES)(x.status) &&
    isStr(x.message)
  );
}

const isMeasure = (x: unknown): x is Measure =>
  isObj(x) && nullable(isNonNeg)(x.distance_cm) && nullable(isNonNeg)(x.squint);

export function isVerificationData(x: unknown): x is VerificationData {
  return (
    isObj(x) &&
    isStr(x.action_id) &&
    oneOf(OUTCOMES)(x.outcome) &&
    isMeasure(x.before) &&
    isMeasure(x.after) &&
    isNonNeg(x.window_s)
  );
}

export function isBreakData(x: unknown): x is BreakData {
  return (
    isObj(x) &&
    isStr(x.id) &&
    oneOf(BREAK_PHASES)(x.phase) &&
    isNonNeg(x.target_s) &&
    isNonNeg(x.looking_away_s) &&
    isInt(x.streak) &&
    x.streak >= 0
  );
}

const isDoctrineRule = (x: unknown): x is DoctrineRule =>
  isObj(x) &&
  isInt(x.n) &&
  isStr(x.text) &&
  oneOf(RULE_ORIGINS)(x.origin) &&
  oneOf(RULE_STATUSES)(x.status) &&
  isStr(x.basis);

export function isDoctrineData(x: unknown): x is DoctrineData {
  return (
    isObj(x) &&
    isInt(x.version) &&
    isStr(x.source_text) &&
    isBool(x.approved) &&
    isArrayOf(isDoctrineRule)(x.rules)
  );
}

const isProposalMoment = (x: unknown): x is ProposalMoment => isObj(x) && isNum(x.t) && isStr(x.note);

export function isProposalData(x: unknown): x is ProposalData {
  return (
    isObj(x) &&
    isStr(x.id) &&
    isStr(x.rule_text) &&
    isStr(x.reason) &&
    isArrayOf(isProposalMoment)(x.moments) &&
    oneOf(PROPOSAL_STATUSES)(x.status)
  );
}

const STATS_NUMERIC_KEYS = [
  'under30_min',
  'longest_bout_min',
  'breaks_offered',
  'breaks_verified',
  'streak',
  'squint_episodes',
  'glasses_off_min',
  'adaptations',
  'adaptations_worked',
  'decisions',
  'decider_p50_ms',
  'decider_p95_ms',
  'face_images_uploaded',
  'bedrock_calls',
  'bedrock_tokens',
] as const satisfies readonly (keyof StatsData)[];

export function isStatsData(x: unknown): x is StatsData {
  return isObj(x) && isStr(x.day) && STATS_NUMERIC_KEYS.every((k) => isNonNeg(x[k]));
}

export function isReportData(x: unknown): x is ReportData {
  return (
    isObj(x) &&
    isStr(x.id) &&
    oneOf(REPORT_PERIODS)(x.period) &&
    isStr(x.markdown) &&
    isStr(x.model) &&
    isNum(x.generated_at)
  );
}

export function isEmailDraftData(x: unknown): x is EmailDraftData {
  return (
    isObj(x) &&
    isStr(x.id) &&
    isStr(x.subject) &&
    isStr(x.body) &&
    oneOf(EMAIL_STATUSES)(x.status) &&
    (x.to === undefined || nullable(isStr)(x.to))
  );
}

export function isConfirmRequestData(x: unknown): x is ConfirmRequestData {
  return isObj(x) && isStr(x.request_id) && isStr(x.title) && isStr(x.detail);
}

export function isToastData(x: unknown): x is ToastData {
  return isObj(x) && oneOf(TOAST_LEVELS)(x.level) && isStr(x.text);
}

export const DATA_GUARDS: { [K in ServerEventType]: (d: unknown) => d is ServerEventDataMap[K] } = {
  hello: isHelloData,
  signals: isSignalsData,
  decision: isDecisionData,
  action: isActionData,
  verification: isVerificationData,
  break: isBreakData,
  doctrine: isDoctrineData,
  proposal: isProposalData,
  stats: isStatsData,
  report: isReportData,
  email_draft: isEmailDraftData,
  confirm_request: isConfirmRequestData,
  toast: isToastData,
};

/* ------------------------------------------------------------------------------------------------
 * Envelope / event guards
 * ---------------------------------------------------------------------------------------------- */

/** Structural envelope check only (does not validate `data`). */
export function isEnvelope(x: unknown): x is Envelope<string, unknown> {
  return isObj(x) && x.v === PROTOCOL_VERSION && isStr(x.type) && isNum(x.t) && isObj(x.data);
}

export const isServerEventType = oneOf(SERVER_EVENT_TYPES);

/** Full check: envelope + known type + payload. */
export function isServerEvent(x: unknown): x is ServerEvent {
  if (!isEnvelope(x) || !isServerEventType(x.type)) return false;
  return DATA_GUARDS[x.type](x.data);
}

/** Narrow a validated event to a specific type. */
export function isEventOfType<K extends ServerEventType>(x: ServerEvent, type: K): x is Extract<ServerEvent, { type: K }> {
  return x.type === type;
}

export type ParseFailure = 'invalid_json' | 'not_envelope' | 'bad_version' | 'unknown_type' | 'invalid_data';
export type ParseResult =
  | { ok: true; event: ServerEvent }
  | { ok: false; reason: ParseFailure; type?: string; raw: unknown };

/**
 * Parse a WebSocket frame (string or already-parsed object) into a validated ServerEvent.
 * Never throws. Callers should drop `unknown_type` silently and log other failures.
 */
export function parseServerMessage(raw: unknown): ParseResult {
  let msg: unknown = raw;
  if (typeof raw === 'string') {
    try {
      msg = JSON.parse(raw);
    } catch {
      return { ok: false, reason: 'invalid_json', raw };
    }
  }
  if (!isObj(msg)) return { ok: false, reason: 'not_envelope', raw };
  if (msg.v !== PROTOCOL_VERSION) return { ok: false, reason: 'bad_version', raw };
  if (!isEnvelope(msg)) return { ok: false, reason: 'not_envelope', raw };
  if (!isServerEventType(msg.type)) return { ok: false, reason: 'unknown_type', type: msg.type, raw };
  if (!DATA_GUARDS[msg.type](msg.data)) return { ok: false, reason: 'invalid_data', type: msg.type, raw };
  return { ok: true, event: msg as ServerEvent };
}

/* ------------------------------------------------------------------------------------------------
 * Command guards (used by mock servers / tests; the real backend validates in Python)
 * ---------------------------------------------------------------------------------------------- */

export const ARGS_GUARDS: { [K in CommandName]: (a: unknown) => a is CommandArgsMap[K] } = {
  set_eye_description: (a): a is CommandArgsMap['set_eye_description'] => isObj(a) && isStr(a.text),
  approve_doctrine: (a): a is CommandArgsMap['approve_doctrine'] => isObj(a) && isInt(a.version),
  approve_proposal: (a): a is CommandArgsMap['approve_proposal'] => isObj(a) && isStr(a.id),
  reject_proposal: (a): a is CommandArgsMap['reject_proposal'] => isObj(a) && isStr(a.id),
  start_calibration: (a): a is CommandArgsMap['start_calibration'] =>
    isObj(a) && isNum(a.distance_cm) && a.distance_cm > 0,
  request_report: (a): a is CommandArgsMap['request_report'] => isObj(a) && oneOf(REPORT_PERIODS)(a.period),
  draft_exam_email: (a): a is CommandArgsMap['draft_exam_email'] => isObj(a),
  confirm: (a): a is CommandArgsMap['confirm'] => isObj(a) && isStr(a.request_id) && isBool(a.approve),
  pause_camera: (a): a is CommandArgsMap['pause_camera'] => isObj(a) && isBool(a.paused),
  skip_break: (a): a is CommandArgsMap['skip_break'] => isObj(a) && isStr(a.id),
};

export const isCommandName = oneOf(COMMAND_NAMES);

export function isClientCommand(x: unknown): x is ClientCommand {
  return (
    isObj(x) &&
    x.v === PROTOCOL_VERSION &&
    x.type === 'cmd' &&
    isCommandName(x.name) &&
    (x.t === undefined || isNum(x.t)) &&
    ARGS_GUARDS[x.name](x.args)
  );
}

/* ------------------------------------------------------------------------------------------------
 * Examples (one per message; identical to docs/ui-contract.md). Usable as mock-server fixtures.
 * ---------------------------------------------------------------------------------------------- */

const T0 = 1767225600000; // 2026-01-01T00:00:00Z

export const EXAMPLE_EVENTS: { [K in ServerEventType]: ServerEventOf<K> } = {
  hello: {
    v: 1,
    type: 'hello',
    t: T0,
    data: {
      mode: 'live',
      app_version: '0.1.0',
      profile_name: 'Ashfaque',
      decider: { status: 'ready', model: 'qwen2.5-vl-3b-instruct-q4', device: 'cuda', vision: true },
      bedrock: { status: 'ready', model: 'anthropic.claude-sonnet-4' },
      camera: { status: 'on' },
    },
  },
  signals: {
    v: 1,
    type: 'signals',
    t: T0 + 200,
    data: {
      face: true,
      distance_cm: 27.4,
      distance_band: 'too_close',
      squint: 0.71,
      squinting: true,
      blink_per_min: 9.5,
      looking_at_screen: true,
      ambient: 'dim',
      glasses_on: false,
      bout_s: 1840,
      under30_today_s: 2710,
      app: { name: 'Acrobat Reader', category: 'pdf', zoom_step: 0 },
    },
  },
  decision: {
    v: 1,
    type: 'decision',
    t: T0 + 2400,
    data: {
      id: 'd_000142',
      latency_ms: 312,
      source: 'decider',
      state_text:
        'Reading a PDF at 27 cm for 30 min, squint 0.71 vs baseline, dim room, glasses off, blink 9.5/min.',
      answers: {
        next_action: {
          choice: 'enlarge_text',
          confidence: 0.64,
          probs: { enlarge_text: 0.64, far_look_break: 0.18, glasses_reminder: 0.11, none: 0.07 },
        },
        strain: { level: 'mild', expected: 1.21, probs: { relaxed: 0.14, mild: 0.51, strong: 0.35 } },
        interrupt_ok: { p: 0.78 },
        vision: { glasses_on: 0.06, rubbing_eyes: 0.03, looking_far: 0.02, video_call: 0.01 },
      },
      policy: 'act',
      rule_ref: 'rule 2',
    },
  },
  action: {
    v: 1,
    type: 'action',
    t: T0 + 2450,
    data: {
      id: 'a_000057',
      decision_id: 'd_000142',
      tool: 'enlarge_text',
      args: { steps: 1 },
      gate: { name: 'InterruptGate', verdict: 'proceed', p: 0.78 },
      status: 'done',
      message: 'Text enlarged one step so you can lean back.',
    },
  },
  verification: {
    v: 1,
    type: 'verification',
    t: T0 + 32450,
    data: {
      action_id: 'a_000057',
      outcome: 'worked',
      before: { distance_cm: 27.4, squint: 0.71 },
      after: { distance_cm: 41.2, squint: 0.93 },
      window_s: 30,
    },
  },
  break: {
    v: 1,
    type: 'break',
    t: T0 + 40000,
    data: { id: 'b_000012', phase: 'tick', target_s: 20, looking_away_s: 12.5, streak: 3 },
  },
  doctrine: {
    v: 1,
    type: 'doctrine',
    t: T0 + 500,
    data: {
      version: 3,
      source_text: 'Myopia -3.5 both eyes, early cataract in left eye. Glare bothers me at night.',
      approved: false,
      rules: [
        {
          n: 1,
          text: 'Prefer enlarging text over interrupting when distance drops below 30 cm.',
          origin: 'bedrock',
          status: 'active',
          basis: "Myopia -3.5: sustained near focus under 30 cm drives accommodation strain.",
        },
        {
          n: 2,
          text: 'In dim rooms, suggest dark mode before brightening the screen.',
          origin: 'bedrock',
          status: 'active',
          basis: "Early cataract: glare from bright screens in dark rooms scatters light.",
        },
        {
          n: 3,
          text: 'Never interrupt during video calls.',
          origin: 'default',
          status: 'active',
          basis: 'Default doctrine.',
        },
      ],
    },
  },
  proposal: {
    v: 1,
    type: 'proposal',
    t: T0 + 600000,
    data: {
      id: 'p_000004',
      rule_text: 'When reading PDFs after 21:00, start at zoom +1.',
      reason: 'Three late-evening PDF sessions each needed a manual enlarge within 2 minutes.',
      moments: [
        { t: T0 - 86400000, note: 'Squint 0.62 at 24 cm in PDF, dim room, 21:40' },
        { t: T0 - 43200000, note: 'Squint 0.66 at 26 cm in PDF, dim room, 22:05' },
      ],
      status: 'pending',
    },
  },
  stats: {
    v: 1,
    type: 'stats',
    t: T0 + 60000,
    data: {
      day: '2026-01-01',
      under30_min: 45.2,
      longest_bout_min: 52,
      breaks_offered: 9,
      breaks_verified: 7,
      streak: 3,
      squint_episodes: 14,
      glasses_off_min: 38,
      adaptations: 11,
      adaptations_worked: 8,
      decisions: 1240,
      decider_p50_ms: 298,
      decider_p95_ms: 611,
      face_images_uploaded: 0,
      bedrock_calls: 4,
      bedrock_tokens: 6120,
    },
  },
  report: {
    v: 1,
    type: 'report',
    t: T0 + 70000,
    data: {
      id: 'r_000002',
      period: 'today',
      markdown: '## Today\n\n- 45 min closer than 30 cm (down from 71 yesterday)\n- 7 of 9 breaks verified',
      model: 'anthropic.claude-sonnet-4',
      generated_at: T0 + 69000,
    },
  },
  email_draft: {
    v: 1,
    type: 'email_draft',
    t: T0 + 80000,
    data: {
      id: 'e_000001',
      subject: 'Request for an eye exam: screen-strain notes from the last 2 weeks',
      body: 'Hello,\n\nI would like to book an eye exam. Attached is a summary of my screen habits...',
      status: 'draft',
      to: null,
    },
  },
  confirm_request: {
    v: 1,
    type: 'confirm_request',
    t: T0 + 81000,
    data: {
      request_id: 'c_000009',
      title: 'Open email draft in your mail app?',
      detail: 'Myrmidon will open a mailto: link. Nothing is sent until you press Send yourself.',
    },
  },
  toast: {
    v: 1,
    type: 'toast',
    t: T0 + 82000,
    data: { level: 'success', text: 'Calibration saved: baseline 55 cm.' },
  },
};

export const EXAMPLE_COMMANDS: { [K in CommandName]: CommandOf<K> } = {
  set_eye_description: {
    v: 1,
    type: 'cmd',
    name: 'set_eye_description',
    args: { text: 'Myopia -3.5 both eyes, early cataract in left eye. Glare bothers me at night.' },
  },
  approve_doctrine: { v: 1, type: 'cmd', name: 'approve_doctrine', args: { version: 3 } },
  approve_proposal: { v: 1, type: 'cmd', name: 'approve_proposal', args: { id: 'p_000004' } },
  reject_proposal: { v: 1, type: 'cmd', name: 'reject_proposal', args: { id: 'p_000004' } },
  start_calibration: { v: 1, type: 'cmd', name: 'start_calibration', args: { distance_cm: 55 } },
  request_report: { v: 1, type: 'cmd', name: 'request_report', args: { period: 'week' } },
  draft_exam_email: { v: 1, type: 'cmd', name: 'draft_exam_email', args: {} },
  confirm: { v: 1, type: 'cmd', name: 'confirm', args: { request_id: 'c_000009', approve: true } },
  pause_camera: { v: 1, type: 'cmd', name: 'pause_camera', args: { paused: true } },
  skip_break: { v: 1, type: 'cmd', name: 'skip_break', args: { id: 'b_000012' } },
};
