# MiroFish Ops Contract

## Canonical Paths

- Runtime: `/Users/Shared/OpenClaw/mirofish-runtime`
- Transcribes: `/Users/Shared/OpenClaw/transcribes`
- Source only: `/Users/adrianlat/Library/Mobile Documents/com~apple~CloudDocs/airShare/MiroFish`

## Ownership

- Service owner: `airstride`
- LaunchDaemon label: `com.openclaw.mirofish`

## Local Health Checks

```bash
sudo launchctl print system/com.openclaw.mirofish
curl -sS http://127.0.0.1:5001/health
curl -sSI http://127.0.0.1:3000/
curl -sS http://127.0.0.1:3000/api/graph/project/list
```

## Post-Reboot Smoke Test

```bash
/Users/Shared/OpenClaw/mirofish-runtime/scripts/host-smoke-test.sh
```

## LAN + SSH Access

- Frontend: `http://10.0.0.161:3000`
- Backend: `http://10.0.0.161:5001`
- SSH alias: `openclaw-mirofish`
- SSH user: `airstride`

Recommended tunnels:

```bash
ssh -L 3000:127.0.0.1:3000 openclaw-mirofish
ssh -L 5001:127.0.0.1:5001 openclaw-mirofish
```

## Operational Rule

- Do not run MiroFish from iCloud.
- Do not change canonical runtime or transcribes paths without migration.
- Treat `backend/uploads` and shared transcribes as operational state.
