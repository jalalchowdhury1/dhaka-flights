#!/usr/bin/env python3
"""
Jev Client - Python side for communicating with the Jev Node server.

Provides pick(instructions, candidates, state) -> (choice or None, p)
Counts calls, ms, fallbacks into scraper.DIAG.
"""
import os
import subprocess
import time
import json
from typing import List, Tuple, Optional

class JevClient:
    """Client for the Jev element-pick server."""
    
    def __init__(self):
        self.process = None
        self.started = False
        self.calls = 0
        self.ms = 0
        self.timeouts = 0
    
    def start(self, env: dict = None) -> bool:
        """Start the Jev server process. Loads .env if not provided.
        
        Args:
            env: Environment dict for subprocess. If None, loads from .env
        
        Returns:
            True if server started successfully
        """
        # Load .env via python-dotenv like run_daily.py does
        if env is None:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
            env = os.environ.copy()
        
        jev_dir = os.path.join(os.path.dirname(__file__), "jev")
        node_path = "/Users/jalalchowdhury/.nvm/versions/node/v24.15.0/bin/node"
        
        try:
            self.process = subprocess.Popen(
                [node_path, os.path.join(jev_dir, "jev-server.mjs")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=jev_dir,
                text=True,
                bufsize=1
            )
            self.started = True
            return True
        except Exception as e:
            print(f"  WARN: Failed to start Jev server: {e}")
            return False
    
    def pick(self, instructions: str, candidates: List[str], state: str = "") -> Tuple[Optional[str], float]:
        """Get Jev to pick the best element from candidates.
        
        Args:
            instructions: Instructions for picking (e.g., "Pick the dropdown suggestion for Istanbul airport (IST)")
            candidates: List of candidate tree lines to choose from
            state: The page state/context
        
        Returns:
            Tuple of (choice or None, probability 0-1)
            On error or timeout, returns (None, 0)
        """
        if not self.started or self.process is None:
            return None, 0
        
        if not candidates:
            return None, 0
        
        if len(candidates) == 1:
            return candidates[0], 1.0
        
        request = {
            "id": int(time.time() * 1000) % 1000000,
            "site": "google-flights",
            "instructions": instructions,
            "state": state or "Real accessibility-tree elements read from the live Google Flights page right now.",
            "candidates": candidates
        }
        
        try:
            # Send request
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
            
            # Read response with timeout
            start = time.time()
            timeout = 3.0
            
            # Use select for timeout
            import select
            while time.time() - start < timeout:
                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                if ready:
                    line = self.process.stdout.readline().strip()
                    if line:
                        response = json.loads(line)
                        if response.get("id") == request["id"]:
                            self.ms += response.get("ms", 0)
                            self.calls += 1
                            choice = response.get("choice")
                            p = response.get("p", 0)
                            if response.get("error"):
                                return None, 0
                            return choice, p
                    break
            
            self.timeouts += 1
            return None, 0
            
        except subprocess.TimeoutExpired:
            self.timeouts += 1
            return None, 0
        except Exception as e:
            print(f"  WARN: Jev pick error: {e}")
            return None, 0
    
    def stop(self):
        """Stop the Jev server process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None
        self.started = False


# Global client instance
_jev_client = None

def get_client() -> Optional[JevClient]:
    """Get or create the global Jev client instance."""
    global _jev_client
    if _jev_client is None:
        _jev_client = JevClient()
    return _jev_client


def start() -> JevClient:
    """Start the Jev client. Returns the client instance."""
    client = get_client()
    client.start()
    return client


def stop():
    """Stop the Jev client."""
    global _jev_client
    if _jev_client:
        _jev_client.stop()
        _jev_client = None


def pick(instructions: str, candidates: List[str], state: str = "") -> Tuple[Optional[str], float]:
    """Pick an element using Jev.
    
    Args:
        instructions: Instructions for the pick
        candidates: List of candidate strings (tree lines)
        state: Page state context
    
    Returns:
        (choice, probability) tuple, or (None, 0) on error/fallback
    """
    client = get_client()
    if client is None or not client.started:
        return None, 0
    return client.pick(instructions, candidates, state)


def track_in_diag():
    """Update scraper.DIAG with Jev statistics."""
    import scraper
    if "_jev_client" in globals() and _jev_client:
        scraper.DIAG["jev_calls"] = _jev_client.calls
        scraper.DIAG["jev_ms"] = _jev_client.ms
        scraper.DIAG["jev_fallbacks"] = _jev_client.timeouts