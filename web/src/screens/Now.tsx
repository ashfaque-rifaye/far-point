import { ArrowRight, Check, Eye, EyeOff, Glasses, Hourglass, Lightbulb, ShieldCheck, Timer } from 'lucide-react';
import { Iris } from '../components/Iris';
import { Ring, fmtDur, toolMeta } from '../components/ui';
import { useStore } from '../store';

const BAND_TEXT: Record<string, string> = {
  too_close: 'too close',
  close: 'a little close',
  healthy: 'comfortable',
  far: 'far back',
};

export function Now() {
  const s = useStore((x) => x.signals);
  const lastAction = useStore((x) => x.actions[x.actions.length - 1]);
  const lastVerified = useStore((x) => x.lastVerified);
  const stats = useStore((x) => x.stats);

  const mode = useStore((x) => (x.conn === 'demo' ? 'demo' : x.hello?.mode));
  const dist = s?.distance_cm ?? null;
  const band = s?.distance_band ?? null;
  const boutMin = (s?.bout_s ?? 0) / 60;

  return (
    <section className="now" aria-label="Now">
      <div className="hero">
        <div>
          <div className="eyebrow">{mode === 'live' ? 'Live · on this laptop' : mode === 'demo' ? 'Demo story · scripted numbers' : 'Replay · recorded numbers, real Decider'}</div>
          <h1 className="headline" style={{ marginTop: 10 }}>
            You're
            <span className={`inline-pill num ${band ?? ''}`} aria-live="polite">
              {dist !== null ? `${dist.toFixed(0)} cm` : '-- cm'}
            </span>
            <br />
            from the screen<span className="dim">,</span> <span className="dim">{band ? BAND_TEXT[band] : 'no face yet'}.</span>
          </h1>
        </div>
        <p className="lede">
          Myrmidon reads your distance, squint and blinks from the webcam, on this laptop. When your rules say so, it changes the screen
          and checks whether it helped.
        </p>
        <div className="metric-grid">
          <Metric icon={<Eye size={15} />} k="Eye opening vs. your baseline" v={s ? `${Math.round(s.squint * 100)}` : '--'} unit="%" bar={s ? Math.min(1, s.squint) : 0} warn={!!s?.squinting} />
          <Metric icon={<Timer size={15} />} k="Near-work bout" v={s ? fmtDur(s.bout_s).split(' ')[0] : '--'} unit={s && s.bout_s >= 60 ? 'min' : 's'} bar={Math.min(1, boutMin / 45)} warn={boutMin >= 45} />
          <Metric icon={<Hourglass size={15} />} k="Closer than 30 cm today" v={s ? (s.under30_today_s / 60).toFixed(1) : '--'} unit="min" />
          <Metric icon={<ShieldCheck size={15} />} k="Face images uploaded" v={String(stats?.face_images_uploaded ?? 0)} unit="ever" />
        </div>
      </div>

      <div className="stage" aria-label="Your eye, drawn from the measurements">
        <Iris s={s} />
        <div className="callout tl">
          <span className="k">Glasses</span>
          <b className="row" style={{ gap: 6 }}>
            <Glasses size={16} /> {s?.glasses_on === true ? 'On' : s?.glasses_on === false ? 'Off' : 'Unknown'}
          </b>
        </div>
        <div className="callout tr">
          <span className="k">Room light</span>
          <b className="row" style={{ gap: 6, textTransform: 'capitalize' }}>
            <Lightbulb size={16} /> {s?.ambient ?? '--'}
          </b>
        </div>
        <div className="callout bl">
          <span className="k">Blinks</span>
          <b className="num">{s ? `${Math.round(s.blink_per_min)}/min` : '--'}</b>
        </div>
        <div className="callout br">
          <span className="k">Looking at</span>
          <b className="row" style={{ gap: 6 }}>
            {s?.looking_at_screen === false ? <EyeOff size={16} /> : <Eye size={16} />}
            <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s?.looking_at_screen === false ? 'Far away' : s ? s.app.name : '--'}</span>
            {s && s.app.zoom_step !== 0 && <span className="chip grad">zoom {s.app.zoom_step > 0 ? '+' : ''}{s.app.zoom_step}</span>}
          </b>
        </div>
        <div className="zone-legend" aria-hidden="true">
          <span><i style={{ background: 'var(--zone-bad)' }} />under 30</span>
          <span><i style={{ background: 'var(--zone-close)' }} />30-40</span>
          <span><i style={{ background: 'var(--zone-good)' }} />40-70 cm</span>
        </div>
      </div>

      <div className="side">
        <DecisionCard />
        <div className="card verify-card" aria-live="polite">
          <div className="eyebrow">Did it help?</div>
          {lastVerified ? (
            <>
              <div className="verify-figure num">
                {lastVerified.data.before.distance_cm?.toFixed(0) ?? '--'}
                <ArrowRight size={22} />
                {lastVerified.data.after.distance_cm?.toFixed(0) ?? '--'} cm
              </div>
              <div style={{ fontWeight: 700 }}>
                {lastVerified.data.outcome === 'worked' ? 'Worked. ' : lastVerified.data.outcome === 'worse' ? 'Made it worse. ' : 'No change. '}
                <span className="muted">
                  {toolMeta(lastVerified.tool ?? '').verb}, checked {lastVerified.data.window_s} s later.
                  {lastVerified.data.before.squint != null && lastVerified.data.after.squint != null &&
                    ` Eye opening ${Math.round(lastVerified.data.before.squint * 100)}% to ${Math.round(lastVerified.data.after.squint * 100)}%.`}
                </span>
              </div>
            </>
          ) : (
            <p style={{ margin: '8px 0 0', fontWeight: 600 }}>
              Every change is checked against the camera numbers afterwards. Nothing to check yet.
            </p>
          )}
        </div>
        <StrainCard lastAction={lastAction?.data.message} />
      </div>
    </section>
  );
}

function StrainCard({ lastAction }: { lastAction?: string }) {
  const decision = useStore((x) => x.decisions[x.decisions.length - 1]);
  const strain = decision?.data.answers.strain;
  const level = strain?.level ?? 'relaxed';
  const v = strain ? strain.expected / 2 : 0;
  return (
    <div className="card">
      <div className="strain">
        <Ring value={Math.max(0.06, v)} size={92} tone={level === 'relaxed' ? 'grad' : 'warn'} label={`Strain ${level}`}>
          <span style={{ fontWeight: 800, textTransform: 'capitalize', fontSize: '0.85rem' }}>{level}</span>
        </Ring>
        <div>
          <div className="eyebrow">Strain signs</div>
          <div style={{ fontWeight: 700, marginTop: 4 }}>Counted in code, not guessed</div>
          <div className="muted" style={{ fontSize: '0.84rem' }}>
            Squinting, too close, break due, low blink rate.{lastAction ? ` Last: ${lastAction}` : ''}
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ icon, k, v, unit, bar, warn }: { icon: React.ReactNode; k: string; v: string; unit?: string; bar?: number; warn?: boolean }) {
  return (
    <div className="metric">
      <span className="k">
        {icon}
        {k}
      </span>
      <span className="v num">
        {v}
        {unit && <small>{unit}</small>}
      </span>
      {bar !== undefined && (
        <div className={`bar ${warn ? 'warn' : ''}`} aria-hidden="true">
          <i style={{ width: `${Math.round(bar * 100)}%` }} />
        </div>
      )}
    </div>
  );
}

export function DecisionCard({ compact = false }: { compact?: boolean }) {
  const d = useStore((x) => x.decisions[x.decisions.length - 1]);
  const hello = useStore((x) => x.hello);
  const action = useStore((x) => (d ? x.actions.find((a) => a.data.decision_id === d.data.id) : undefined));
  if (!d) {
    return (
      <div className="card">
        <div className="eyebrow">Decider 2B</div>
        <p className="muted">Waiting for the first decision (every 2.5 s).</p>
      </div>
    );
  }
  const dd = d.data;
  const choice = dd.answers.next_action.choice;
  const meta = toolMeta(choice);
  const Icon = meta.icon;
  const rules = dd.answers.rules ?? [];
  return (
    <div className="card" aria-live="polite">
      <div className="decision-head">
        <div className="eyebrow">Decider 2B · local GPU</div>
        <span className="chip num">{Math.round(dd.latency_ms)} ms</span>
      </div>
      <div className="big-action">
        <span className="icon-btn" style={{ width: 40, height: 40, background: dd.policy === 'act' ? 'var(--grad)' : 'var(--card-2)', color: dd.policy === 'act' ? 'var(--on-grad)' : 'var(--muted)' }}>
          <Icon size={19} />
        </span>
        {dd.policy === 'act' ? meta.label : dd.policy === 'ask' ? 'Ask you' : 'Stay quiet'}
      </div>
      <div className="muted" style={{ fontSize: '0.84rem' }}>
        {dd.reason ?? (dd.rule_ref ? `${dd.rule_ref} applies` : 'No rule applies right now.')}
        {dd.source === 'fallback' && ' Decider unavailable: fail quiet.'}
      </div>
      {!compact && rules.length > 0 && (
        <div className="rules" aria-label="Does each rule apply right now?">
          {rules.map((r) => (
            <div key={r.n} className={`rule-row ${r.state}`} title={`Rule ${r.n}: ${toolMeta(r.tool).label}`}>
              <span className="n">{r.n}</span>
              <div className="track">
                <i style={{ width: `${Math.max(3, (r.p ?? 0) * 100)}%` }} />
                <span className="th" style={{ left: '65%' }} />
                <span>{toolMeta(r.tool).label}</span>
              </div>
              <span className="p num">{r.p == null ? '--' : r.p.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="gate-line">
        <span className="chip">interrupt ok p={dd.answers.interrupt_ok.p.toFixed(2)}</span>
        {action && action.data.gate.name && (
          <span className={`chip ${action.data.gate.verdict === 'deny' ? 'warn' : 'ok'}`}>
            {action.data.gate.name}: {action.data.gate.verdict}
          </span>
        )}
        {action && action.data.status === 'done' && (
          <span className="chip ok">
            <Check size={13} /> done
          </span>
        )}
        {dd.escalation && <span className="chip warn">asked {dd.escalation.model.replace(/^.*?\./, '')}</span>}
        <span className="muted" style={{ marginLeft: 'auto', fontSize: '0.76rem' }}>
          {hello?.decider.model.replace('strands-decider-', 'Decider ') ?? ''}
        </span>
      </div>
    </div>
  );
}
