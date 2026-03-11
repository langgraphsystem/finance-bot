# Voice Launch Checklist

## Runtime switches

- `VOICE_ENABLED=true`
- `VOICE_ALLOW_OUTBOUND=false` for initial soft launch
- `VOICE_ALLOW_WRITE_TOOLS=false` for receptionist-only pilot
- `VOICE_RECEPTIONIST_ONLY=true` during first inbound pilot
- `VOICE_FORCE_CALLBACK_MODE=true` as emergency fallback mode

## Infrastructure

- Public HTTPS base URL reachable by Twilio
- Public WSS endpoint reachable by Twilio Media Streams
- Redis available for call sessions, trace, reviews, verification codes
- OpenAI Realtime API key configured
- Twilio Voice and SMS credentials configured

## Safety

- Telegram owner account linked for approvals and handoffs
- Verification SMS flow tested on a real phone
- Callback fallback tested with Telegram unavailable
- Approval-required tools tested from inbound calls
- Emergency switch to callback-only mode documented

## QA

- `pytest tests/test_voice -q`
- Synthetic scenarios pass:
  - `inbound_booking_success`
  - `sensitive_request_approval`
  - `realtime_failure`
- Review endpoints checked:
  - `/voice/review/recent`
  - `/voice/ops/overview`
  - `/voice/ops/switches`

## Pilot rollout

- Phase 1: `enabled=true`, `allow_outbound=false`, `allow_write_tools=false`, `receptionist_only=true`
- Phase 2: enable write tools for verified callers only
- Phase 3: enable outbound confirmation calls
- Phase 4: disable callback-only fallback after stable QA metrics

## Go-live watchpoints

- QA fail rate
- Approval volume
- Callback volume
- Handoff volume
- Verification completion rate
- Realtime transport errors
