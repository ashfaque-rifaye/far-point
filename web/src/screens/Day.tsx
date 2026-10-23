import { useState } from 'react';
import { Activity, Bot, Coffee, Eye, Glasses, Hourglass, ShieldCheck, Sparkles } from 'lucide-react';
import { DistanceChart, Ring, fmtTime, toolMeta } from '../components/ui';
import { useStore } from '../store';

export function Day() {
  const stats = useStore((x) => x.stats);
  const samples = useStore((x) => x.samples);
  const actions = useStore((x) => x.actions);
  const verifications = useStore((x) => x.verifications);
  const [tab, setTab] = useState<'session' | 'today'>('session');

  const breaksRatio = stats && stats.breaks_offered ? stats.breaks_verified / stats.breaks_offered : 0;
  const worked = stats && stats.adaptations ? stats.adaptations_worked / stats.adaptations : 0;
  const done = actions.filter((a) => a.data.status === 'done' || a.data.status === 'denied').slice(-12).reverse();

  return (
    <section className="main" aria-label="Day">
      <div className="section-head">
        <div>
          <div className="eyebrow">{stats?.day ?? 'Today'}</div>
          <h1>Your eyes at the screen, today</h1>
          <p>Behavioral observations from the camera numbers. Not a diagnosis.</p>
        </div>
        <div className="tabs" role="tablist" aria-label="Range">
          <button role="tab" aria-selected={tab === 'session'} onClick={() => setTab('session')}>
            This session
          </button>
          <button role="tab" aria-selected={tab === 'today'} onClick={() => setTab('today')}>
            Today
          </button>
        </div>
      </div>

      <div className="stat-grid">
        <Stat icon={<Hourglass size={15} />} k="Closer than 30 cm" v={stats ? stats.under30_min.toFixed(1) : '--'} u="min" />
        <Stat icon={<Activity size={15} />} k="Longest near-work bout" v={stats ? String(Math.round(stats.longest_bout_min)) : '--'} u="min" />
        <Stat icon={<Eye size={15} />} k="Squint episodes" v={stats ? String(stats.squint_episodes) : '--'} />
        <Stat icon={<Glasses size={15} />} k="Glasses off while close" v={stats ? String(Math.round(stats.glasses_off_min)) : '--'} u="min" />
      </div>

      <div className="two-col">
        <div className="card chart-card">
          <div className="row between">
            <div>
              <h3>Viewing distance</h3>
              <div className="muted" style={{ fontSize: '0.84rem' }}>
                {tab === 'session' ? 'Live samples from this session (cm).' : 'The backend keeps per-day totals only; the curve shows this session.'}
              </div>
            </div>
            <span className="chip num">{samples.length} samples</span>
          </div>
          <DistanceChart samples={tab === 'session' ? samples.slice(-600) : samples} />
        </div>
        <div className="card">
          <h3>Breaks and adaptations</h3>
          <div className="row" style={{ gap: 20, marginTop: 14 }}>
            <Ring value={breaksRatio} size={110} label="Breaks verified">
              <div>
                <div className="display num" style={{ fontSize: '1.3rem' }}>
                  {stats ? `${stats.breaks_verified}/${stats.breaks_offered}` : '--'}
                </div>
                <div className="muted" style={{ fontSize: '0.7rem', fontWeight: 700 }}>
                  breaks
                </div>
              </div>
            </Ring>
            <Ring value={worked} size={110} label="Adaptations that worked">
              <div>
                <div className="display num" style={{ fontSize: '1.3rem' }}>
                  {stats ? `${stats.adaptations_worked}/${stats.adaptations}` : '--'}
                </div>
                <div className="muted" style={{ fontSize: '0.7rem', fontWeight: 700 }}>
                  worked
                </div>
              </div>
            </Ring>
          </div>
          <div className="row wrap" style={{ marginTop: 16, gap: 8 }}>
            <span className="chip ok">
              <Coffee size={13} /> streak {stats?.streak ?? 0}
            </span>
            <span className="chip">
              <Sparkles size={13} /> {stats?.decisions ?? 0} decisions, p50 {stats?.decider_p50_ms ?? '--'} ms
            </span>
            <span className="chip">
              <Bot size={13} /> Nova: {stats?.bedrock_calls ?? 0} calls, {stats?.bedrock_tokens ?? 0} tokens
            </span>
            <span className="chip grad">
              <ShieldCheck size={13} /> {stats?.face_images_uploaded ?? 0} face images uploaded
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>What Far Point did</h3>
        <div className="feed" style={{ marginTop: 12 }}>
          {done.length === 0 && <div className="muted">Nothing yet.</div>}
          {done.map((a) => {
            const meta = toolMeta(a.data.tool);
            const Icon = meta.icon;
            const v = verifications[a.data.id];
            const denied = a.data.status === 'denied';
            return (
              <div key={a.data.id} className={`feed-item ${denied ? 'deny' : 'act'}`} style={{ cursor: 'default' }}>
                <span className="time num">{fmtTime(a.t)}</span>
                <span className="ico">
                  <Icon size={17} />
                </span>
                <span>
                  <span className="title">{a.data.message || meta.verb}</span>
                  <br />
                  <span className="sub">
                    {a.data.gate.name ? `${a.data.gate.name} ${a.data.gate.verdict} (p=${a.data.gate.p?.toFixed(2)})` : 'No gate needed'}
                  </span>
                </span>
                <span>
                  {v ? (
                    <span className={`chip ${v.data.outcome === 'worked' ? 'ok' : ''}`}>
                      {v.data.outcome} · {v.data.before.distance_cm?.toFixed(0)}→{v.data.after.distance_cm?.toFixed(0)} cm
                    </span>
                  ) : denied ? (
                    <span className="chip warn">held</span>
                  ) : (
                    <span className="chip">checking…</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Stat({ icon, k, v, u }: { icon: React.ReactNode; k: string; v: string; u?: string }) {
  return (
    <div className="metric">
      <span className="k">
        {icon}
        {k}
      </span>
      <span className="v num">
        {v}
        {u && <small>{u}</small>}
      </span>
    </div>
  );
}
