import threading
import time

from myrmidon.bus import EventBus
from myrmidon.confirm import ConfirmBroker
from myrmidon.contract import errors


def setup():
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    return bus, ConfirmBroker(bus, deny_without_client=False), seen


def test_request_resolved_true():
    bus, broker, seen = setup()
    result = {}

    def ask():
        result["v"] = broker.request("Open email?", "Nothing is sent.", timeout_s=5)

    th = threading.Thread(target=ask)
    th.start()
    for _ in range(100):
        if broker.pending_ids():
            break
        time.sleep(0.01)
    rid = broker.pending_ids()[0]
    assert rid.startswith("c_")
    assert broker.resolve(rid, True)
    th.join(2)
    assert result["v"] is True
    assert seen[0]["type"] == "confirm_request" and errors(seen[0], "ServerEvent") == []


def test_timeout_is_deny():
    _, broker, _ = setup()
    assert broker.request("x", "y", timeout_s=0.05) is False
    assert broker.pending_ids() == []


def test_deny_all_and_async():
    _, broker, _ = setup()
    answers = []
    rid = broker.request_async("Ask", "Take a break?", answers.append)
    assert rid in broker.pending_ids()
    assert broker.deny_all() == 1
    assert answers == [False] and broker.pending_ids() == []
    assert broker.resolve(rid, True) is False  # already answered


def test_no_client_fails_closed():
    bus = EventBus()
    broker = ConfirmBroker(bus)  # deny_without_client=True by default
    got = []
    assert broker.request("x", "y", timeout_s=5) is False
    assert broker.request_async("x", "y", got.append) is None and got == [False]


def test_preapproval_tokens_are_single_use():
    _, broker, _ = setup()
    broker.preapprove("doctrine:3", ttl_s=5)
    assert broker.consume("doctrine:3") is True
    assert broker.consume("doctrine:3") is False
    broker.preapprove("doctrine:4", ttl_s=-1)
    assert broker.consume("doctrine:4") is False
