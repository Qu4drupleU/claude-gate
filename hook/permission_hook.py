#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — remote approval gate.

Claude Code passes tool details via stdin as JSON.
This script:
  1. POSTs the request to the approval server
  2. Long-polls for a decision
  3. Exits 0 (allow) or 2 (deny/block)

Wire it up in ~/.claude/settings.json:
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python /absolute/path/to/permission_hook.py"
          }
        ]
      }
    ]
  }
}

Set SERVER_URL to your server address:
  - Local:  http://localhost:8000
  - Cloud:  https://your-app.fly.dev
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

SERVER_URL = os.environ.get("APPROVAL_SERVER_URL", "http://localhost:8000")
POLL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "300"))  # seconds


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    # Read tool call details from stdin
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_input = {}

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input", {})
    session_id = hook_input.get("session_id")
    cwd = hook_input.get("cwd")

    # Register the request with the approval server
    try:
        resp = post_json(
            f"{SERVER_URL}/request",
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "session_id": session_id,
                "cwd": cwd,
            },
        )
        request_id = resp["request_id"]
    except Exception as e:
        # If server is unreachable, fail open (allow) so Claude Code isn't stuck
        sys.stderr.write(f"[approval hook] Server unreachable: {e}. Allowing by default.\n")
        sys.exit(0)

    sys.stderr.write(
        f"[approval hook] Waiting for remote approval of '{tool_name}' "
        f"(request_id={request_id}, timeout={POLL_TIMEOUT}s)...\n"
    )

    # Long-poll for decision
    try:
        result = get_json(
            f"{SERVER_URL}/poll/{request_id}?timeout={POLL_TIMEOUT}",
            timeout=POLL_TIMEOUT + 15,
        )
        decision = result.get("decision", "deny")
    except Exception as e:
        sys.stderr.write(f"[approval hook] Poll failed: {e}. Denying by default.\n")
        decision = "deny"

    if decision == "allow":
        sys.stderr.write(f"[approval hook] ALLOWED: {tool_name}\n")
        sys.exit(0)
    else:
        sys.stderr.write(f"[approval hook] DENIED: {tool_name}\n")
        # Output a block decision so Claude knows why
        print(json.dumps({"decision": "block", "reason": "Denied remotely by user"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
