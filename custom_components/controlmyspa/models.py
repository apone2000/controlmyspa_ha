"""Parsing of raw API payloads into a typed snapshot of spa state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .const import STALE_AFTER

_LOGGER = logging.getLogger(__name__)


def _as_float(value: Any) -> float | None:
    """Coerce an API temperature to a float.

    Temperatures arrive as strings, and as empty strings while the spa is
    offline, so a plain float() here would raise during every outage.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Coerce a value to an int, tolerating strings and blanks."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    """Parse an API timestamp into an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class SpaState:
    """A single snapshot of spa state, already coerced to usable types."""

    spa_id: str
    serial_number: str | None = None

    online: bool = False
    current_temp: float | None = None
    target_temp: float | None = None
    ambient_temp: float | None = None
    high_limit_temp: float | None = None
    celsius: bool = True

    heater_mode: str | None = None
    heating: bool = False
    temp_range: str | None = None
    run_mode: str | None = None
    temperature_reached: bool = False
    min_temp: float | None = None
    max_temp: float | None = None

    error_code: int | None = None
    wifi_health: str | None = None
    controller_version: str | None = None
    heater_type: str | None = None
    heater_power: Any = None

    panel_lock: bool = False
    temp_lock: bool = False
    settings_lock: bool = False
    access_locked: bool = False
    maintenance_locked: bool = False

    eco_mode: bool = False
    soak_mode: bool = False
    cleanup_cycle: bool = False
    priming_mode: bool = False

    reminder_filter1: int | None = None
    reminder_filter2: int | None = None
    reminder_water: int | None = None
    reminder_clearray: int | None = None

    light_on: bool | None = None

    uplink_timestamp: datetime | None = None
    stale_timestamp: datetime | None = None

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_stale(self) -> bool:
        """Return True when the last uplink is too old to trust."""
        if self.uplink_timestamp is None:
            return False
        age = (datetime.now(timezone.utc) - self.uplink_timestamp).total_seconds()
        return age > STALE_AFTER

    @property
    def available(self) -> bool:
        """Return True when readings should be published rather than withheld.

        Entities go unavailable instead of holding the last known value, so a
        spa that drops off the network does not look like a spa sitting at a
        constant temperature.
        """
        return self.online and not self.is_stale

    @classmethod
    def from_api(cls, spa: dict[str, Any]) -> SpaState:
        """Build a snapshot from the raw record returned by /web/spas."""
        current = spa.get("currentState") or {}
        setup = current.get("setupParams") or {}
        system = current.get("systemInfo") or {}
        tzl = spa.get("tzlState") or {}

        # Which pair of setup limits applies depends on the active range.
        temp_range = current.get("tempRange")
        if isinstance(temp_range, str) and temp_range.upper().startswith("HIGH"):
            min_temp = _as_float(setup.get("highRangeLow"))
            max_temp = _as_float(setup.get("highRangeHigh"))
        else:
            min_temp = _as_float(setup.get("lowRangeLow"))
            max_temp = _as_float(setup.get("lowRangeHigh"))

        light_status = tzl.get("tzlLightStatus")
        light_on: bool | None
        if isinstance(light_status, bool):
            light_on = light_status
        elif isinstance(light_status, str):
            light_on = light_status.strip().upper() not in ("OFF", "0", "FALSE", "")
        elif isinstance(light_status, (int, float)):
            light_on = bool(light_status)
        else:
            light_on = None

        return cls(
            spa_id=str(spa.get("_id") or ""),
            serial_number=spa.get("serialNumber"),
            online=bool(current.get("online")),
            current_temp=_as_float(current.get("currentTemp")),
            target_temp=_as_float(current.get("desiredTemp")),
            ambient_temp=_as_float(current.get("ambientTemp")),
            high_limit_temp=_as_float(current.get("hiLimitTemp")),
            celsius=bool(current.get("celsius", True)),
            heater_mode=current.get("heaterMode"),
            heating=bool(current.get("heaterCooling")),
            temp_range=temp_range,
            run_mode=current.get("runMode"),
            temperature_reached=bool(current.get("temperatureReached")),
            min_temp=min_temp,
            max_temp=max_temp,
            error_code=_as_int(current.get("errorCode")),
            wifi_health=current.get("wifiConnectionHealth"),
            controller_version=system.get("controllerSoftwareVersion"),
            heater_type=system.get("heaterType"),
            heater_power=system.get("heaterPower"),
            panel_lock=bool(current.get("panelLock")),
            temp_lock=bool(current.get("tempLock")),
            settings_lock=bool(current.get("settingsLock")),
            access_locked=bool(current.get("accessLocked")),
            maintenance_locked=bool(current.get("maintenanceLocked")),
            eco_mode=bool(current.get("ecoMode")),
            soak_mode=bool(current.get("soakMode")),
            cleanup_cycle=bool(current.get("cleanupCycle")),
            priming_mode=bool(current.get("primingMode")),
            reminder_filter1=_as_int(current.get("reminderDaysFilter1")),
            reminder_filter2=_as_int(current.get("reminderDaysFilter2")),
            reminder_water=_as_int(current.get("reminderDaysWater")),
            reminder_clearray=_as_int(current.get("reminderDaysClearRay")),
            light_on=light_on,
            uplink_timestamp=_as_datetime(current.get("uplinkTimestamp")),
            stale_timestamp=_as_datetime(current.get("staleTimestamp")),
            raw=spa,
        )
