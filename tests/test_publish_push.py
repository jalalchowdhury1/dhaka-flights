"""git push must retry, and a final failure must warn Telegram — a silently
stale dashboard was the failure mode this guards against."""
import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish


class FakeProc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _run_factory(push_results, calls):
    """subprocess.run stand-in: add/commit succeed, push pops push_results."""
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "push" in cmd:
            return push_results.pop(0)
        if "commit" in cmd:
            return FakeProc(0, out="committed")
        return FakeProc(0)
    return fake_run


def _write(monkeypatch, push_results):
    calls, warnings = [], []
    monkeypatch.setattr(publish.subprocess, "run",
                        _run_factory(push_results, calls))
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    monkeypatch.setattr(publish, "_telegram_warn", lambda msg: warnings.append(msg))
    publish.write_payload({"history": [], "updated": "t"})
    return calls, warnings


def test_push_succeeds_first_try_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch, [FakeProc(0)])
    assert len([c for c in calls if "push" in c]) == 1
    assert warnings == []


def test_push_retries_then_recovers(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="network"), FakeProc(0)])
    assert len([c for c in calls if "push" in c]) == 2
    assert warnings == []


def test_push_final_failure_warns_telegram(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="x"), FakeProc(1, err="x"),
                              FakeProc(1, err="x")])
    assert len([c for c in calls if "push" in c]) == 3
    assert len(warnings) == 1
    assert "stale" in warnings[0]


def test_write_payload_still_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(publish.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    publish.write_payload({"history": []})   # must not raise
