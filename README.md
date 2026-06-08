# Claude Remote Approval

Intercept Claude Code tool permission requests and approve/deny them remotely from a web dashboard or native iOS app.

## How it works

```
Claude Code needs to run a tool
  → PreToolUse hook fires → permission_hook.py
  → POSTs request to FastAPI server
  → Server pushes event to web/iOS via SSE
  → You tap Allow or Deny
  → Server records decision
  → Hook script gets decision, exits 0 (allow) or 2 (deny)
  → Claude Code proceeds or stops
```

---

## Quick Start (Local)

### 1. Start the server

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Open the web dashboard

Open `web/index.html` in a browser (double-click or `open web/index.html`).  
It connects to `http://localhost:8000` automatically.

### 3. Wire up the Claude Code hook

Edit `~/.claude/settings.json` (create if missing):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "APPROVAL_SERVER_URL=http://localhost:8000 python /absolute/path/to/hook/permission_hook.py"
          }
        ]
      }
    ]
  }
}
```

> **Tip:** Change `"Bash"` to `"*"` to require approval for every tool (Edit, Write, etc.), not just shell commands.

### 4. Run Claude Code

The next time Claude Code tries to run a Bash command, the web dashboard will show the request. Approve or deny it there.

---

## Cloud Deployment (access from anywhere, real iOS push)

### Deploy the server to Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
cd server
fly launch --name claude-approvals --no-deploy
fly deploy
```

Or Railway / Render — any platform that runs a Docker/Python app works.

### Update the hook to use your cloud URL

```json
"command": "APPROVAL_SERVER_URL=https://claude-approvals.fly.dev python /path/to/permission_hook.py"
```

### Point the web app at your cloud server

Enter your cloud URL in the "Connect" bar in `web/index.html`.

---

## iOS App

The iOS app in `ios/RemoteApproval/` is a SwiftUI project. Open it in Xcode (iOS 17+).

Features:
- Connects to your server via Server-Sent Events (same SSE stream as the web app — no APNs config needed)
- Shows pending requests in real time
- Allow / Deny buttons per request
- Local notifications when a new request arrives (works when app is foregrounded)
- Configurable server URL in-app

To get push notifications when the app is **backgrounded**, you need APNs (Apple Push Notification Service), which requires an Apple Developer account ($99/year). The current implementation uses local notifications only (no APNs config needed).

### Build steps

1. Open `ios/RemoteApproval/` in Xcode
2. Set your Team in Signing & Capabilities
3. Build & run on device or simulator
4. Tap "Server" in the top-right to enter your server URL

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APPROVAL_SERVER_URL` | `http://localhost:8000` | Server address the hook posts to |
| `APPROVAL_TIMEOUT` | `300` | Seconds to wait before auto-denying |

---

## Security

- Add an `Authorization` header check to the server if exposing to the internet
- Restrict the CORS origin list in `server/main.py` to your web app's URL
- The hook script auto-denies on timeout (default 5 min) to avoid leaving Claude Code hung

---

## Project Structure

```
claude-remote-approval/
├── server/
│   ├── main.py              # FastAPI server (SSE, long-poll, decisions)
│   └── requirements.txt
├── hook/
│   ├── permission_hook.py   # Claude Code PreToolUse hook script
│   └── settings_snippet.json
├── web/
│   └── index.html           # Single-file web dashboard
└── ios/
    └── RemoteApproval/
        ├── RemoteApprovalApp.swift
        ├── Models.swift
        ├── RequestStore.swift
        └── ContentView.swift
```
