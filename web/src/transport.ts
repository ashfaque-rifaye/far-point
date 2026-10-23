import { makeCommand, parseServerMessage, resolveWsUrl, type ClientCommand, type CommandArgsMap, type CommandName } from './contract';
import { getState, ingest, pushToast, setState } from './store';
import { startDemo, demoCommand } from './demo';

const BACKOFF = [1000, 2000, 4000, 10000];
let ws: WebSocket | null = null;
let attempt = 0;
let stopped = false;

function connect(url: string) {
  setState({ conn: 'connecting', wsUrl: url });
  let sock: WebSocket;
  try {
    sock = new WebSocket(url);
  } catch {
    scheduleReconnect(url);
    return;
  }
  ws = sock;
  sock.onopen = () => {
    attempt = 0;
    setState({ conn: 'open' });
  };
  sock.onmessage = (m) => {
    const r = parseServerMessage(m.data);
    if (r.ok) ingest(r.event);
    else if (r.reason !== 'unknown_type') console.warn('[myrmidon] dropped frame', r.reason, r.type);
  };
  sock.onclose = () => {
    if (ws === sock) ws = null;
    if (!stopped) {
      setState({ conn: 'offline' });
      scheduleReconnect(url);
    }
  };
  sock.onerror = () => sock.close();
}

function scheduleReconnect(url: string) {
  const delay = BACKOFF[Math.min(attempt, BACKOFF.length - 1)];
  attempt += 1;
  window.setTimeout(() => !stopped && connect(url), delay);
}

/** The backend only ever runs on this machine; served from anywhere else (the hosted demo), there is none. */
const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);

export function startTransport() {
  const search = window.location.search;
  const params = new URLSearchParams(search);
  if (params.has('demo') || !LOCAL_HOSTS.has(window.location.hostname)) {
    stopped = true;
    setState({ conn: 'demo', wsUrl: 'demo' });
    startDemo();
    return;
  }
  connect(resolveWsUrl(search, import.meta.env.VITE_WS_URL as string | undefined));
}

/** Switch from a dead socket into the built-in demo story (offline screen button). */
export function enterDemo() {
  stopped = true;
  ws?.close();
  setState({ conn: 'demo', wsUrl: 'demo' });
  startDemo();
}

export function send<K extends CommandName>(name: K, args: CommandArgsMap[K]) {
  const cmd = makeCommand(name, args);
  if (getState().conn === 'demo') {
    demoCommand(cmd as unknown as ClientCommand);
    return;
  }
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
  else pushToast('warning', 'Not connected to the Myrmidon backend.');
}
