#!/usr/bin/env python3
"""
Terminal CLI for approving/denying pending Claude Code requests.
Run this in a separate terminal window as an alternative to the web dashboard.

Usage:
    python cli.py                          # auto-refresh every 2s
    python cli.py --url http://host:8000   # custom server
"""

import argparse
import json
import os
import sys
import time
import urllib.request

SERVER_URL = os.environ.get("APPROVAL_SERVER_URL", "http://localhost:8000")


def get(path):
    with urllib.request.urlopen(f"{SERVER_URL}{path}", timeout=5) as r:
        return json.loads(r.read())


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def fmt_input(tool_input: dict) -> str:
    s = json.dumps(tool_input, indent=2)
    lines = s.splitlines()
    if len(lines) > 8:
        lines = lines[:8] + [f"  ... ({len(lines) - 8} more lines)"]
    return "\n    ".join(lines)


def run(server_url: str):
    global SERVER_URL
    SERVER_URL = server_url.rstrip("/")

    print(f"Claude Gate CLI — connected to {SERVER_URL}")
    print("Press Ctrl+C to quit.\n")

    while True:
        try:
            pending = get("/pending")
            pending = [r for r in pending if r.get("status") == "pending"]
        except Exception as e:
            print(f"\r[error] Cannot reach server: {e}   ", end="", flush=True)
            time.sleep(2)
            continue

        if not pending:
            print("\rWaiting for requests...   ", end="", flush=True)
            time.sleep(1)
            continue

        clear()
        print(f"Claude Gate CLI — {SERVER_URL}\n")
        print(f"{len(pending)} pending request(s):\n")

        for i, req in enumerate(pending, 1):
            age = int(time.time() - req["created_at"])
            cwd = f"  cwd: {req['cwd']}" if req.get("cwd") else ""
            print(f"  [{i}] {req['tool_name']}  ({age}s ago){cwd}")
            print(f"    {fmt_input(req['tool_input'])}")
            print()

        print("Enter: <number> a(llow) | <number> d(eny) | a(ll) a | a(ll) d")
        print("Example:  1 a   or   all d   (blank = refresh)\n> ", end="", flush=True)

        try:
            line = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            sys.exit(0)

        if not line:
            continue

        parts = line.split()
        if len(parts) != 2:
            print("Bad input, try again.")
            time.sleep(1)
            continue

        target, action = parts
        if action not in ("a", "allow", "d", "deny"):
            print("Action must be a(llow) or d(eny).")
            time.sleep(1)
            continue

        decision = "allow" if action in ("a", "allow") else "deny"

        targets = pending if target in ("all", "*") else []
        if not targets:
            try:
                idx = int(target) - 1
                if 0 <= idx < len(pending):
                    targets = [pending[idx]]
                else:
                    print("Number out of range.")
                    time.sleep(1)
                    continue
            except ValueError:
                print("Bad target. Use a number or 'all'.")
                time.sleep(1)
                continue

        for req in targets:
            try:
                post(f"/decision/{req['id']}", {"decision": decision})
                print(f"  → {decision.upper()}: {req['tool_name']}")
            except Exception as e:
                print(f"  → error sending decision: {e}")

        time.sleep(0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Gate terminal CLI")
    parser.add_argument("--url", default=SERVER_URL, help="Server URL")
    args = parser.parse_args()
    run(args.url)
