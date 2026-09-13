"""Tests for parsing raw API payloads into spa state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import models

SpaState = models.SpaState


def _spa(**current_overrides):
    """Build a spa record shaped like the live API response."""
    current = {
        "online": True,
        "currentTemp": "37.5",
        "desiredTemp": "38.0",
        "ambientTemp": 18,
        "hiLimitTemp": 40,
        "celsius": True,
        "heaterMode": "READY",
        "heaterCooling": True,
        "tempRange": "HIGH",
        "runMode": "Ready",
        "temperatureReached": False,
        "errorCode": 0,
        "wifiConnectionHealth": "GOOD",
        "panelLock": False,
        "ecoMode": False,
        "reminderDaysFilter1": 30,
        "reminderDaysWater": 90,
        "uplinkTimestamp": datetime.now(timezone.utc).isoformat(),
        "setupParams": {
            "lowRangeLow": 10.0,
            "lowRangeHigh": 30.0,
            "highRangeLow": 26.0,
            "highRangeHigh": 40.0,
        },
        "systemInfo": {
            "controllerSoftwareVersion": "M100_226 V65.0",
            "heaterType": "STANDARD",
        },
    }
    current.update(current_overrides)
    return {
        "_id": "spa-abc-123",
        "serialNumber": "SN-0001",
        "currentState": current,
        "tzlState": {"tzlLightStatus": True},
    }


def test_parses_string_temperatures_as_floats():
    """Temperatures arrive as strings and must become numbers."""
    state = SpaState.from_api(_spa())

    assert state.current_temp == 37.5
    assert state.target_temp == 38.0
    assert isinstance(state.current_temp, float)


def test_blank_temperatures_become_none_rather_than_raising():
    """An offline spa reports empty strings where numbers normally sit."""
    state = SpaState.from_api(
        _spa(online=False, currentTemp="", desiredTemp=None, ambientTemp="")
    )

    assert state.current_temp is None
    assert state.target_temp is None
    assert state.ambient_temp is None


def test_high_range_selects_high_setup_limits():
    """Climate limits follow the active temperature range."""
    state = SpaState.from_api(_spa(tempRange="HIGH"))

    assert state.min_temp == 26.0
    assert state.max_temp == 40.0


def test_low_range_selects_low_setup_limits():
    """The other range yields the other pair of limits."""
    state = SpaState.from_api(_spa(tempRange="LOW"))

    assert state.min_temp == 10.0
    assert state.max_temp == 30.0


def test_offline_spa_is_unavailable():
    """Readings are withheld rather than published stale."""
    state = SpaState.from_api(_spa(online=False))

    assert state.online is False
    assert state.available is False


def test_old_uplink_marks_state_stale():
    """A spa claiming to be online but silent for hours is not trustworthy."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    state = SpaState.from_api(_spa(uplinkTimestamp=old.isoformat()))

    assert state.is_stale is True
    assert state.available is False


def test_recent_uplink_is_available():
    """A fresh reading from an online spa is usable."""
    state = SpaState.from_api(_spa())

    assert state.is_stale is False
    assert state.available is True


def test_missing_uplink_timestamp_is_not_treated_as_stale():
    """Absence of a timestamp should not permanently disable every entity."""
    state = SpaState.from_api(_spa(uplinkTimestamp=None))

    assert state.is_stale is False
    assert state.available is True


def test_zulu_timestamps_parse_to_aware_datetimes():
    """The API uses a trailing Z, which fromisoformat alone rejects."""
    state = SpaState.from_api(_spa(uplinkTimestamp="2026-09-13T12:00:00Z"))

    assert state.uplink_timestamp == datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_unparseable_timestamp_is_ignored():
    """Malformed timestamps must not raise during a poll."""
    state = SpaState.from_api(_spa(uplinkTimestamp="not-a-date"))

    assert state.uplink_timestamp is None


def test_diagnostics_and_identity_are_carried_through():
    """Device metadata used for the HA device page is parsed."""
    state = SpaState.from_api(_spa())

    assert state.spa_id == "spa-abc-123"
    assert state.serial_number == "SN-0001"
    assert state.controller_version == "M100_226 V65.0"
    assert state.wifi_health == "GOOD"
    assert state.reminder_filter1 == 30
    assert state.reminder_water == 90
    assert state.heating is True


def test_fahrenheit_flag_is_respected():
    """Unit follows the spa's own setting, not an assumption."""
    state = SpaState.from_api(_spa(celsius=False))

    assert state.celsius is False


def test_light_status_accepts_string_form():
    """Light state has been seen as a string rather than a boolean."""
    spa = _spa()
    spa["tzlState"]["tzlLightStatus"] = "OFF"
    assert SpaState.from_api(spa).light_on is False

    spa["tzlState"]["tzlLightStatus"] = "ON"
    assert SpaState.from_api(spa).light_on is True


def test_light_status_absent_yields_none():
    """An unknown light state is reported as unknown, not as off."""
    spa = _spa()
    spa["tzlState"] = {}

    assert SpaState.from_api(spa).light_on is None


def test_empty_payload_does_not_raise():
    """A sparse or unexpected response must not kill the poll loop."""
    state = SpaState.from_api({"_id": "x"})

    assert state.spa_id == "x"
    assert state.current_temp is None
    assert state.available is False
