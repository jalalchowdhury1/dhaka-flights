#!/usr/bin/env python3
"""
Jev client — Python side of jev/jev-server.mjs.

pick(instructions, candidates, state) -> (choice or None, p)
One request per line on the server's stdin, one JSON reply per line on its
stdout, matched by id. Every failure path (no key, server down, timeout,
error reply) returns (None, 0) — the engine then uses its legacy fallback.
"""
import os
import json
import time
import select
import subprocess
from typing import List, Tuple, Optional

NODE = "/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin/node"
PICK_TIMEOUT_S = 3.0


class JevClient:
    def __init__(self):
        self.process = None
        self.started = False
        self.calls = 0
        self.ms = 0
        self.timeouts = 0
        self._next_id = 0

    def start(self, env: dict = None) -> bool:
        """Spawn the server. Returns False (and stays disabled) without a key."""
        if env is None:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
            env = os.environ.copy()
        if not env.get("AI_GATEWAY_API_KEY"):
            print("  WARN: AI_GATEWAY_API_KEY missing — Jev disabled, legacy picks only")
            self.started = False
            return False

        jev_dir = os.path.join(os.path.dirname(__file__), "jev")
        try:
            self._errlog = open(os.path.join(jev_dir, "jev-server.log"), "a")
            self.process = subprocess.Popen(
                [NODE, os.path.join(jev_dir, "jev-server.mjs")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._errlog,
                env=env,
                cwd=jev_dir,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            print(f"  WARN: failed to start Jev server: {e}")
            self.started = False
            return False

        time.sleep(0.5)
        if self.process.poll() is not None:
            print(f"  WARN: Jev server exited at start (code {self.process.returncode}) — see jev/jev-server.log")
            self.started = False
            return False
        self.started = True
        return True

    def pick(self, instructions: str, candidates: List[str], state: str = "") -> Tuple[Optional[str], float]:
        if not self.started or self.process is None or self.process.poll() is not None:
            return None, 0
        if not candidates:
            return None, 0
        if len(candidates) == 1:
            return candidates[0], 1.0

        self._next_id += 1
        req_id = self._next_id
        request = {
            "id": req_id,
            "site": "google-flights",
            "instructions": instructions,
            "state": state or "Real accessibility-tree elements read from the live Google Flights page right now.",
            "candidates": candidates,
        }
        try:
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
            deadline = time.time() + PICK_TIMEOUT_S
            while time.time() < deadline:
                ready, _, _ = select.select([self.process.stdout], [], [], 0.05)
                if not ready:
                    continue
                line = self.process.stdout.readline().strip()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                try:
                    resp = json.loads(line)
                except Exception:
                    continue
                if resp.get("id") != req_id:
                    continue          # a stale reply from an earlier timed-out call
                self.calls += 1
                self.ms += int(resp.get("ms", 0))
                if resp.get("error"):
                    return None, 0
                return resp.get("choice"), float(resp.get("p", 0) or 0)
            self.timeouts += 1
            return None, 0
        except Exception as e:
            print(f"  WARN: Jev pick error: {e}")
            return None, 0

    def stop(self):
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.started = False


_jev_client: Optional[JevClient] = None


def get_client() -> JevClient:
    global _jev_client
    if _jev_client is None:
        _jev_client = JevClient()
    return _jev_client


def start() -> JevClient:
    client = get_client()
    client.start()
    return client


def stop():
    global _jev_client
    if _jev_client:
        _jev_client.stop()
        _jev_client = None


def pick(instructions: str, candidates: List[str], state: str = "") -> Tuple[Optional[str], float]:
    client = get_client()
    if not client.started:
        return None, 0
    return client.pick(instructions, candidates, state)
