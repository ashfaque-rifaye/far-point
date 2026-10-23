import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from myrmidon.config import Settings
from myrmidon.contract import errors
from myrmidon.dashboard import UI_MISSING, create_app
from myrmidon.runtime import Runtime

BASE = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765/ws"


def make(tmp_path, dist=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    trace = tmp_path / "empty.jsonl"
    trace.write_text('{"kind":"header","version":1}\n')
    s = Settings(mode="replay", trace=trace, runtime_dir=tmp_path, fake_decider=True, no_bedrock=True,
                 web_dist=dist or (tmp_path / "no-dist"))
    rt = Runtime(s, bedrock_available=False)
    return rt, create_app(rt)


def recv_until(ws, pred, limit=300):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if pred(msg):
            return msg, seen
    raise AssertionError(f"not received; got {[m['type'] for m in seen]}")


def cmd(name, **args):
    return json.dumps({"v": 1, "type": "cmd", "name": name, "args": args})


def test_connect_burst_order_and_schema(tmp_path):
    rt, app = make(tmp_path)
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect(WS, headers={"origin": BASE}) as ws:
            first = [ws.receive_json() for _ in range(3)]
            assert [m["type"] for m in first] == ["hello", "doctrine", "stats"]
            assert first[0]["data"]["mode"] == "replay"
            assert first[0]["data"]["decider"]["model"] == "FAKE oracle (tests/demo)"
            assert first[0]["data"]["bedrock"] == {"status": "off", "model": None}
            assert first[2]["data"]["face_images_uploaded"] == 0
            for m in first:
                assert errors(m, "ServerEvent") == []
    assert rt.stopped and rt.restored == {"zoom": True, "brightness": True, "theme": True}


def test_bad_origin_rejected(tmp_path):
    rt, app = make(tmp_path)
    with TestClient(app, base_url=BASE) as client:
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(WS, headers={"origin": "https://evil.example"}) as ws:
                ws.receive_json()
        assert e.value.code == 1008
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400  # Host check


def test_unknown_command_and_stale_approve_get_warning_toasts(tmp_path):
    rt, app = make(tmp_path)
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect(WS) as ws:  # no Origin header (non-browser client) is allowed
            ws.send_text(cmd("format_disk"))
            t, _ = recv_until(ws, lambda m: m["type"] == "toast" and "Unknown or invalid" in m["data"]["text"])
            assert t["data"]["level"] == "warning"
            ws.send_text(json.dumps({"v": 1, "type": "cmd", "name": "approve_doctrine", "args": {"version": "x"}}))
            recv_until(ws, lambda m: m["type"] == "toast" and "invalid" in m["data"]["text"])
            ws.send_text(cmd("approve_doctrine", version=99))
            t, _ = recv_until(ws, lambda m: m["type"] == "toast" and "out of date" in m["data"]["text"])
            assert t["data"]["level"] == "warning"
            ws.send_text(cmd("start_calibration", distance_cm=50))
            recv_until(ws, lambda m: m["type"] == "toast" and "replay mode" in m["data"]["text"])


def test_confirm_resolves_pending_request_and_disconnect_denies(tmp_path):
    rt, app = make(tmp_path)
    answers = []
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect(WS, headers={"origin": BASE}) as ws:
            rid = rt.broker.request_async("Take a break?", "Look away for 20 s", answers.append)
            msg, _ = recv_until(ws, lambda m: m["type"] == "confirm_request")
            assert msg["data"]["request_id"] == rid
            ws.send_text(cmd("confirm", request_id=rid, approve=True))
            for _ in range(100):
                if answers:
                    break
                import time
                time.sleep(0.02)
            assert answers == [True]
            rid2 = rt.broker.request_async("Again?", "x", answers.append)
            recv_until(ws, lambda m: m["type"] == "confirm_request" and m["data"]["request_id"] == rid2)
        # socket closed -> the open request is denied
        for _ in range(100):
            if len(answers) == 2:
                break
            import time
            time.sleep(0.02)
        assert answers == [True, False]


def test_pause_camera_resends_hello(tmp_path):
    rt, app = make(tmp_path)
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect(WS) as ws:
            ws.send_text(cmd("pause_camera", paused=True))
            msg, _ = recv_until(ws, lambda m: m["type"] == "hello" and m["data"]["camera"]["status"] == "paused")
            assert rt.loop.paused


def test_ui_notice_without_dist_and_static_with_dist(tmp_path):
    rt, app = make(tmp_path)
    with TestClient(app, base_url=BASE) as client:
        r = client.get("/")
        assert r.status_code == 200 and r.text == UI_MISSING
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Myrmidon</title><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    rt2, app2 = make(tmp_path / "two", dist=dist)
    with TestClient(app2, base_url=BASE) as client:
        r = client.get("/")
        assert r.status_code == 200 and "Myrmidon" in r.text
        assert client.get("/assets/app.js").status_code == 200
        with client.websocket_connect(WS) as ws:  # the WS route still wins over the static mount
            assert ws.receive_json()["type"] == "hello"
