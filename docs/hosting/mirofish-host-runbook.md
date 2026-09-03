# MiroFish Host Runbook

## Canonical Runtime

- Shared source of truth: `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/airShare/MiroFish`
- Canonical operational runtime: `/Users/Shared/OpenClaw/mirofish-runtime`
- Canonical operational transcribes: `/Users/Shared/OpenClaw/transcribes`

The runtime should live outside iCloud because always-on services need stable local files, virtual environments, logs, and uploads that are not subject to iCloud eviction or placeholder behavior.

The iCloud source for breathwork transcribes remains:

- `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/BreathWork/Transcribes`

That iCloud tree should be treated as source only. The shared operational copy should live in `/Users/Shared/OpenClaw/transcribes`.

## Ports

- Frontend: `3000`
- Backend: `5001`

## Commands

Run from the runtime root:

```bash
./scripts/host-start.sh
./scripts/host-stop.sh
./scripts/host-status.sh
tail -f runtime/logs/backend.log
tail -f runtime/logs/frontend.log
./scripts/host-smoke-test.sh
```

Sync transcribes from iCloud source to the shared operational path:

```bash
./scripts/sync-transcribes.sh
```

## SSH Tunnels

```bash
ssh -L 3000:127.0.0.1:3000 openclaw-mirofish
ssh -L 5001:127.0.0.1:5001 openclaw-mirofish
```

## Suggested SSH Alias

```sshconfig
Host openclaw-mirofish
  HostName 10.0.0.161
  User airstride
  ServerAliveInterval 30
  ServerAliveCountMax 3
  StrictHostKeyChecking accept-new
```

## Legacy LaunchAgent Template

The current persistent service is the system LaunchDaemon below, running as `airstride`.
Use this LaunchAgent template only for a user-session fallback.

The validated plist is:

- `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/airShare/MiroFish/ops/launchd/airshare.mirofish.plist`

It should be installed by a privileged shell or by a shell already running as `airstride`. If you are running as `airstride`, use:

```bash
cp /Users/adrianlat/Library/Mobile\ Documents/com~apple~CloudDocs/airShare/MiroFish/ops/launchd/airshare.mirofish.plist ~/Library/LaunchAgents/airshare.mirofish.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/airshare.mirofish.plist
launchctl kickstart -k gui/$(id -u)/airshare.mirofish
```

If you are running from another admin account, bootstrap into `airstride` requires root privileges or an interactive `airstride` session.

Template:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>airshare.mirofish</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>/Users/Shared/OpenClaw/mirofish-runtime/scripts/host-start.sh</string>
      <string>/Users/Shared/OpenClaw/mirofish-runtime</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/Shared/OpenClaw/mirofish-runtime</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>AbandonProcessGroup</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/Shared/OpenClaw/mirofish-runtime/runtime/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/Shared/OpenClaw/mirofish-runtime/runtime/logs/launchd.err.log</string>
  </dict>
</plist>
```

## Validated Constraints

- MiroFish is not run from iCloud.
- Runtime path is local and shared.
- SSH is LAN-only and should not be published through router/NAT.
- Docker was not available during validation, so source deployment is the active path.

## LaunchDaemon Migration

For a true always-on host, prefer the system LaunchDaemon:

- Source plist: `/Users/Shared/OpenClaw/mirofish-runtime/ops/launchd/com.openclaw.mirofish.plist`
- Installed plist: `/Library/LaunchDaemons/com.openclaw.mirofish.plist`
- Label: `com.openclaw.mirofish`
- User: `airstride`

Install with:

```bash
sudo /Users/Shared/OpenClaw/mirofish-runtime/scripts/install-mirofish-launchdaemon.sh
```

Validate with:

```bash
sudo launchctl print system/com.openclaw.mirofish
curl -sS http://127.0.0.1:5001/health
curl -sSI http://127.0.0.1:3000/
curl -sS http://127.0.0.1:3000/api/graph/project/list
```

## Hermes Integration

The canonical integration contract for Hermes and OpenClaw lives at:

- `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/airShare/MiroFish/docs/hosting/mirofish-hermes-integration-contract.md`
- `/Users/Shared/OpenClaw/mirofish-runtime/docs/hosting/mirofish-hermes-integration-contract.md`
