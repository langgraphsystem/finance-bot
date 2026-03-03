"""ScheduleConfig — Pydantic validation for schedule_config JSONB."""

import re
from datetime import datetime

from pydantic import BaseModel, field_validator


class ScheduleConfig(BaseModel):
    """Validated schedule configuration stored as JSONB in scheduled_actions."""

    time: str  # "08:00" local wall-clock
    days: list[int] | None = None  # 0=Mon..6=Sun for weekly
    day_of_month: int | None = None  # 1-31 for monthly, clamped on short months
    cron_expr: str | None = None  # P1: validated cron expression
    original_time: str | None = None  # preserved HH:MM for DST-safe advancement
    end_at: datetime | None = None  # P1: stop after this date
    max_runs: int | None = None  # P1: stop after N runs
    snooze_minutes: int = 10  # default snooze duration

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not re.match(r"^\d{1,2}:\d{2}$", v):
            raise ValueError(f"Invalid time format: {v!r}, expected HH:MM")
        h, m = v.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError(f"Time out of range: {v!r}")
        # Normalize to zero-padded HH:MM
        return f"{int(h):02d}:{int(m):02d}"

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        for d in v:
            if not (0 <= d <= 6):
                raise ValueError(f"Day index out of range: {d}, expected 0(Mon)..6(Sun)")
        return sorted(set(v))

    @field_validator("day_of_month")
    @classmethod
    def validate_day_of_month(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not (1 <= v <= 31):
            raise ValueError(f"Day of month out of range: {v}, expected 1..31")
        return v

    @field_validator("max_runs")
    @classmethod
    def validate_max_runs(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError(f"max_runs must be >= 1, got {v}")
        return v

    @field_validator("snooze_minutes")
    @classmethod
    def validate_snooze(cls, v: int) -> int:
        if not (1 <= v <= 1440):
            raise ValueError(f"snooze_minutes must be 1..1440, got {v}")
        return v
