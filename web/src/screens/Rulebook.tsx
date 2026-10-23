import { useState } from 'react';
import { Check, PenLine, Sparkles, X } from 'lucide-react';
import { fmtTime } from '../components/ui';
import { send } from '../transport';
import { useStore } from '../store';

const ORIGIN_LABEL: Record<string, string> = {
  default: 'default',
  bedrock: 'written by Nova',
  user: 'yours',
  proposal: 'learned',
};

export function Rulebook() {
  const doctrine = useStore((x) => x.doctrine);
  const proposals = useStore((x) => x.proposals);
  const hello = useStore((x) => x.hello);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = proposals.filter((p) => p.status === 'pending');
  const bedrockOff = hello?.bedrock.status === 'off' || hello?.bedrock.status === 'down';

  return (
    <section className="main" aria-label="Rulebook">
      <div className="section-head">
        <div>
          <div className="eyebrow">Rulebook {doctrine ? `v${doctrine.version}` : ''}</div>
          <h1>Your rules, in priority order</h1>
          <p>The Decider checks each rule every 2.5 s. The first rule that applies picks the change. Nothing new takes effect until you approve it.</p>
        </div>
      </div>

      {doctrine && !doctrine.approved && (
        <div className="banner" role="status">
          <PenLine size={20} />
          <span className="grow">Draft v{doctrine.version} is waiting for you. Far Point keeps using the current rules until you adopt it.</span>
          <button className="btn grad" onClick={() => send('approve_doctrine', { version: doctrine.version })}>
            <Check size={17} /> Adopt v{doctrine.version}
          </button>
        </div>
      )}

      <div className="two-col">
        <div className="rulebook">
          {!doctrine && <div className="card muted">Waiting for the rulebook from the backend.</div>}
          {doctrine?.rules.map((r) => (
            <div key={r.n} className="rb-rule">
              <span className="n">{r.n}</span>
              <div>
                <div className="t">{r.text}</div>
                <div className="b">{r.basis}</div>
              </div>
              <div className="row" style={{ gap: 6, flexDirection: 'column', alignItems: 'flex-end' }}>
                <span className={`chip ${r.origin === 'proposal' ? 'grad' : r.origin === 'bedrock' ? 'ok' : ''}`}>{ORIGIN_LABEL[r.origin]}</span>
                {r.status !== 'active' && <span className="chip warn">{r.status}</span>}
              </div>
            </div>
          ))}
        </div>

        <div className="side">
          <div className="card">
            <h3>Describe your eyes</h3>
            <p className="muted" style={{ fontSize: '0.86rem', margin: '4px 0 12px' }}>
              In your own words. Amazon Nova turns it into a draft rulebook for you to review. Only this text goes to Bedrock.
            </p>
            <label htmlFor="eyes">Your eyes</label>
            <textarea
              id="eyes"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="I'm -3.5 in both eyes, 34, and I take my glasses off to read in the evening. Glare bothers me at night."
            />
            {doctrine?.source_text && (
              <p className="muted" style={{ fontSize: '0.8rem' }}>
                Current rules came from: "{doctrine.source_text}"
              </p>
            )}
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="btn"
                disabled={!text.trim() || busy}
                onClick={() => {
                  setBusy(true);
                  send('set_eye_description', { text: text.trim() });
                  window.setTimeout(() => setBusy(false), 6000);
                }}
              >
                <Sparkles size={16} /> {busy ? 'Drafting…' : 'Draft my rulebook'}
              </button>
              {bedrockOff && <span className="chip warn">Bedrock off</span>}
            </div>
          </div>

          <div className="card">
            <h3>Learned rules waiting for you</h3>
            <p className="muted" style={{ fontSize: '0.86rem', margin: '4px 0 12px' }}>
              When the Decider is unsure in the same kind of moment more than once, Nova proposes a rule.
            </p>
            {pending.length === 0 && <div className="muted">None right now.</div>}
            {pending.map((p) => (
              <div key={p.id} style={{ borderTop: '1px dashed var(--line)', paddingTop: 12, marginTop: 12 }}>
                <div style={{ fontWeight: 700 }}>{p.rule_text}</div>
                <div className="muted" style={{ fontSize: '0.84rem', margin: '4px 0' }}>
                  {p.reason}
                </div>
                {p.moments.map((m, i) => (
                  <div key={i} className="chip" style={{ marginRight: 6, marginTop: 4 }}>
                    {fmtTime(m.t)} · {m.note}
                  </div>
                ))}
                <div className="row" style={{ marginTop: 10 }}>
                  <button className="btn grad sm" onClick={() => send('approve_proposal', { id: p.id })}>
                    <Check size={15} /> Approve
                  </button>
                  <button className="btn ghost sm" onClick={() => send('reject_proposal', { id: p.id })}>
                    <X size={15} /> Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
