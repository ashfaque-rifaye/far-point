import { useState } from 'react';
import { Camera, CameraOff, Crosshair, Info, Ruler } from 'lucide-react';
import { send } from '../transport';
import { useStore } from '../store';

export function Setup() {
  const hello = useStore((x) => x.hello);
  const conn = useStore((x) => x.conn);
  const wsUrl = useStore((x) => x.wsUrl);
  const s = useStore((x) => x.signals);
  const [cm, setCm] = useState(50);
  const paused = hello?.camera.status === 'paused';

  return (
    <section className="main" aria-label="Setup">
      <div className="section-head">
        <div>
          <div className="eyebrow">Setup</div>
          <h1>Camera, calibration and privacy</h1>
          <p>Far Point measures distance from the size of your iris. Calibrate once at a distance you measured, and it stays accurate to about 10%.</p>
        </div>
      </div>
      <div className="two-col">
        <div className="card">
          <div className="row" style={{ gap: 12 }}>
            <span className="icon-btn" style={{ background: 'var(--grad)', color: 'var(--on-grad)' }}>
              <Ruler size={19} />
            </span>
            <div>
              <h3>Calibrate distance</h3>
              <div className="muted" style={{ fontSize: '0.86rem' }}>
                Sit with your eyes at a measured distance from the screen (a tape, or two A4 long sides = 59 cm), look at the screen, then press Calibrate.
              </div>
            </div>
          </div>
          <div className="row wrap" style={{ marginTop: 18, alignItems: 'flex-end' }}>
            <div style={{ width: 160 }}>
              <label htmlFor="cm">Measured distance (cm)</label>
              <input id="cm" type="number" min={25} max={100} value={cm} onChange={(e) => setCm(Number(e.target.value))} />
            </div>
            <button className="btn grad" disabled={!(cm >= 25 && cm <= 100) || !s?.face} onClick={() => send('start_calibration', { distance_cm: cm })}>
              <Crosshair size={16} /> Calibrate
            </button>
            {!s?.face && <span className="chip warn">No face in view</span>}
            {s?.face && s.distance_cm !== null && <span className="chip num">reading now: {s.distance_cm.toFixed(0)} cm</span>}
          </div>
        </div>

        <div className="side">
          <div className="card">
            <h3>Camera</h3>
            <p className="muted" style={{ fontSize: '0.86rem', margin: '4px 0 12px' }}>
              Frames are processed in memory on this laptop and dropped. None is saved or uploaded.
            </p>
            <button className="btn" onClick={() => send('pause_camera', { paused: !paused })} disabled={hello?.mode !== 'live'}>
              {paused ? <Camera size={16} /> : <CameraOff size={16} />} {paused ? 'Resume camera' : 'Pause camera'}
            </button>
            {hello?.mode !== 'live' && (
              <p className="muted" style={{ fontSize: '0.8rem' }}>
                The camera is not used in {conn === 'demo' ? 'demo' : 'replay'} mode.
              </p>
            )}
          </div>
          <div className="card">
            <div className="row" style={{ gap: 8 }}>
              <Info size={16} />
              <h3>System</h3>
            </div>
            <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 14px', fontSize: '0.86rem', margin: '12px 0 0' }}>
              <dt className="muted">Connection</dt>
              <dd style={{ margin: 0 }}>{conn} {conn !== 'demo' && <span className="muted">({wsUrl})</span>}</dd>
              <dt className="muted">Mode</dt>
              <dd style={{ margin: 0 }}>{hello?.mode ?? '--'}</dd>
              <dt className="muted">Decider</dt>
              <dd style={{ margin: 0 }}>
                {hello ? `${hello.decider.status}, ${hello.decider.model} on ${hello.decider.device}${hello.decider.vision ? ', images on' : ', text only'}` : '--'}
              </dd>
              <dt className="muted">Bedrock</dt>
              <dd style={{ margin: 0 }}>{hello ? `${hello.bedrock.status}${hello.bedrock.model ? `, ${hello.bedrock.model}` : ''}` : '--'}</dd>
              <dt className="muted">Camera</dt>
              <dd style={{ margin: 0 }}>{hello?.camera.status ?? '--'}</dd>
              <dt className="muted">Version</dt>
              <dd style={{ margin: 0 }}>{hello?.app_version ?? '--'}</dd>
            </dl>
          </div>
          <div className="card">
            <h3>Not a medical device</h3>
            <p className="muted" style={{ fontSize: '0.86rem', margin: '6px 0 0' }}>
              Far Point does not diagnose, treat or prevent any eye condition. Its thresholds come from a study of school-age children (Clouclip pilot, 2020) and are applied to adults as a starting point.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
