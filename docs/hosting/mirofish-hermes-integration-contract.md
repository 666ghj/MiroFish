# MiroFish Hermes Integration Contract

## Purpose

This document defines the minimum stable contract for Hermes and OpenClaw to use the MiroFish host safely.

## Canonical Paths

- Runtime: `/Users/Shared/OpenClaw/mirofish-runtime`
- Transcribes: `/Users/Shared/OpenClaw/transcribes`
- Source only: `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/airShare/MiroFish`

## Service Identity

- Service label: `com.openclaw.mirofish`
- Runtime owner: `airstride`
- Access model: LAN + SSH only

## Network Endpoints

- Frontend LAN URL: `http://10.0.0.161:3000`
- Backend LAN URL: `http://10.0.0.161:5001`
- Backend health: `http://10.0.0.161:5001/health`
- Frontend proxy health path: `http://10.0.0.161:3000/api/graph/project/list`

## SSH Access

- SSH alias: `openclaw-mirofish`
- SSH user: `airstride`

Recommended tunnels:

```bash
ssh -L 3000:127.0.0.1:3000 openclaw-mirofish
ssh -L 5001:127.0.0.1:5001 openclaw-mirofish
```

Tunnel-based local URLs:

- Frontend: `http://127.0.0.1:3000`
- Backend: `http://127.0.0.1:5001`

## Required Health Checks

Before Hermes or OpenClaw send operational work to MiroFish, the host should pass:

```bash
sudo launchctl print system/com.openclaw.mirofish
curl -sS http://127.0.0.1:5001/health
curl -sSI http://127.0.0.1:3000/
curl -sS http://127.0.0.1:3000/api/graph/project/list
```

Expected results:

- LaunchDaemon present in `system`
- Backend returns `{"service":"MiroFish Backend","status":"ok"}`
- Frontend returns `HTTP/1.1 200 OK`
- Frontend proxy returns a successful JSON payload

## Smoke Test

Use the canonical smoke test after reboot or maintenance:

```bash
/Users/Shared/OpenClaw/mirofish-runtime/scripts/host-smoke-test.sh
```

## Operational Data Rules

- Do not run MiroFish from iCloud.
- Do not write operational runtime state back into the iCloud source tree.
- Treat `/Users/Shared/OpenClaw/mirofish-runtime/backend/uploads` as persistent operational state.
- Treat `/Users/Shared/OpenClaw/transcribes` as the canonical local operational transcribes dataset.

## Consumption Rules

- Prefer SSH tunnels for operator access from other machines.
- Use LAN URLs only inside the trusted local network.
- Do not expose ports `3000` or `5001` through router forwarding or public internet ingress.
- Hermes and OpenClaw should assume MiroFish is a long-lived host service, not an ephemeral dev process.

## Operational Commands

From `/Users/Shared/OpenClaw/mirofish-runtime`:

```bash
./scripts/host-start.sh
./scripts/host-stop.sh
./scripts/host-status.sh
tail -f runtime/logs/backend.log
tail -f runtime/logs/frontend.log
```
