"""Print a local voice pilot readiness summary from current env."""

from __future__ import annotations

from src.voice.config import VoiceConfig
from src.voice.pilot import build_voice_pilot_readiness


def main() -> None:
    report = build_voice_pilot_readiness(VoiceConfig())
    status = "READY" if report.ready else "NOT READY"
    print(f"Voice pilot readiness: {status}")
    print("Rollout switches:")
    for name, value in report.rollout_state.items():
        print(f"  - {name}: {value}")
    print("Checks:")
    for item in report.checks:
        marker = "OK" if item.ok else "FAIL"
        print(f"  - [{marker}] {item.name}: {item.detail}")


if __name__ == "__main__":
    main()
