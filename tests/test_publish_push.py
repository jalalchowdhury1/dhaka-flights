"""git push must retry, and a final failure must warn Telegram — a silently
stale dashboard was the failure mode this guards against. Also: a failed
commit must warn the same way (same silent-stale outcome), a rejected
(non-fast-forward) push must fail fast instead of burning all 3 retries on
something retries can never fix, and a non-serializable payload must never
truncate a good file that's already on disk."""
import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import publish


class FakeProc:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _run_factory(push_results, calls, commit=None):
    """subprocess.run stand-in: add succeeds, commit succeeds unless a
    FakeProc is given for it, push pops push_results."""
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "push" in cmd:
            return push_results.pop(0)
        if "commit" in cmd:
            return commit if commit is not None else FakeProc(0, out="committed")
        return FakeProc(0)
    return fake_run


def _write(monkeypatch, push_results, sleeps=None):
    calls, warnings = [], []
    monkeypatch.setattr(publish.subprocess, "run",
                        _run_factory(push_results, calls))
    monkeypatch.setattr(publish.time, "sleep",
                        (lambda s: sleeps.append(s)) if sleeps is not None
                        else (lambda s: None))
    monkeypatch.setattr(publish, "_telegram_warn", lambda msg: warnings.append(msg))
    publish.write_payload({"history": [], "updated": "t"})
    return calls, warnings


def test_push_attempts_derived_from_backoff_list():
    # A future bump of PUSH_ATTEMPTS without extending PUSH_BACKOFF_S would
    # IndexError inside write_payload's outer except and swallow the warning
    # — deriving one from the other makes that impossible.
    assert publish.PUSH_ATTEMPTS == len(publish.PUSH_BACKOFF_S) + 1


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
    sleeps = []
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="x"), FakeProc(1, err="x"),
                              FakeProc(1, err="x")], sleeps=sleeps)
    assert len([c for c in calls if "push" in c]) == 3
    assert len(warnings) == 1
    assert "stale" in warnings[0]
    assert sleeps == publish.PUSH_BACKOFF_S


def test_push_rejected_fails_fast_no_retries(monkeypatch, tmp_path):
    # A non-fast-forward rejection can't be fixed by waiting and retrying —
    # only `git pull --rebase` fixes it — so burning the 10s/30s backoff on
    # more of the same rejection just delays the useful warning.
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    sleeps = []
    calls, warnings = _write(monkeypatch,
                             [FakeProc(1, err="! [rejected]  main -> main "
                                             "(non-fast-forward)")],
                             sleeps=sleeps)
    assert len([c for c in calls if "push" in c]) == 1
    assert sleeps == []
    assert len(warnings) == 1
    assert "pull --rebase" in warnings[0]


def test_commit_failure_warns_telegram(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    calls, warnings = [], []
    broken_commit = FakeProc(1, err="fatal: Unable to create '.git/index.lock'")
    monkeypatch.setattr(publish.subprocess, "run",
                        _run_factory([], calls, commit=broken_commit))
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    monkeypatch.setattr(publish, "_telegram_warn", lambda msg: warnings.append(msg))
    publish.write_payload({"history": [], "updated": "t"})
    assert not any("push" in c for c in calls)   # push must never be attempted
    assert len(warnings) == 1
    assert "index.lock" in warnings[0]


def test_write_payload_still_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(publish, "REPO_DIR", str(tmp_path))

    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(publish.subprocess, "run", _boom)
    publish.write_payload({"history": []})   # must not raise


def test_nan_payload_does_not_clobber_existing_good_file(monkeypatch, tmp_path):
    # Serialize-before-write: json.dumps must run to completion (or raise)
    # BEFORE the live file is opened for writing, so an unserializable
    # payload leaves yesterday's good file untouched instead of half
    # (or fully) overwritten with garbage.
    data_file = tmp_path / "data.json"
    good_content = '{"history": [], "updated": "yesterday-good"}'
    data_file.write_text(good_content)
    monkeypatch.setattr(publish, "DATA_FILE", str(data_file))
    monkeypatch.setattr(publish, "REPO_DIR", str(tmp_path))  # keep backups/ local
    publish.write_payload({"history": [],
                           "flights": [{"price_total": float("nan")}]})
    assert data_file.read_text() == good_content
