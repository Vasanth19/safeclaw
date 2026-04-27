"""Tests for the in-memory SSE progress registry."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.progress import Install, registry  # noqa: E402


def test_publish_and_snapshot():
    inst = Install("abc123")
    inst.publish({"phase": "validating", "status": "ok", "message": "fine"})
    inst.publish({"phase": "secrets", "status": "start", "message": "go"})
    snap = inst.snapshot()
    assert len(snap) == 2
    assert snap[0]["phase"] == "validating"
    assert "ts" in snap[0]


def test_publish_rejects_non_dict():
    inst = Install("abc124")
    try:
        inst.publish("not a dict")  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError")


def test_subscribe_yields_events_then_closes():
    inst = Install("abc125")
    received: list[str] = []

    def consume():
        for chunk in inst.subscribe():
            received.append(chunk)

    t = threading.Thread(target=consume, daemon=True)
    t.start()

    # Let subscriber settle
    time.sleep(0.05)
    inst.publish({"phase": "validating", "status": "ok", "message": "x"})
    inst.publish({"phase": "done", "status": "ok", "message": "y"})
    inst.close()
    t.join(timeout=2.0)

    assert not t.is_alive(), "subscribe() should return after close()"
    blob = "".join(received)
    assert "validating" in blob
    assert "done" in blob
    assert "data: " in blob


def test_registry_create_and_get():
    inst = registry.create("xyz999")
    assert registry.get("xyz999") is inst
    try:
        registry.create("xyz999")  # duplicate
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on duplicate")
    registry.remove("xyz999")
    assert registry.get("xyz999") is None


def test_event_history_capped():
    inst = Install("cap1")
    for i in range(Install.MAX_EVENTS + 50):
        inst.publish({"phase": "x", "status": "progress", "message": str(i)})
    assert len(inst.snapshot()) == Install.MAX_EVENTS


if __name__ == "__main__":
    test_publish_and_snapshot()
    test_publish_rejects_non_dict()
    test_subscribe_yields_events_then_closes()
    test_registry_create_and_get()
    test_event_history_capped()
    print("progress: all tests passed")
