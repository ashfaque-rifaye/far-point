import { FileText, Mail, ShieldCheck } from 'lucide-react';
import { Markdown } from '../components/ui';
import { send } from '../transport';
import { setState, useStore } from '../store';

export function Report() {
  const report = useStore((x) => x.report);
  const loading = useStore((x) => x.reportLoading);
  const email = useStore((x) => x.email);
  const stats = useStore((x) => x.stats);

  const ask = (period: 'today' | 'week') => {
    setState({ reportLoading: true });
    send('request_report', { period });
    window.setTimeout(() => setState({ reportLoading: false }), 30000);
  };

  return (
    <section className="main" aria-label="Report">
      <div className="section-head">
        <div>
          <div className="eyebrow">For your optometrist</div>
          <h1>A report you can bring to your eye exam</h1>
          <p>Amazon Nova writes it from numbers only: minutes, counts and distances. It never sees an image of you, and it never sends anything.</p>
        </div>
        <div className="row wrap">
          <button className="btn grad" onClick={() => ask('today')} disabled={loading}>
            <FileText size={16} /> {loading ? 'Writing…' : 'Today'}
          </button>
          <button className="btn ghost" onClick={() => ask('week')} disabled={loading}>
            This week
          </button>
        </div>
      </div>
      <div className="two-col">
        <div className="card">
          {report ? (
            <>
              <div className="row between wrap" style={{ marginBottom: 6 }}>
                <span className="eyebrow">
                  {report.period === 'week' ? 'Weekly' : 'Daily'} report · {new Date(report.generated_at).toLocaleString()}
                </span>
                <span className="chip">{report.model}</span>
              </div>
              <Markdown text={report.markdown} />
            </>
          ) : (
            <div className="muted" style={{ padding: '30px 0' }}>
              No report yet. Pick Today or This week.
            </div>
          )}
        </div>
        <div className="side">
          <div className="card">
            <h3>Book an eye exam</h3>
            <p className="muted" style={{ fontSize: '0.86rem', margin: '4px 0 12px' }}>
              Nova drafts the email. Far Point asks you before it opens it in your mail app, and it never sends it for you.
            </p>
            {email ? (
              <>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>{email.subject}</div>
                {email.to && <div className="muted" style={{ fontSize: '0.84rem' }}>To: {email.to}</div>}
                <div className="email">{email.body}</div>
                <div className="row" style={{ marginTop: 10 }}>
                  <span className={`chip ${email.status === 'opened' ? 'ok' : email.status === 'pending_confirm' ? 'warn' : ''}`}>{email.status.replace('_', ' ')}</span>
                </div>
              </>
            ) : null}
            <button className="btn" style={{ marginTop: 12 }} onClick={() => send('draft_exam_email', {})}>
              <Mail size={16} /> {email ? 'Draft again' : 'Draft the email'}
            </button>
          </div>
          <div className="card">
            <div className="row" style={{ gap: 12 }}>
              <span className="icon-btn" style={{ background: 'var(--grad)', color: 'var(--on-grad)' }}>
                <ShieldCheck size={19} />
              </span>
              <div>
                <div style={{ fontWeight: 700 }}>{stats?.face_images_uploaded ?? 0} face images uploaded</div>
                <div className="muted" style={{ fontSize: '0.84rem' }}>
                  {stats?.bedrock_calls ?? 0} Bedrock calls today, text and numbers only.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
