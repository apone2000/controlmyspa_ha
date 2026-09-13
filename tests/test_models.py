"""Tests for parsing raw API payloads into spa state.

The fixture mirrors a real response from a live spa (an NGSC controller
reporting Fahrenheit while its celsius flag reads true), so the awkward parts
of the real data are covered rather than an idealised version of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import models

SpaState = models.SpaState


def _spa(tzl_state=None, **current_overrides):
    """Build a spa record shaped like the live API response."""
    uplink = datetime.now(timezone.utc)
    current = {
        "online": True,
        # Strings, two decimal places, and Fahrenheit despite the flag below.
        "currentTemp": "100.00",
        "desiredTemp": "100.00",
        "celsius": True,
        # Reported as 0 by controllers that do not have the hardware.
        "ambientTemp": 0,
        "hiLimitTemp": 0,
        "heaterMode": "READY",
        "heaterCooling": False,
        "tempRange": "HIGH",
        "runMode": "Ready",
        "temperatureReached": True,
        "errorCode": 0,
        "wifiConnectionHealth": "STRONG",
        "controllerType": "NGSC",
        "primaryTZLStatus": "TZL_NOT_PRESENT",
        "spaSerialNumber": "ZT-000000000000000",
        "reminderDaysFilter1": 0,
        "reminderDaysFilter2": 0,
        "reminderDaysWater": 0,
        "reminderDaysClearRay": 0,
        "uplinkTimestamp": uplink.isoformat(),
        # The API declares its own expiry, roughly three minutes out.
        "staleTimestamp": (uplink + timedelta(seconds=180)).isoformat(),
        "setupParams": {
            "lowRangeLow": 50,
            "lowRangeHigh": 99,
            "highRangeLow": 80,
            "highRangeHigh": 104,
        },
        "systemInfo": {"controllerSoftwareVersion": "M100_226 V65.0"},
    }
    current.update(current_overrides)
    return {
        "_id": "spa-abc-123",
        "currentState": current,
        "tzlState": tzl_state if tzl_state is not None else {},
    }


# --- temperature units -------------------------------------------------------


def test_fahrenheit_is_detected_despite_the_celsius_flag():
    """The celsius flag is a display preference and cannot be trusted.

    Observed live: celsius true on a spa reporting 100 with a 104 maximum.
    """
    state = SpaState.from_api(_spa(celsius=True))

    assert state.fahrenheit is True
    assert state.current_temp == 100.0


def test_celsius_is_detected_from_metric_limits():
    """A genuinely metric spa is identified by its limits, not its flag."""
    state = SpaState.from_api(
        _spa(
            celsius=False,
            currentTemp="37.80",
            setupParams={
                "lowRangeLow": 10,
                "lowRangeHigh": 37,
                "highRangeLow": 26,
                "highRangeHigh": 40,
            },
        )
    )

    assert state.fahrenheit is False


def test_unit_falls_back_to_the_flag_without_limits():
    """With no limits to judge by, the flag is all there is."""
    assert SpaState.from_api(_spa(celsius=True, setupParams={})).fahrenheit is False
    assert SpaState.from_api(_spa(celsius=False, setupParams={})).fahrenheit is True


def test_parses_string_temperatures_as_floats():
    """Temperatures arrive as strings and must become numbers."""
    state = SpaState.from_api(_spa())

    assert state.current_temp == 100.0
    assert isinstance(state.current_temp, float)


def test_blank_temperatures_become_none_rather_than_raising():
    """An offline spa reports empty strings where numbers normally sit."""
    state = SpaState.from_api(_spa(online=False, currentTemp="", desiredTemp=None))

    assert state.current_temp is None
    assert state.target_temp is None


def test_high_range_selects_high_setup_limits():
    """Climate limits follow the active temperature range."""
    state = SpaState.from_api(_spa(tempRange="HIGH"))

    assert (state.min_temp, state.max_temp) == (80.0, 104.0)


def test_low_range_selects_low_setup_limits():
    """The other range yields the other pair of limits."""
    state = SpaState.from_api(_spa(tempRange="LOW"))

    assert (state.min_temp, state.max_temp) == (50.0, 99.0)


# --- unreported fields -------------------------------------------------------


def test_zero_temperatures_are_treated_as_unreported():
    """Controllers report 0 for sensors they do not have."""
    state = SpaState.from_api(_spa())

    assert state.ambient_temp is None
    assert state.high_limit_temp is None


def test_zero_reminders_are_treated_as_unreported():
    """A literal 0 would read as 'due now' forever on spas that never set it."""
    state = SpaState.from_api(_spa())

    assert state.reminder_filter1 is None
    assert state.reminder_water is None


def test_real_reminder_values_are_kept():
    """Populated counters still come through."""
    state = SpaState.from_api(_spa(reminderDaysFilter1=30, reminderDaysWater=90))

    assert state.reminder_filter1 == 30
    assert state.reminder_water == 90


# --- staleness and availability ---------------------------------------------


def test_fresh_reading_is_available():
    """A reading inside its stated lifetime is usable."""
    state = SpaState.from_api(_spa())

    assert state.is_stale is False
    assert state.available is True


def test_expired_stale_timestamp_marks_data_stale():
    """Past the API's own expiry, plus grace, the reading is not trusted."""
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    state = SpaState.from_api(
        _spa(uplinkTimestamp=old.isoformat(), staleTimestamp=old.isoformat())
    )

    assert state.is_stale is True
    assert state.available is False


def test_slightly_late_uplink_does_not_flap():
    """A grace period absorbs an uplink arriving just after its expiry."""
    just_past = datetime.now(timezone.utc) - timedelta(seconds=30)
    state = SpaState.from_api(_spa(staleTimestamp=just_past.isoformat()))

    assert state.is_stale is False


def test_missing_stale_timestamp_falls_back_to_uplink_age():
    """Older payloads without staleTimestamp still get a staleness check."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    state = SpaState.from_api(
        _spa(staleTimestamp=None, uplinkTimestamp=old.isoformat())
    )

    assert state.is_stale is True


def test_no_timestamps_at_all_is_not_treated_as_stale():
    """Absence of both must not permanently disable every entity."""
    state = SpaState.from_api(_spa(staleTimestamp=None, uplinkTimestamp=None))

    assert state.is_stale is False


def test_offline_spa_is_unavailable():
    """Readings are withheld rather than published stale."""
    assert SpaState.from_api(_spa(online=False)).available is False


def test_zulu_timestamps_parse_to_aware_datetimes():
    """The API uses a trailing Z, which fromisoformat alone rejects."""
    state = SpaState.from_api(_spa(uplinkTimestamp="2026-09-13T12:00:00Z"))

    assert state.uplink_timestamp == datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_unparseable_timestamp_is_ignored():
    """Malformed timestamps must not raise during a poll."""
    assert (
        SpaState.from_api(_spa(uplinkTimestamp="not-a-date")).uplink_timestamp is None
    )


# --- lighting ----------------------------------------------------------------


def test_absent_tzl_yields_no_light_entity():
    """Spas with ordinary lights report TZL_NOT_PRESENT and expose no state.

    The lights work; the API simply does not report them, so no entity is
    created rather than one confidently reporting the wrong thing.
    """
    state = SpaState.from_api(_spa(primaryTZLStatus="TZL_NOT_PRESENT"))

    assert state.light_present is False
    assert state.light_on is None


def test_tzl_zones_at_zero_intensity_read_as_off():
    """With TZL fitted, intensity is the dependable signal."""
    state = SpaState.from_api(
        _spa(
            primaryTZLStatus="TZL_PRESENT",
            tzl_state={
                "tzlLightStatus": {"tzlZones": [{"zoneId": "1", "intensity": 0}]}
            },
        )
    )

    assert state.light_present is True
    assert state.light_on is False


def test_any_lit_zone_reads_as_on():
    """A single lit zone is enough for the light to count as on."""
    state = SpaState.from_api(
        _spa(
            primaryTZLStatus="TZL_PRESENT",
            tzl_state={
                "tzlLightStatus": {
                    "tzlZones": [
                        {"zoneId": "1", "intensity": 0},
                        {"zoneId": "2", "intensity": 4},
                    ]
                }
            },
        )
    )

    assert state.light_on is True


def test_tzl_present_without_zone_data_is_unknown():
    """Fitted but unreported is unknown, not off."""
    state = SpaState.from_api(_spa(primaryTZLStatus="TZL_PRESENT", tzl_state={}))

    assert state.light_present is True
    assert state.light_on is None


# --- identity and diagnostics ------------------------------------------------


def test_serial_falls_back_to_the_nested_field():
    """The serial is absent at top level on some responses."""
    spa = _spa()
    spa.pop("serialNumber", None)

    assert SpaState.from_api(spa).serial_number == "ZT-000000000000000"


def test_diagnostics_are_carried_through():
    """Device metadata used for the HA device page is parsed."""
    state = SpaState.from_api(_spa())

    assert state.controller_type == "NGSC"
    assert state.controller_version == "M100_226 V65.0"
    assert state.wifi_health == "STRONG"
    assert state.temperature_reached is True
    assert state.heating is False


def test_empty_payload_does_not_raise():
    """A sparse or unexpected response must not kill the poll loop."""
    state = SpaState.from_api({"_id": "x"})

    assert state.spa_id == "x"
    assert state.current_temp is None
    assert state.available is False
