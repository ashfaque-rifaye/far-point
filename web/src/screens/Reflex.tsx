import { useState } from 'react';
import { DecisionCard } from './Now';
import { fmtTime, toolMeta } from '../components/ui';
import { useStore, type DecisionExt, type Stamped, type State } from '../store';

export function Reflex() {
  const decisions = useStore((x) => x.decisions);
  const actions = useStore((x) => x.actions);
  const verifications = useStore((x) => x.verifications);
  const [onlyActs, setOnlyActs] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const list = [...decisions].reverse().filter((d) => !onlyActs || d.data.policy !== 'quiet' || actions.some((a) => a.data.decision_id === d.data.id));
  const latest = decisions[decisions.length - 1];
  const p50 = median(decisions.slice(-40).map((d) => d.data.latency_ms));

  return (
    <section className="main" aria-label="Reflex log">
      <div className="section-head">
        <div>
          <div className="eyebrow">Reflex log</div>
          <h1>Every decision, and why</h1>
          <p>One local Decider request every 2.5 s asks "does rule N apply right now?" for each rule. Code applies the rulebook's order. Nothing here was sent to the cloud.</p>
        </div>
        <div className="row wrap">
          <span className="chip num">{decisions.length} decisions</span>
          <span className="chip num">p50 {p50} ms</span>
          <div className="tabs" role="tablist" aria-label="Filter">
            <button role="tab" aria-selected={onlyActs} onClick={() => setOnlyActs(true)}>
              Actions
            </button>
            <button role="tab" aria-selected={!onlyActs} onClick={() => setOnlyActs(false)}>
              All
            </button>
          </div>
        </div>
      </div>
      <div className="two-col">
        <div className="feed">
          {list.length === 0 && <div className="card muted">{onlyActs ? 'No actions yet. Switch to All to see quiet ticks.' : 'No decisions yet.'}</div>}
          {list.slice(0, 60).map((d) => (
            <Item key={d.data.id} d={d} open={open === d.data.id} onToggle={() => setOpen(open === d.data.id ? null : d.data.id)} actions={actions} verifications={verifications} />
          ))}
        </div>
        <div className="side" style={{ position: 'sticky', top: 22 }}>
          <DecisionCard />
          {latest && (
            <div className="card">
              <div className="eyebrow">What the Decider read</div>
              <p className="muted" style={{ fontSize: '0.84rem', margin: '6px 0 0' }}>
                Code does the arithmetic and writes each verdict in words. The Decider only judges the words.
              </p>
              <pre className="state-text">{latest.data.state_text}</pre>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Item({
  d,
  open,
  onToggle,
  actions,
  verifications,
}: {
  d: Stamped<DecisionExt>;
  open: boolean;
  onToggle: () => void;
  actions: State['actions'];
  verifications: State['verifications'];
}) {
  const a = actions.find((x) => x.data.decision_id === d.data.id);
  const v = a ? verifications[a.data.id] : undefined;
  const tool = a?.data.tool ?? d.data.answers.next_action.choice;
  const meta = toolMeta(d.data.policy === 'quiet' && !a ? 'none' : tool);
  const Icon = meta.icon;
  const denied = a?.data.status === 'denied';
  return (
    <div>
      <button className={`feed-item ${a && !denied ? 'act' : ''} ${denied ? 'deny' : ''}`} onClick={onToggle} aria-expanded={open}>
        <span className="time num">{fmtTime(d.t)}</span>
        <span className="ico">
          <Icon size={17} />
        </span>
        <span>
          <span className="title">{a ? a.data.message || meta.verb : meta.label}</span>
          <br />
          <span className="sub">{d.data.reason ?? d.data.rule_ref ?? 'no rule applies'}</span>
        </span>
        <span className="row" style={{ gap: 6 }}>
          {denied && <span className="chip warn">held by {a?.data.gate.name}</span>}
          {v && <span className={`chip ${v.data.outcome === 'worked' ? 'ok' : v.data.outcome === 'worse' ? 'bad' : ''}`}>{v.data.outcome}</span>}
          <span className="chip num">{Math.round(d.data.latency_ms)} ms</span>
        </span>
      </button>
      {open && <pre className="state-text">{d.data.state_text}</pre>}
    </div>
  );
}

function median(xs: number[]) {
  if (!xs.length) return '--';
  const s = [...xs].sort((a, b) => a - b);
  return String(Math.round(s[Math.floor(s.length / 2)]));
}
