"""Parsing of raw API payloads into a typed snapshot of spa state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .const import FAHRENHEIT_THRESHOLD, STALE_AFTER, STALE_GRACE

_LOGGER = logging.getLogger(__name__)

# Heater modes as the API reports them. READY_REST is a temporary state of Rest
# mode -- an hour of heating after the jets are used while resting -- that the
# spa enters on its own. It can be reported but not commanded.
HEATER_MODES = ("READY", "REST", "READY_REST")
SETTABLE_HEATER_MODES = ("READY", "REST")

# componentType as current-state reports it -> the token spa-commands expects.
# Taken from the portal's own mapping; anything absent cannot be commanded.
COMMAND_TYPES = {
    "PUMP": "jet",
    "CIRCULATION_PUMP": "circ-pump",
    "LIGHT": "light",
    "BLOWER": "blower",
    "MISTER": "mister",
    "MICROSILK": "microsilk",
    "AUX": "aux",
    "OZONE": "ozone",
}

# Types whose commands address one unit by its port as deviceNumber.
PORTED_TYPES = frozenset({"PUMP", "LIGHT", "BLOWER", "MISTER", "AUX"})

# Numeric component values decode per type: lights and blowers run a four-step
# scale, pumps a three-step one, and everything else is plain off/on.
NUMERIC_SCALES = {
    "LIGHT": ("OFF", "LOW", "MED", "HIGH"),
    "BLOWER": ("OFF", "LOW", "MED", "HIGH"),
    "PUMP": ("OFF", "LOW", "HIGH"),
    "CIRCULATION_PUMP": ("OFF", "LOW", "HIGH"),
}
COMPONENT_VALUES = frozenset({"DISABLED", "HIGH", "LOW", "MED", "OFF", "ON"})
_OFF_VALUES = frozenset({"OFF", "DISABLED"})
# Used to pick the strongest setting a component offers, whatever order the
# API lists them in.
_VALUE_RANK = {"OFF": 0, "DISABLED": 0, "LOW": 1, "MED": 2, "HIGH": 3, "ON": 3}

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


def normalise_component_value(value: Any, component_type: str) -> str:
    """Decode a raw component value into the OFF/LOW/MED/HIGH/ON vocabulary.

    Values arrive as words, as numeric strings, and occasionally as booleans,
    so all three are folded into the words the command endpoint accepts.
    """
    if value is None or value == "":
        return "OFF"
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    text = str(value).strip()
    if text.isdigit():
        scale = NUMERIC_SCALES.get(component_type, ("OFF", "ON"))
        index = int(text)
        return scale[index] if index < len(scale) else "OFF"
    upper = text.upper()
    return upper if upper in COMPONENT_VALUES else "OFF"


def heater_mode_state(mode: str | None) -> str | None:
    """Return the reported heater mode as a translatable state key."""
    if isinstance(mode, str) and mode.upper() in HEATER_MODES:
        return mode.lower()
    return None


def settable_heater_mode(mode: str | None) -> str | None:
    """Map the reported heater mode onto the two modes that can be commanded.

    READY_REST reads as Rest: the spa is still in Rest mode, heating for an
    hour because the jets were used, and returns to plain Rest by itself.
    """
    if not isinstance(mode, str):
        return None
    upper = mode.upper()
    if upper == "READY_REST":
        return "rest"
    if upper in SETTABLE_HEATER_MODES:
        return upper.lower()
    return None


@dataclass(frozen=True)
class Component:
    """One controllable device from the current-state components array."""

    component_type: str
    port: int | None
    value: str
    available_values: tuple[str, ...] = ()

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Component | None:
        """Build a component, or None for an entry with no type."""
        component_type = str(raw.get("componentType") or "").upper()
        if not component_type:
            return None
        return cls(
            component_type=component_type,
            port=_as_int(raw.get("port")),
            value=normalise_component_value(raw.get("value"), component_type),
            available_values=tuple(
                normalise_component_value(value, component_type)
                for value in raw.get("availableValues") or []
            ),
        )

    @property
    def is_on(self) -> bool:
        """Return True at any setting other than off."""
        return self.value not in _OFF_VALUES

    @property
    def on_value(self) -> str:
        """Return the state to send when switching this component on.

        The strongest setting it offers. Confirmed live as HIGH on a light
        offering OFF and HIGH.
        """
        choices = [value for value in self.available_values if value not in _OFF_VALUES]
        if not choices:
            return "ON"
        return max(choices, key=lambda value: _VALUE_RANK.get(value, 0))

    @property
    def command_type(self) -> str | None:
        """Return the token spa-commands expects, or None if not commandable."""
        return COMMAND_TYPES.get(self.component_type)

    @property
    def device_number(self) -> int | None:
        """Return the deviceNumber to send, for types addressed by port."""
        if self.component_type not in PORTED_TYPES:
            return None
        return self.port or 0


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

    # Tri-Zone Lighting only. Spas with ordinary lights report them as a LIGHT
    # entry in ``components`` instead.
    light_present: bool = False
    light_on: bool | None = None

    # From the separate current-state record. None when that could not be read,
    # which is distinct from a spa that reports no components.
    components: tuple[Component, ...] | None = None

    uplink_timestamp: datetime | None = None
    stale_timestamp: datetime | None = None

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def components_of(self, component_type: str) -> list[Component]:
        """Return every component of one type, in port order."""
        found = [c for c in self.components or () if c.component_type == component_type]
        return sorted(found, key=lambda c: c.port or 0)

    def component(self, component_type: str, port: int | None) -> Component | None:
        """Return the component of this type on this port, if reported."""
        for candidate in self.components or ():
            if candidate.component_type == component_type and candidate.port == port:
                return candidate
        return None

    def with_component_value(
        self, component_type: str, port: int | None, value: str
    ) -> SpaState:
        """Return a copy with one component's value replaced.

        Used to show a command's effect straight away instead of waiting for
        the next poll to read it back.
        """
        if self.components is None:
            return self
        return replace(
            self,
            components=tuple(
                replace(c, value=value)
                if (c.component_type, c.port) == (component_type, port)
                else c
                for c in self.components
            ),
        )

    @property
    def is_stale(self) -> bool:
        """Return True once the reading is past the expiry the API gave it.

        Informational only. Spas uplink well less often than the three-minute
        window the service attaches to each reading, so a stale reading here is
        routine rather than a fault, and this must not gate availability.
        """
        if self.stale_timestamp is None:
            return False
        return datetime.now(timezone.utc) > self.stale_timestamp + timedelta(
            seconds=STALE_GRACE
        )

    @property
    def is_expired(self) -> bool:
        """Return True when the last uplink is old enough to distrust entirely."""
        if self.uplink_timestamp is None:
            return False
        age = (datetime.now(timezone.utc) - self.uplink_timestamp).total_seconds()
        return age > STALE_AFTER

    @property
    def available(self) -> bool:
        """Return True when readings should be published rather than withheld.

        Driven by the spa's own online flag, which the service maintains from
        the gateway connection, with a long backstop for a spa that claims to
        be online while having gone quiet for an hour.
        """
        return self.online and not self.is_expired

    @classmethod
    def from_api(
        cls, spa: dict[str, Any], current_state: dict[str, Any] | None = None
    ) -> SpaState:
        """Build a snapshot from /web/spas and, when read, current-state."""
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

        components: tuple[Component, ...] | None = None
        heater_mode = current.get("heaterMode")
        if current_state is not None:
            parsed = (
                Component.from_api(raw)
                for raw in current_state.get("components") or []
                if isinstance(raw, dict)
            )
            components = tuple(c for c in parsed if c is not None)
            # The portal's heat mode control reads current-state, so prefer it.
            heater_mode = current_state.get("heaterMode") or heater_mode

        return cls(
            spa_id=str(spa.get("_id") or ""),
            serial_number=spa.get("serialNumber") or current.get("spaSerialNumber"),
            online=bool(current.get("online")),
            current_temp=_as_float(current.get("currentTemp")),
            target_temp=_as_float(current.get("desiredTemp")),
            ambient_temp=_as_float_reported(current.get("ambientTemp")),
            high_limit_temp=_as_float_reported(current.get("hiLimitTemp")),
            fahrenheit=fahrenheit,
            heater_mode=heater_mode,
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
            components=components,
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
    lights reports TZL_NOT_PRESENT while its lights work perfectly well -- their
    state is a LIGHT component in current-state, not part of this record.
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
