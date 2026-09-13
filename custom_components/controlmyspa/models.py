"""Parsing of raw API payloads into a typed snapshot of spa state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .const import FAHRENHEIT_THRESHOLD, STALE_AFTER, STALE_GRACE

_LOGGER = logging.getLogger(__name__)

# Controllers report 0 for hardware they do not have. A real reading of exactly
# zero is not meaningful for any of these fields (0F water is frozen, a zero
# high-limit is impossible, and a zero reminder would read as permanently due),
# so zero is treated as "not reported" rather than published as a value.
_ZERO_MEANS_UNREPORTED = True

TZL_ABSENT = "TZL_NOT_PRESENT"


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


def _as_float_reported(value: Any) -> float | None:
    """Coerce to a float, treating zero as an unreported field."""
    result = _as_float(value)
    if result == 0.0 and _ZERO_MEANS_UNREPORTED:
        return None
    return result


def _as_int(value: Any) -> int | None:
    """Coerce a value to an int, tolerating strings and blanks."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int_reported(value: Any) -> int | None:
    """Coerce to an int, treating zero as an unreported field."""
    result = _as_int(value)
    if result == 0 and _ZERO_MEANS_UNREPORTED:
        return None
    return result


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


def detect_fahrenheit(setup_params: dict[str, Any], celsius_flag: Any) -> bool:
    """Determine whether the payload's temperatures are in Fahrenheit.

    The payload's own ``celsius`` field describes how the mobile app displays
    temperatures, not the unit the API sends, and has been observed reading
    true on a spa reporting 104 as its maximum. The configured limits are a
    reliable substitute: every spa tops out near 40C / 104F, so a maximum above
    the threshold can only be Fahrenheit.
    """
    for key in ("highRangeHigh", "lowRangeHigh", "highRangeLow"):
        limit = _as_float(setup_params.get(key))
        if limit:
            return limit > FAHRENHEIT_THRESHOLD

    # No limits to judge by; fall back to the flag, inverted.
    return not bool(celsius_flag)


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
    # True when the API's temperatures are Fahrenheit, inferred from the
    # configured limits rather than taken from the unreliable celsius flag.
    fahrenheit: bool = True

    heater_mode: str | None = None
    heating: bool = False
    temp_range: str | None = None
    run_mode: str | None = None
    temperature_reached: bool = False
    min_temp: float | None = None
    max_temp: float | None = None

    error_code: int | None = None
    wifi_health: str | None = None
    controller_type: str | None = None
    controller_version: str | None = None

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

    # False when the API reports no readable light state. Spas with ordinary
    # (non-TZL) lights fall in here too: the lights work, but their state lived
    # in the removed components array and has no replacement in this payload.
    # No entity is created rather than one that reports a confident wrong value.
    light_present: bool = False
    light_on: bool | None = None

    uplink_timestamp: datetime | None = None
    stale_timestamp: datetime | None = None

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_stale(self) -> bool:
        """Return True when the last reading is too old to trust.

        The API states its own expiry via staleTimestamp; a grace period on top
        absorbs an uplink arriving slightly late without flapping entities.
        """
        now = datetime.now(timezone.utc)

        if self.stale_timestamp is not None:
            return now > self.stale_timestamp + timedelta(seconds=STALE_GRACE)

        if self.uplink_timestamp is not None:
            return (now - self.uplink_timestamp).total_seconds() > STALE_AFTER

        return False

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

        fahrenheit = detect_fahrenheit(setup, current.get("celsius"))

        # Which pair of setup limits applies depends on the active range.
        temp_range = current.get("tempRange")
        if isinstance(temp_range, str) and temp_range.upper().startswith("HIGH"):
            min_temp = _as_float(setup.get("highRangeLow"))
            max_temp = _as_float(setup.get("highRangeHigh"))
        else:
            min_temp = _as_float(setup.get("lowRangeLow"))
            max_temp = _as_float(setup.get("lowRangeHigh"))

        light_present, light_on = _parse_lighting(current, tzl)

        return cls(
            spa_id=str(spa.get("_id") or ""),
            serial_number=spa.get("serialNumber") or current.get("spaSerialNumber"),
            online=bool(current.get("online")),
            current_temp=_as_float(current.get("currentTemp")),
            target_temp=_as_float(current.get("desiredTemp")),
            ambient_temp=_as_float_reported(current.get("ambientTemp")),
            high_limit_temp=_as_float_reported(current.get("hiLimitTemp")),
            fahrenheit=fahrenheit,
            heater_mode=current.get("heaterMode"),
            heating=bool(current.get("heaterCooling")),
            temp_range=temp_range,
            run_mode=current.get("runMode"),
            temperature_reached=bool(current.get("temperatureReached")),
            min_temp=min_temp,
            max_temp=max_temp,
            error_code=_as_int(current.get("errorCode")),
            wifi_health=current.get("wifiConnectionHealth"),
            controller_type=current.get("controllerType"),
            controller_version=system.get("controllerSoftwareVersion"),
            panel_lock=bool(current.get("panelLock")),
            temp_lock=bool(current.get("tempLock")),
            settings_lock=bool(current.get("settingsLock")),
            access_locked=bool(current.get("accessLocked")),
            maintenance_locked=bool(current.get("maintenanceLocked")),
            eco_mode=bool(current.get("ecoMode")),
            soak_mode=bool(current.get("soakMode")),
            cleanup_cycle=bool(current.get("cleanupCycle")),
            priming_mode=bool(current.get("primingMode")),
            reminder_filter1=_as_int_reported(current.get("reminderDaysFilter1")),
            reminder_filter2=_as_int_reported(current.get("reminderDaysFilter2")),
            reminder_water=_as_int_reported(current.get("reminderDaysWater")),
            reminder_clearray=_as_int_reported(current.get("reminderDaysClearRay")),
            light_present=light_present,
            light_on=light_on,
            uplink_timestamp=_as_datetime(current.get("uplinkTimestamp")),
            stale_timestamp=_as_datetime(current.get("staleTimestamp")),
            raw=spa,
        )


def _parse_lighting(
    current: dict[str, Any], tzl: dict[str, Any]
) -> tuple[bool, bool | None]:
    """Return whether light state is readable, and whether it is lit.

    Every spa carries a tzlState block whether or not it has Tri-Zone Lighting;
    without it the block holds defaults that never update, so the controller's
    status flag decides whether the data means anything. A spa with ordinary
    lights reports TZL_NOT_PRESENT while its lights work perfectly well -- that
    state simply is not exposed by this endpoint.
    """
    status = current.get("primaryTZLStatus")
    if not status or status == TZL_ABSENT:
        return False, None

    zones = (tzl.get("tzlLightStatus") or {}).get("tzlZones") or []
    if not zones:
        return True, None

    # Intensity is the dependable signal; the accompanying state strings use a
    # vocabulary that has not been confirmed.
    intensities = [_as_int(zone.get("intensity")) for zone in zones]
    if all(value is None for value in intensities):
        return True, None

    return True, any(bool(value) for value in intensities)
