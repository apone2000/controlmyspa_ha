"""Tests for parsing raw API payloads into spa state.

The fixture mirrors a real response from a live spa (an NGSC controller
reporting Fahrenheit while its celsius flag reads true), so the awkward parts
of the real data are covered rather than an idealised version of it.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

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


def test_no_reading_sentinel_is_unknown_not_a_temperature():
    """Observed live: shown as 127.8C while the panel read "---".

    The pump had not run, so the sensor had no water reading. The portal
    discards anything above 150F or at or below 1F.
    """
    assert SpaState.from_api(_spa(currentTemp="262.00")).current_temp is None
    assert SpaState.from_api(_spa(currentTemp="150.50")).current_temp is None
    assert SpaState.from_api(_spa(currentTemp="1.00")).current_temp is None
    assert SpaState.from_api(_spa(currentTemp="150.00")).current_temp == 150.0
    assert SpaState.from_api(_spa(currentTemp="96.00")).current_temp == 96.0


def test_raw_water_temperature_keeps_what_the_api_sent():
    """The raw reading keeps the sentinel and is never replaced by a held value."""
    assert SpaState.from_api(_spa(currentTemp="262.00")).current_temp_raw == 262.0
    assert SpaState.from_api(_spa(currentTemp="96.00")).current_temp_raw == 96.0
    assert SpaState.from_api(_spa(currentTemp="")).current_temp_raw is None
    held = SpaState.from_api(_spa(currentTemp="262.00")).holding_water_temperature_from(
        SpaState.from_api(_spa(currentTemp="96.00"))
    )
    assert (held.current_temp, held.current_temp_raw) == (96.0, 262.0)


def test_a_fresh_reading_records_when_it_was_measured():
    """The measurement time is the uplink that carried the reading."""
    state = SpaState.from_api(_spa(currentTemp="96.00"))

    assert state.current_temp_at == state.uplink_timestamp
    assert state.current_temp_held is False
    assert SpaState.from_api(_spa(currentTemp="262.00")).current_temp_at is None


def test_last_good_reading_is_held_while_the_spa_has_none():
    """Graphs stay continuous, and the snapshot says the value is held."""
    earlier = datetime.now(timezone.utc) - timedelta(hours=3)
    previous = SpaState.from_api(
        _spa(currentTemp="96.00", uplinkTimestamp=earlier.isoformat())
    )

    held = SpaState.from_api(_spa(currentTemp="262.00")).holding_water_temperature_from(
        previous
    )
    still_held = SpaState.from_api(_spa(currentTemp="")).holding_water_temperature_from(
        held
    )

    assert (held.current_temp, held.current_temp_held) == (96.0, True)
    assert held.current_temp_at == earlier
    # Holding again keeps the original measurement time, not the last poll's.
    assert still_held.current_temp_at == earlier


def test_a_fresh_reading_ends_the_hold():
    """Once the pump runs, the real value replaces the held one."""
    previous = SpaState.from_api(_spa(currentTemp="262.00")).holding_water_temperature_from(
        SpaState.from_api(_spa(currentTemp="96.00"))
    )

    fresh = SpaState.from_api(_spa(currentTemp="98.00")).holding_water_temperature_from(
        previous
    )

    assert (fresh.current_temp, fresh.current_temp_held) == (98.0, False)


def test_nothing_to_hold_stays_unknown():
    """After a restart there is no earlier reading to carry over."""
    no_reading = SpaState.from_api(_spa(currentTemp="262.00"))

    assert no_reading.holding_water_temperature_from(None).current_temp is None
    assert (
        no_reading.holding_water_temperature_from(no_reading).current_temp_held
        is False
    )


def test_no_reading_sentinel_is_caught_in_celsius_data_too():
    """The window is applied in Fahrenheit whatever unit the data is in."""
    metric = {
        "lowRangeLow": 10,
        "lowRangeHigh": 37,
        "highRangeLow": 26,
        "highRangeHigh": 40,
    }
    assert SpaState.from_api(
        _spa(currentTemp="127.50", setupParams=metric)
    ).current_temp is None
    assert SpaState.from_api(
        _spa(currentTemp="38.00", setupParams=metric)
    ).current_temp == 38.0


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


def test_stale_reading_stays_available():
    """Staleness is informational and must never take entities offline.

    Regression test for the real failure: spas uplink far less often than the
    three-minute expiry the service stamps on each reading, so gating
    availability on it left every entity permanently unavailable.
    """
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    state = SpaState.from_api(
        _spa(uplinkTimestamp=old.isoformat(), staleTimestamp=old.isoformat())
    )

    assert state.is_stale is True
    assert state.is_expired is False
    assert state.available is True


def test_slightly_late_uplink_is_not_yet_stale():
    """A grace period absorbs an uplink arriving just after its expiry."""
    just_past = datetime.now(timezone.utc) - timedelta(seconds=30)
    state = SpaState.from_api(_spa(staleTimestamp=just_past.isoformat()))

    assert state.is_stale is False


def test_long_silence_marks_the_reading_expired():
    """A spa quiet for over an hour is not reporting, whatever its flag says."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    state = SpaState.from_api(_spa(uplinkTimestamp=old.isoformat()))

    assert state.is_expired is True
    assert state.available is False


def test_no_timestamps_at_all_is_not_treated_as_stale():
    """Absence of both must not permanently disable every entity."""
    state = SpaState.from_api(_spa(staleTimestamp=None, uplinkTimestamp=None))

    assert state.is_stale is False
    assert state.is_expired is False
    assert state.available is True


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


# --- components --------------------------------------------------------------

# Shaped like the live spa's current-state components, trimmed to one of each.
LIVE_COMPONENTS = [
    {"componentType": "GATEWAY", "value": "OFF"},
    {
        "componentType": "FILTER",
        "port": "0",
        "value": "ON",
        "availableValues": ["OFF", "ON", "DISABLED"],
    },
    {
        "componentType": "PUMP",
        "port": "1",
        "value": "OFF",
        "availableValues": ["OFF", "LOW", "HIGH"],
    },
    {
        "componentType": "PUMP",
        "port": "0",
        "value": "OFF",
        "availableValues": ["OFF", "LOW", "HIGH"],
    },
    {
        "componentType": "CIRCULATION_PUMP",
        "value": "OFF",
        "availableValues": ["OFF", "HIGH"],
    },
    {
        "componentType": "BLOWER",
        "port": 0,
        "value": "OFF",
        "availableValues": ["OFF", "LOW", "MED", "HIGH"],
    },
    {
        "componentType": "LIGHT",
        "port": 0,
        "value": "HIGH",
        "availableValues": ["OFF", "HIGH"],
    },
]


def _with_components(components=None, **current_state):
    """Build a snapshot from both records, as the coordinator does."""
    state = {"components": LIVE_COMPONENTS if components is None else components}
    state.update(current_state)
    return SpaState.from_api(_spa(), state)


def test_components_are_parsed_from_current_state():
    """The light is found by type and port with its value decoded."""
    light = _with_components().component("LIGHT", 0)

    assert light is not None
    assert light.value == "HIGH"
    assert light.is_on is True
    assert light.available_values == ("OFF", "HIGH")


def test_without_current_state_components_are_unknown():
    """Unread is distinct from a spa that reports nothing."""
    state = SpaState.from_api(_spa())

    assert state.components is None
    assert state.components_of("LIGHT") == []
    assert SpaState.from_api(_spa(), {}).components == ()


def test_string_and_integer_ports_are_equivalent():
    """Ports arrive either way and must match the same lookups."""
    state = _with_components()

    assert state.component("FILTER", 0) is not None
    assert [c.port for c in state.components_of("PUMP")] == [0, 1]


def test_malformed_component_entries_are_skipped():
    """A bad entry must not take the rest of the array down with it."""
    state = _with_components(["junk", {}, {"componentType": "LIGHT", "port": 0}])

    assert [c.component_type for c in state.components] == ["LIGHT"]
    assert state.component("LIGHT", 0).value == "OFF"


def test_component_values_decode_per_type():
    """Numbers, booleans and words all fold into the command vocabulary."""
    normalise = models.normalise_component_value

    assert normalise("3", "LIGHT") == "HIGH"
    assert normalise("2", "PUMP") == "HIGH"
    assert normalise("1", "OZONE") == "ON"
    assert normalise(True, "OZONE") == "ON"
    assert normalise("low", "BLOWER") == "LOW"
    assert normalise("", "LIGHT") == "OFF"
    assert normalise("9", "LIGHT") == "OFF"
    assert normalise("sideways", "LIGHT") == "OFF"


def test_disabled_reads_as_off():
    """A disabled filter cycle is not running."""
    component = models.Component("FILTER", 1, "DISABLED", ("OFF", "ON", "DISABLED"))

    assert component.is_on is False


def test_on_value_is_the_strongest_setting():
    """Verified live: HIGH is what switches an OFF/HIGH light on."""
    state = _with_components()

    assert state.component("LIGHT", 0).on_value == "HIGH"
    assert state.component("BLOWER", 0).on_value == "HIGH"
    shuffled = models.Component("BLOWER", 0, "OFF", ("HIGH", "OFF", "LOW"))
    assert shuffled.on_value == "HIGH"
    assert models.Component("OZONE", None, "OFF").on_value == "ON"


def test_components_are_addressed_as_the_portal_addresses_them():
    """Command tokens and deviceNumber follow the portal's own mapping."""
    state = _with_components()

    light = state.component("LIGHT", 0)
    assert (light.command_type, light.device_number) == ("light", 0)
    circ = state.component("CIRCULATION_PUMP", None)
    assert (circ.command_type, circ.device_number) == ("circ-pump", None)
    pump = state.component("PUMP", 1)
    assert (pump.command_type, pump.device_number) == ("jet", 1)
    assert state.component("GATEWAY", None).command_type is None


def test_with_component_value_leaves_the_original_untouched():
    """Optimistic updates build a new snapshot rather than editing the old."""
    state = _with_components()

    updated = state.with_component_value("LIGHT", 0, "OFF")

    assert updated.component("LIGHT", 0).value == "OFF"
    assert state.component("LIGHT", 0).value == "HIGH"
    assert updated.component("BLOWER", 0) == state.component("BLOWER", 0)
    unread = SpaState.from_api(_spa())
    assert unread.with_component_value("LIGHT", 0, "OFF") is unread


# --- target temperature ------------------------------------------------------


def test_target_temperature_prefers_current_state():
    """The portal's temperature control reads current-state."""
    assert _with_components(desiredTemp="102.00").target_temp == 102.0
    assert _with_components().target_temp == 100.0
    assert _with_components(desiredTemp="").target_temp == 100.0


def test_locks_prefer_current_state():
    """The portal's panel lock button reads current-state, False included."""
    assert _with_components(panelLock=True, tempLock=True).panel_lock is True
    assert SpaState.from_api(_spa(panelLock=True), {"panelLock": False}).panel_lock is False
    assert SpaState.from_api(_spa(tempLock=True), {"tempLock": False}).temp_lock is False
    assert SpaState.from_api(_spa(panelLock=True), {"components": []}).panel_lock is True
    assert SpaState.from_api(_spa(panelLock=True)).panel_lock is True


def test_temperature_range_prefers_current_state_and_sets_limits():
    """The portal's range control reads current-state; limits follow the range."""
    state = _with_components(tempRange="LOW")

    assert state.temp_range == "LOW"
    assert (state.min_temp, state.max_temp) == (50.0, 99.0)
    assert (_with_components().min_temp, _with_components().max_temp) == (80.0, 104.0)


def test_with_temp_range_switches_the_limits_too():
    """A range change shows at once, thermostat limits included."""
    state = SpaState.from_api(_spa())

    low = state.with_temp_range("LOW")

    assert (low.temp_range, low.min_temp, low.max_temp) == ("LOW", 50.0, 99.0)
    assert (state.temp_range, state.max_temp) == ("HIGH", 104.0)
    high = low.with_temp_range("HIGH")
    assert (high.min_temp, high.max_temp) == (80.0, 104.0)


def test_temperature_range_maps_onto_the_select_options():
    """The select offers high and low; anything else is unknown."""
    assert models.settable_temp_range("HIGH") == "high"
    assert models.settable_temp_range("low") == "low"
    assert models.settable_temp_range("") is None
    assert models.settable_temp_range(None) is None


def test_celsius_readings_use_the_portals_rounding():
    """Observed live: the portal showed 101F as 38.5 and 100F as 37.5.

    An exact conversion gives 38.3 and 37.8; the portal truncates to one
    decimal and then rounds to a half degree.
    """
    assert models.portal_celsius(101) == 38.5
    assert models.portal_celsius(100) == 37.5
    assert models.portal_celsius(102) == 39.0
    assert models.portal_celsius(104) == 40.0
    assert models.portal_celsius(80) == 26.5


def test_readings_convert_only_when_shown_in_celsius():
    """Fahrenheit shown as Fahrenheit, and Celsius data, pass through."""
    assert models.display_temperature(100.0, True, True) == 37.5
    assert models.display_temperature(100.0, True, False) == 100.0
    assert models.display_temperature(37.8, False, True) == 37.8
    assert models.display_temperature(None, True, True) is None


def test_fahrenheit_targets_are_sent_as_whole_degrees():
    """Halves round up, as the portal's Math.round does."""
    assert models.command_temperature(101.4, celsius=False) == 101.0
    assert models.command_temperature(100.5, celsius=False) == 101.0
    assert models.command_temperature(99.5, celsius=False) == 100.0


def test_celsius_targets_are_sent_as_whole_fahrenheit():
    """Observed live: 100.5F was accepted but the spa stored 100.

    So a Celsius target goes out as the nearest whole degree Fahrenheit.
    """
    assert models.command_temperature(40.0, celsius=True) == 104.0
    assert models.command_temperature(38.5, celsius=True) == 101.0
    assert models.command_temperature(37.5, celsius=True) == 100.0
    # 38.0 has no whole-degree equivalent (100F reads 37.5, 101F reads 38.5).
    assert models.command_temperature(38.0, celsius=True) == 100.0


def test_every_displayable_celsius_value_round_trips():
    """Choosing any Celsius value the spa shows sets the degree that shows it."""
    for fahrenheit in range(80, 105):
        shown = models.portal_celsius(fahrenheit)
        assert models.command_temperature(shown, celsius=True) == fahrenheit, shown


def test_targets_are_clamped_to_the_fahrenheit_limits():
    """A target past the range limits is pulled back inside them."""
    assert models.command_temperature(26.0, True, low=80, high=104) == 80
    assert models.command_temperature(110, False, low=80, high=104) == 104


# --- heater mode -------------------------------------------------------------


def test_heater_mode_prefers_current_state():
    """The portal's heat mode control reads current-state."""
    assert _with_components(heaterMode="REST").heater_mode == "REST"
    assert _with_components().heater_mode == "READY"


def test_heater_mode_states_include_ready_in_rest():
    """The sensor reports all three modes, and nothing it does not know."""
    assert models.heater_mode_state("READY") == "ready"
    assert models.heater_mode_state("REST") == "rest"
    assert models.heater_mode_state("READY_REST") == "ready_rest"
    assert models.heater_mode_state("BOOST") is None
    assert models.heater_mode_state(None) is None


def test_ready_in_rest_selects_as_rest():
    """Ready-in-Rest is Rest mode with the jets used; it cannot be chosen."""
    assert models.settable_heater_mode("READY") == "ready"
    assert models.settable_heater_mode("REST") == "rest"
    assert models.settable_heater_mode("READY_REST") == "rest"
    assert models.settable_heater_mode("BOOST") is None
    assert models.settable_heater_mode(None) is None


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


def test_spa_clock_is_read_from_current_state():
    """The portal's Set time dialog reads the clock from current-state."""
    state = _with_components(hour=14, minute=5, military=True,
                             rs485ConnectionActive=True)

    assert state.spa_time == time(14, 5)
    assert state.spa_military is True
    assert state.rs485_active is True


def test_current_state_clock_wins_over_the_spas_record():
    """Both records carry a clock; current-state is the one the portal trusts."""
    spa = _spa(hour=9, minute=0)
    state = SpaState.from_api(spa, {"components": [], "hour": 14, "minute": 5})

    assert state.spa_time == time(14, 5)


def test_midnight_is_a_real_clock_reading():
    """Hour and minute of zero mean 00:00, not a controller reporting nothing."""
    state = _with_components(hour=0, minute=0)

    assert state.spa_time == time(0, 0)


def test_a_spa_reporting_no_clock_reads_none():
    """Absent hour or minute is unknown rather than an invented midnight."""
    assert _with_components().spa_time is None
    assert _with_components(hour=14).spa_time is None


def test_out_of_range_clock_values_are_rejected():
    """A nonsense reading must not raise out of the parser."""
    assert _with_components(hour=25, minute=0).spa_time is None
    assert _with_components(hour=12, minute=99).spa_time is None


def test_with_spa_time_shows_a_new_reading_immediately():
    """Commands update the snapshot optimistically before the spa confirms."""
    state = _with_components(hour=9, minute=0).with_spa_time(time(14, 30))

    assert state.spa_time == time(14, 30)


def test_command_time_is_always_24_hour_hh_mm():
    """The command takes 24-hour HH:MM whatever the spa displays."""
    assert models.command_time(time(9, 5)) == "09:05"
    assert models.command_time(time(23, 59)) == "23:59"
    assert models.command_time(time(0, 0)) == "00:00"


def test_unreported_rs485_flag_is_unknown_not_a_dead_controller():
    """A spa that never reports the flag must keep its clock entity."""
    assert _with_components(hour=14, minute=5).rs485_active is None


def test_rs485_inactive_is_reported_as_false():
    """An explicit False is what makes the clock unreachable."""
    state = _with_components(hour=14, minute=5, rs485ConnectionActive=False)

    assert state.rs485_active is False


def test_filter_components_carry_their_schedule():
    """FILTER entries report when the cycle starts and how long it runs."""
    state = _with_components([
        {"componentType": "FILTER", "port": 0, "value": "ON",
         "hour": 0, "minute": 15, "durationMinutes": 315},
    ])
    cycle = state.component("FILTER", 0)

    assert cycle is not None
    assert cycle.start_time == time(0, 15)
    assert cycle.duration_minutes == 315


def test_a_filter_starting_at_midnight_is_not_treated_as_unreported():
    """00:00 is a real start time, and the default for filter 2."""
    state = _with_components([
        {"componentType": "FILTER", "port": 1, "value": "DISABLED",
         "hour": 0, "minute": 0, "durationMinutes": 15},
    ])

    assert state.component("FILTER", 1).start_time == time(0, 0)


def test_a_component_without_a_schedule_reports_none():
    """Only FILTER entries carry one; everything else must not invent it."""
    light = _with_components().component("LIGHT", 0)

    assert light.start_time is None
    assert light.duration_minutes is None
