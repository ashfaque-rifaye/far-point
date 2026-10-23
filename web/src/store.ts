import { useSyncExternalStore } from 'react';
import type {
  ActionData,
  BreakData,
  ConfirmRequestData,
  DecisionData,
  DoctrineData,
  EmailDraftData,
  HelloData,
  ProposalData,
  ReportData,
  ServerEvent,
  SignalsData,
  StatsData,
  ToastLevel,
  VerificationData,
} from './contract';

/* Optional fields the backend adds on `decision` (docs/backend-extensions.md). */
export interface RuleAnswer {
  n: number;
  tool: string;
  p: number | null;
  state: 'fires' | 'unsure' | 'clear';
  escalated: boolean | null;
}
export interface DecisionExt extends DecisionData {
  answers: DecisionData['answers'] & { rules?: RuleAnswer[] };
  reason?: string;
  skipped?: { n: number; tool: string; why: string }[];
  escalation?: { model: string; latency_ms: number; verdicts: Record<string, boolean | null>; skipped?: string | null };
}

export type Conn = 'connecting' | 'open' | 'offline' | 'demo';

export interface Stamped<T> {
  t: number;
  data: T;
}

export interface Sample {
  t: number;
  d: number | null;
  s: number;
}

export interface Toast {
  id: number;
  level: ToastLevel;
  text: string;
}

export interface State {
  conn: Conn;
  wsUrl: string;
  hello?: HelloData;
  signals?: SignalsData;
  samples: Sample[];
  decisions: Stamped<DecisionExt>[];
  actions: Stamped<ActionData>[];
  verifications: Record<string, Stamped<VerificationData>>;
  brk?: BreakData;
  doctrine?: DoctrineData;
  proposals: ProposalData[];
  stats?: StatsData;
  report?: ReportData;
  reportLoading: boolean;
  email?: EmailDraftData;
  confirm?: ConfirmRequestData;
  toasts: Toast[];
  lastVerified?: Stamped<VerificationData> & { tool?: string };
}

const MAX_SAMPLES = 900;
const MAX_DECISIONS = 120;
const MAX_ACTIONS = 80;

let state: State = {
  conn: 'connecting',
  wsUrl: '',
  samples: [],
  decisions: [],
  actions: [],
  verifications: {},
  proposals: [],
  toasts: [],
  reportLoading: false,
};

const listeners = new Set<() => void>();
let scheduled = false;

function emit() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    listeners.forEach((l) => l());
  });
}

export function getState(): State {
  return state;
}

export function setState(patch: Partial<State> | ((s: State) => Partial<State>)) {
  const p = typeof patch === 'function' ? patch(state) : patch;
  state = { ...state, ...p };
  emit();
}

export function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => sel(state));
}

let toastSeq = 1;
export function pushToast(level: ToastLevel, text: string) {
  const id = toastSeq++;
  setState((s) => ({ toasts: [...s.toasts.slice(-3), { id, level, text }] }));
  window.setTimeout(() => setState((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), level === 'warning' ? 7000 : 4500);
}

export function dismissToast(id: number) {
  setState((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) }));
}

/** Fold one validated server event into the store. */
export function ingest(ev: ServerEvent) {
  switch (ev.type) {
    case 'hello':
      setState({ hello: ev.data });
      break;
    case 'signals': {
      const d = ev.data;
      setState((s) => ({
        signals: d,
        samples: [...s.samples.slice(-(MAX_SAMPLES - 1)), { t: ev.t, d: d.distance_cm, s: d.squint }],
      }));
      break;
    }
    case 'decision':
      setState((s) => ({ decisions: [...s.decisions.slice(-(MAX_DECISIONS - 1)), { t: ev.t, data: ev.data as DecisionExt }] }));
      break;
    case 'action':
      setState((s) => {
        const others = s.actions.filter((a) => a.data.id !== ev.data.id);
        return { actions: [...others.slice(-(MAX_ACTIONS - 1)), { t: ev.t, data: ev.data }] };
      });
      break;
    case 'verification':
      setState((s) => {
        const tool = s.actions.find((a) => a.data.id === ev.data.action_id)?.data.tool;
        const v = { t: ev.t, data: ev.data };
        return {
          verifications: { ...s.verifications, [ev.data.action_id]: v },
          lastVerified: ev.data.outcome === 'n/a' ? s.lastVerified : { ...v, tool },
        };
      });
      break;
    case 'break':
      setState({ brk: ['verified', 'skipped', 'abandoned'].includes(ev.data.phase) ? { ...ev.data } : ev.data });
      if (ev.data.phase === 'verified') pushToast('success', `Break verified. Streak ${ev.data.streak}.`);
      if (['verified', 'skipped', 'abandoned'].includes(ev.data.phase)) {
        window.setTimeout(() => {
          const b = getState().brk;
          if (b && b.id === ev.data.id && b.phase === ev.data.phase) setState({ brk: undefined });
        }, 2600);
      }
      break;
    case 'doctrine':
      setState({ doctrine: ev.data });
      break;
    case 'proposal':
      setState((s) => {
        const others = s.proposals.filter((p) => p.id !== ev.data.id);
        return { proposals: [...others, ev.data] };
      });
      break;
    case 'stats':
      setState({ stats: ev.data });
      break;
    case 'report':
      setState({ report: ev.data, reportLoading: false });
      break;
    case 'email_draft':
      setState({ email: ev.data });
      break;
    case 'confirm_request':
      setState({ confirm: ev.data });
      break;
    case 'toast':
      pushToast(ev.data.level, ev.data.text);
      if (ev.data.level === 'warning') setState({ reportLoading: false });
      break;
  }
}
