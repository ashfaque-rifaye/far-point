import { useEffect, useState } from 'react';
import { BookOpen, CalendarDays, Contrast, FileText, Gauge, Moon, Settings2, Sun, X, Zap } from 'lucide-react';
import { Now } from './screens/Now';
import { Reflex } from './screens/Reflex';
import { Day } from './screens/Day';
import { Rulebook } from './screens/Rulebook';
import { Report } from './screens/Report';
import { Setup } from './screens/Setup';
import { Ring } from './components/ui';
import { dismissToast, setState, useStore } from './store';
import { HOSTED, enterDemo, send } from './transport';

type Screen = 'now' | 'reflex' | 'day' | 'rules' | 'report' | 'setup';
type Theme = 'day' | 'night' | 'contrast';

const NAV: { id: Screen; label: string; icon: typeof Gauge }[] = [
  { id: 'now', label: 'Now', icon: Gauge },
  { id: 'reflex', label: 'Reflex log', icon: Zap },
  { id: 'day', label: 'Day', icon: CalendarDays },
  { id: 'rules', label: 'Rulebook', icon: BookOpen },
  { id: 'report', label: 'Report', icon: FileText },
  { id: 'setup', label: 'Setup', icon: Settings2 },
];

function readHash(): Screen {
  const h = window.location.hash.replace('#', '') as Screen;
  return NAV.some((n) => n.id === h) ? h : 'now';
}

function readTheme(): Theme {
  const q = new URLSearchParams(window.location.search).get('theme') as Theme | null;
  if (q && ['day', 'night', 'contrast'].includes(q)) return q;
  try {
    const t = localStorage.getItem('fp-theme') as Theme | null;
    if (t && ['day', 'night', 'contrast'].includes(t)) return t;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'night' : 'day';
}

export function App() {
  const [screen, setScreen] = useState<Screen>(readHash);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const conn = useStore((x) => x.conn);
  const hello = useStore((x) => x.hello);
  const pendingRules = useStore((x) => x.proposals.some((p) => p.status === 'pending') || (x.doctrine ? !x.doctrine.approved : false));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('fp-theme', theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  useEffect(() => {
    const on = () => setScreen(readHash());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  useEffect(() => {
    // the live agent's dark_mode tool switches this page's theme
    const on = (e: Event) => setTheme((e as CustomEvent<Theme>).detail);
    window.addEventListener('myrmidon:theme', on);
    return () => window.removeEventListener('myrmidon:theme', on);
  }, []);
  const go = (s: Screen) => {
    window.location.hash = s === 'now' ? '' : s;
    setScreen(s);
  };

  const showOffline = (conn === 'offline' || conn === 'connecting') && !hello;

  return (
    <div className="shell">
      <a href="#main" className="sr-only">
        Skip to content
      </a>
      <div className="frame">
        <nav className="rail" aria-label="Screens">
          <Logo />
          {NAV.map((n) => {
            const Icon = n.icon;
            return (
              <button key={n.id} className="rail-btn" aria-current={screen === n.id ? 'page' : undefined} onClick={() => go(n.id)} aria-label={n.label}>
                <Icon size={21} />
                <span className="tip">{n.label}</span>
                {n.id === 'rules' && pendingRules && <span className="badge-dot" aria-label="needs your approval" />}
              </button>
            );
          })}
          <div className="rail-spacer" />
        </nav>
        <div className="main" id="main">
          <TopBar theme={theme} setTheme={setTheme} />
          {showOffline ? (
            <Offline />
          ) : (
            <>
              {screen === 'now' && <Now />}
              {screen === 'reflex' && <Reflex />}
              {screen === 'day' && <Day />}
              {screen === 'rules' && <Rulebook />}
              {screen === 'report' && <Report />}
              {screen === 'setup' && <Setup />}
            </>
          )}
        </div>
      </div>
      <BreakOverlay />
      <ConfirmModal />
      <Toasts />
    </div>
  );
}

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 64 64" role="img" aria-label="Myrmidon">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2fd3c4" />
          <stop offset="1" stopColor="#3b6cf6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="22" fill="var(--btn)" />
      <circle cx="32" cy="32" r="16" fill="none" stroke="url(#lg)" strokeWidth="5" />
      <circle cx="32" cy="32" r="6" fill="url(#lg)" />
      <circle cx="35.5" cy="28" r="2.2" fill="var(--on-btn)" />
    </svg>
  );
}

function TopBar({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  const hello = useStore((x) => x.hello);
  const conn = useStore((x) => x.conn);
  const stats = useStore((x) => x.stats);
  const last = useStore((x) => x.decisions[x.decisions.length - 1]);
  const dot = (st?: string) => (st === 'ready' || st === 'on' ? 'ok' : st === 'loading' || st === 'paused' || st === 'off' ? 'warn' : 'bad');
  return (
    <header className="topbar">
      <div className="wordmark">
        Myrmidon<i>.</i>
      </div>
      <div className="pills" aria-label="Status">
        {conn === 'demo' && <span className="pill demo">DEMO story, scripted numbers</span>}
        {conn === 'demo' && HOSTED && (
          <a className="pill live-cta" href="?live=1">Try it live with your webcam</a>
        )}
        {conn === 'live' && <span className="pill live">LIVE · your webcam, measured in this tab</span>}
        {hello?.mode === 'replay' && conn !== 'demo' && <span className="pill demo">Replay of a recorded session</span>}
        {conn === 'offline' && hello && <span className="pill"><span className="dot bad" />Reconnecting…</span>}
        <span className="pill">
          <span className={`dot ${dot(hello?.decider.status)}`} />
          {last?.data.source === 'fallback' && conn === 'live' ? 'Decider not available · code rules' : `Decider ${hello?.decider.status ?? '…'}`}
          {last && last.data.source !== 'fallback' && <span className="muted num">· {Math.round(last.data.latency_ms)} ms</span>}
        </span>
        <span className="pill">
          <span className={`dot ${dot(hello?.bedrock.status)}`} />
          Nova {hello?.bedrock.status ?? '…'}
        </span>
        <span className="pill">
          <span className={`dot ${dot(hello?.camera.status)}`} />
          Camera {hello?.camera.status ?? '…'}
        </span>
        <span className="pill privacy">
          <span className="dot ok" />
          <span className="num">{stats?.face_images_uploaded ?? 0}</span> face images uploaded
        </span>
      </div>
      <div className="theme-switch" role="group" aria-label="Theme">
        <button aria-pressed={theme === 'day'} onClick={() => setTheme('day')} aria-label="Day theme">
          <Sun size={16} />
        </button>
        <button aria-pressed={theme === 'night'} onClick={() => setTheme('night')} aria-label="Night theme">
          <Moon size={16} />
        </button>
        <button aria-pressed={theme === 'contrast'} onClick={() => setTheme('contrast')} aria-label="High contrast, large text">
          <Contrast size={16} /> Aa
        </button>
      </div>
    </header>
  );
}

function Offline() {
  const wsUrl = useStore((x) => x.wsUrl);
  return (
    <div className="offline">
      <div className="card">
        <div className="eyebrow">Not connected</div>
        <h2 style={{ fontSize: '1.7rem', margin: '8px 0' }}>Myrmidon's backend isn't running</h2>
        <p className="muted">Start it from the repo, then this page connects by itself.</p>
        <div className="code">.venv\Scripts\python.exe -m myrmidon.app --mode live</div>
        <p className="muted" style={{ fontSize: '0.82rem' }}>Trying {wsUrl}</p>
        <button className="btn grad" style={{ marginTop: 8 }} onClick={enterDemo}>
          Play the demo story instead
        </button>
      </div>
    </div>
  );
}

function BreakOverlay() {
  const b = useStore((x) => x.brk);
  if (!b) return null;
  const done = b.phase === 'verified';
  const left = Math.max(0, b.target_s - b.looking_away_s);
  return (
    <div className="break-screen" role="dialog" aria-modal="true" aria-label="Far-look break">
      <div className="horizon" />
      <div className="orb" />
      <div className="break-inner">
        <Ring value={b.looking_away_s / b.target_s} size={180} stroke={12} tone="light" label={`${Math.round(left)} seconds left`}>
          <div>
            <div className="display num" style={{ fontSize: '3rem', lineHeight: 1 }}>
              {done ? '✓' : Math.ceil(left)}
            </div>
            <div style={{ fontSize: '0.8rem', fontWeight: 700, opacity: 0.8 }}>{done ? 'verified' : 'seconds'}</div>
          </div>
        </Ring>
        <h1>{done ? 'Nice. Eyes reset.' : b.phase === 'offered' ? 'Look at something far away' : 'Keep looking far away'}</h1>
        <p>
          {done
            ? `Streak ${b.streak}. The camera saw you look away for ${b.target_s} seconds.`
            : 'Find something at least 6 metres away, out of a window or across the room. The camera counts the seconds you look away; looking back pauses the count.'}
        </p>
        {!done && (
          <button className="btn ghost" style={{ background: 'rgba(255,255,255,0.14)', color: '#fff', borderColor: 'rgba(255,255,255,0.3)' }} onClick={() => send('skip_break', { id: b.id })}>
            Skip this one
          </button>
        )}
      </div>
    </div>
  );
}

function ConfirmModal() {
  const c = useStore((x) => x.confirm);
  if (!c) return null;
  const answer = (approve: boolean) => {
    send('confirm', { request_id: c.request_id, approve });
    setState({ confirm: undefined });
  };
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="cf-title">
      <div className="modal">
        <div className="eyebrow">Your approval needed</div>
        <h2 id="cf-title" style={{ fontSize: '1.4rem', margin: '8px 0' }}>
          {c.title}
        </h2>
        <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>
          {c.detail}
        </p>
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 18 }}>
          <button className="btn ghost" onClick={() => answer(false)}>
            Not now
          </button>
          <button className="btn grad" autoFocus onClick={() => answer(true)}>
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}

function Toasts() {
  const toasts = useStore((x) => x.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.level}`}>
          <span>{t.text}</span>
          <button onClick={() => dismissToast(t.id)} aria-label="Dismiss">
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}
