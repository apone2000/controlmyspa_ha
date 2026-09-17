#!/usr/bin/env python3
"""Exercise the integration's control code against the live API, without HA.

Uses the integration's own api.py and models.py -- the same calls and parsing
the coordinator makes -- and prints what the light, blower and heat mode
entities would show.

    # read-only: what would the new entities report?
    python scripts/verify_controls.py --email you@example.com

    # send one command through the integration's client, then re-read
    python scripts/verify_controls.py --email you@example.com --light off
    python scripts/verify_controls.py --email you@example.com --blower on
    python scripts/verify_controls.py --email you@example.com --heat-mode rest
    python scripts/verify_controls.py --email you@example.com --temp 100
    python scripts/verify_controls.py --email you@example.com --temp-c 38.0
    python scripts/verify_controls.py --email you@example.com --panel-lock lock
    python scripts/verify_controls.py --email you@example.com --temp-range low
    python scripts/verify_controls.py --email you@example.com --time 14:30
    python scripts/verify_controls.py --email you@example.com --time now
    python scripts/verify_controls.py --email you@example.com --jet 1 on
    python scripts/verify_controls.py --email you@example.com --jet 1 off

Without --light, --blower, --heat-mode, --temp, --temp-c, --panel-lock or
--temp-range nothing is sent. --temp is in the unit the spa reports; --temp-c is
Celsius, converted as a Celsius Home Assistant would. A locked panel stops the
spa's own buttons working until it is unlocked again.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from datetime import time as dtime
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "controlmyspa"

_package = types.ModuleType("controlmyspa_verify")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_verify"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_verify.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_verify.{name}"] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
models = _load("models")
api = _load("api")

# Entity ids Home Assistant would generate for a device named "Spa".
ENTITY_PREFIX = {"LIGHT": "light.spa_light", "BLOWER": "switch.spa_blower"}


async def read(client, spa_id: str | None = None):
    """Fetch both records the way the coordinator does."""
    spa = await client.async_get_spa()
    spa_id = spa_id or str(spa.get("_id") or "")
    current = await client.async_get_current_state(spa_id)
    return spa_id, spa, current, models.SpaState.from_api(spa, current)


def show(spa: dict, current: dict, state) -> None:
    """Print what each new entity would report."""
    print(f"online={state.online} available={state.available}")
    if state.uplink_timestamp:
        age = (datetime.now(timezone.utc) - state.uplink_timestamp).total_seconds()
        print(f"last uplink {int(age)}s ago")

    print("\n=== heat mode ===")
    print(f"/web/spas heaterMode      = {(spa.get('currentState') or {}).get('heaterMode')!r}")
    print(f"current-state heaterMode  = {current.get('heaterMode')!r}")
    print(f"sensor.spa_heater_mode    = {models.heater_mode_state(state.heater_mode)!r}")
    print(f"select.spa_heat_mode      = {models.settable_heater_mode(state.heater_mode)!r}")

    unit = "F" if state.fahrenheit else "C"
    print("\n=== thermostat (climate.spa) ===")
    print(f"current {state.current_temp} {unit}, target {state.target_temp} {unit}, "
          f"heating={state.heating}")
    print(f"range {state.temp_range}: targets {state.min_temp}-{state.max_temp} {unit}")
    print(f"/web/spas tempRange       = {(spa.get('currentState') or {}).get('tempRange')!r}")
    print(f"current-state tempRange   = {current.get('tempRange')!r}")
    print(f"select.spa_temperature_range = {models.settable_temp_range(state.temp_range)!r}")
    if state.fahrenheit:
        def c(value):
            return models.display_temperature(value, True, True)

        print(f"in a Celsius HA: current {c(state.current_temp)} C, target "
              f"{c(state.target_temp)} C, targets {c(state.min_temp)}-{c(state.max_temp)} C")
    print(f"/web/spas desiredTemp     = {(spa.get('currentState') or {}).get('desiredTemp')!r}")
    print(f"current-state desiredTemp = {current.get('desiredTemp')!r}")

    web = spa.get("currentState") or {}
    print("\n=== locks ===")
    print(f"/web/spas panelLock       = {web.get('panelLock')!r}")
    print(f"current-state panelLock   = {current.get('panelLock')!r}")
    print(f"/web/spas tempLock        = {web.get('tempLock')!r}")
    print(f"current-state tempLock    = {current.get('tempLock')!r}")
    print(f"panel lock reads {state.panel_lock}, temperature lock reads {state.temp_lock}")

    print("\n=== clock ===")
    for label, record in (("/web/spas", web), ("current-state", current)):
        print(f"{label:<13} hour={record.get('hour')!r} minute={record.get('minute')!r} "
              f"military={record.get('military')!r} "
              f"rs485={record.get('rs485ConnectionActive')!r}")
    reading = state.spa_time
    print(f"spa clock reads {reading.strftime('%H:%M') if reading else None}, "
          f"24-hour display={state.spa_military}, rs485 active={state.rs485_active}")
    if reading is not None:
        now = datetime.now()  # noqa: DTZ005 - the spa keeps local time
        drift = (now.hour * 60 + now.minute) - (reading.hour * 60 + reading.minute)
        drift = (drift + 720) % 1440 - 720
        print(f"this Mac reads {now.strftime('%H:%M')}; the spa is {drift:+d} min from it")

    # Read straight from the raw record: the filter schedule fields are not on
    # Component, and parsing them lives on the parked filter-schedule branch.
    filters = [c for c in current.get("components") or []
               if isinstance(c, dict) and c.get("componentType") == "FILTER"]
    if filters:
        print("\n=== filter cycles ===")
        # The spa schedules by its own clock, so judge "running" against that.
        reference = state.spa_time or datetime.now().time()  # noqa: DTZ005
        clock = reference.hour * 60 + reference.minute
        for entry in sorted(filters, key=lambda c: int(c.get("port") or 0)):
            line = (f"port {entry.get('port')}  value={entry.get('value')!r}  "
                    f"hour={entry.get('hour')!r} minute={entry.get('minute')!r} "
                    f"durationMinutes={entry.get('durationMinutes')!r}")
            try:
                start = int(entry["hour"]) * 60 + int(entry["minute"])
                end = start + int(entry["durationMinutes"])
            except (KeyError, TypeError, ValueError):
                print(line)
                continue
            running = start <= clock < end or start <= clock + 1440 < end
            print(f"{line}\n{'':<10}-> {start // 60:02d}:{start % 60:02d}"
                  f"-{(end // 60) % 24:02d}:{end % 60:02d} "
                  f"({end - start} min), filtering now={running} "
                  f"at spa time {reference.strftime('%H:%M')}")

    print("\n=== components ===")
    if state.components is None:
        print("current-state unreadable -- light and blower would be unavailable")
        return
    print(f"{'type':<18} {'port':<5} {'value':<9} {'available':<22} command")
    for component in state.components:
        command = component.command_type or "-"
        if component.device_number is not None:
            command += f" #{component.device_number}"
        print(
            f"{component.component_type:<18} {str(component.port):<5} "
            f"{component.value:<9} {','.join(component.available_values):<22} {command}"
        )

    print("\n=== control entities ===")
    for component_type, entity_id in ENTITY_PREFIX.items():
        found = state.components_of(component_type)
        if not found:
            print(f"{entity_id:<22} not created (spa reports no {component_type})")
        for index, component in enumerate(found):
            suffix = f"_{index + 1}" if len(found) > 1 else ""
            print(
                f"{entity_id + suffix:<22} {'on' if component.is_on else 'off':<4}"
                f" (turn on sends {component.on_value})"
            )


async def main() -> int:
    """Show entity state, and send one command when asked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--light", choices=("on", "off"))
    group.add_argument("--blower", choices=("on", "off"))
    group.add_argument("--heat-mode", choices=("ready", "rest"))
    group.add_argument("--temp", type=float, metavar="DEGREES")
    group.add_argument("--temp-c", type=float, metavar="CELSIUS")
    group.add_argument("--panel-lock", choices=("lock", "unlock"))
    group.add_argument("--temp-range", choices=("high", "low"))
    group.add_argument("--time", metavar="HH:MM",
                       help="set the spa's own clock; 'now' uses this Mac's time")
    group.add_argument("--jet", nargs=2, metavar=("N", "STATE"),
                       help="set jet N (1, 2, 3...) to on, off, low or high")
    args = parser.parse_args()

    password = os.environ.get("CONTROLMYSPA_PASSWORD") or getpass.getpass("Password: ")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.ControlMySpaClient(session, args.email, password)
        try:
            spa_id, spa, current, state = await read(client)
        except api.ControlMySpaError as err:
            print(f"Failed: {type(err).__name__}: {err}")
            return 1

        show(spa, current, state)

        if args.light or args.blower:
            component_type = "LIGHT" if args.light else "BLOWER"
            wanted = args.light or args.blower
            found = state.components_of(component_type)
            if not found:
                print(f"\nNo {component_type} to command.")
                return 1
            component = found[0]
            value = component.on_value if wanted == "on" else "OFF"
            print(
                f"\nSending {component_type} {component.value} -> {value} via "
                f"async_set_component_state(<spa>, {component.command_type!r}, "
                f"{value!r}, {component.device_number!r})"
            )
            send = client.async_set_component_state(
                spa_id, component.command_type, value, component.device_number
            )

            def reached(fresh) -> bool:
                match = fresh.component(component.component_type, component.port)
                print(f"value={match.value if match else None}", end="  ")
                return match is not None and match.value == value

        elif args.heat_mode:
            mode = args.heat_mode.upper()
            print(f"\nSending heater mode {state.heater_mode} -> {mode} via "
                  f"async_set_heater_mode(<spa>, {mode!r})")
            send = client.async_set_heater_mode(spa_id, mode)

            def reached(fresh) -> bool:
                print(f"/web/spas={(fresh.raw.get('currentState') or {}).get('heaterMode')} "
                      f"current-state={fresh.heater_mode}", end="  ")
                return models.settable_heater_mode(fresh.heater_mode) == args.heat_mode

        elif args.temp is not None or args.temp_c is not None:
            celsius = args.temp_c is not None
            asked = args.temp_c if celsius else args.temp

            def shown(value):
                return models.display_temperature(value, state.fahrenheit, celsius)

            low, high = shown(state.min_temp), shown(state.max_temp)
            if low is not None and high is not None and not low <= asked <= high:
                print(f"\n{asked} is outside the {state.temp_range} range "
                      f"({low}-{high}); Home Assistant would refuse it too.")
                return 1
            limits = (state.min_temp, state.max_temp) if state.fahrenheit else (None, None)
            value = models.command_temperature(asked, celsius, *limits)
            print(f"\nSending target {shown(state.target_temp)} -> {asked} via "
                  f"async_set_target_temperature(<spa>, {value!r})")
            send = client.async_set_target_temperature(spa_id, value)

            def reached(fresh) -> bool:
                print(f"/web/spas={(fresh.raw.get('currentState') or {}).get('desiredTemp')} "
                      f"target={fresh.target_temp} shows as {shown(fresh.target_temp)}",
                      end="  ")
                return (
                    fresh.target_temp is not None
                    and abs(fresh.target_temp - value) < 0.01
                )

        elif args.panel_lock:
            command = "LOCK_PANEL" if args.panel_lock == "lock" else "UNLOCK_PANEL"
            print(f"\nSending {command} via async_set_panel_state(<spa>, {command!r})")
            send = client.async_set_panel_state(spa_id, command)

            def reached(fresh) -> bool:
                web_value = (fresh.raw.get("currentState") or {}).get("panelLock")
                print(f"/web/spas panelLock={web_value} reads locked={fresh.panel_lock}",
                      end="  ")
                return fresh.panel_lock == (args.panel_lock == "lock")

        elif args.temp_range:
            wanted = args.temp_range.upper()
            print(f"\nSending range {state.temp_range} -> {wanted} via "
                  f"async_set_temperature_range(<spa>, {wanted!r})")
            send = client.async_set_temperature_range(spa_id, wanted)

            def reached(fresh) -> bool:
                print(f"range={fresh.temp_range} targets {fresh.min_temp}-{fresh.max_temp} "
                      f"target={fresh.target_temp}", end="  ")
                return models.settable_temp_range(fresh.temp_range) == args.temp_range

        elif args.jet:
            number, wanted = args.jet
            try:
                port = int(number) - 1
            except ValueError:
                print(f"\n{number!r} is not a jet number.")
                return 1
            component = state.component("PUMP", port)
            if component is None:
                found = [str((c.port or 0) + 1) for c in state.components_of("PUMP")]
                print(f"\nNo jet {number} (PUMP port {port}). "
                      f"This spa reports jets: {', '.join(found) or 'none'}")
                return 1
            wanted = wanted.upper()
            if wanted == "ON":
                wanted = component.on_value
            if wanted not in component.available_values:
                print(f"\n{wanted} is not one of "
                      f"{', '.join(component.available_values)} for this jet.")
                return 1
            print(f"\nSending jet {number} (PUMP port {port}) {component.value} -> "
                  f"{wanted} via async_set_component_state(<spa>, "
                  f"{component.command_type!r}, {wanted!r}, "
                  f"{component.device_number!r})")
            send = client.async_set_component_state(
                spa_id, component.command_type, wanted, component.device_number
            )

            def reached(fresh) -> bool:
                match = fresh.component("PUMP", port)
                print(f"value={match.value if match else None}", end="  ")
                return match is not None and match.value == wanted

        elif args.time:
            if args.time == "now":
                local = datetime.now()  # noqa: DTZ005 - spa clock is local
                wanted = dtime(local.hour, local.minute)
            else:
                try:
                    hour, _, minute = args.time.partition(":")
                    wanted = dtime(int(hour), int(minute))
                except ValueError:
                    print(f"\n{args.time!r} is not HH:MM or 'now'.")
                    return 1
            if not state.rs485_active:
                print("\nrs485ConnectionActive is False -- the portal would "
                      "disable its Set time dialog. Sending anyway.")
            value = models.command_time(wanted)
            military = True if state.spa_military is None else state.spa_military
            print(f"\nSending clock {state.spa_time} -> {value} via "
                  f"async_set_spa_time(<spa>, {value!r}, {military!r})")
            send = client.async_set_spa_time(spa_id, value, military)

            def reached(fresh) -> bool:
                print(f"hour={fresh.spa_hour} minute={fresh.spa_minute} "
                      f"reads {fresh.spa_time}", end="  ")
                return fresh.spa_time == wanted

        else:
            print("\nRead-only. Pass --light, --blower, --jet, --heat-mode, "
                  "--temp, --panel-lock, --temp-range or --time to send a "
                  "command.")
            return 0

        try:
            await send
        except api.ControlMySpaCommandError as err:
            print(f"-> REFUSED by service: {err}")
            return 1
        except api.ControlMySpaError as err:
            print(f"-> FAILED: {type(err).__name__}: {err}")
            return 1
        print("-> accepted")

        print("\nRe-reading both records, as the coordinator would:")
        elapsed = 0
        for delay in (3, 5, 10, 15, 30):
            await asyncio.sleep(delay)
            elapsed += delay
            try:
                _, _, _, fresh = await read(client, spa_id)
            except api.ControlMySpaError as err:
                print(f"  +{elapsed}s  read failed: {err}")
                continue
            print(f"  +{elapsed}s  ", end="")
            if reached(fresh):
                print("MATCHES COMMAND")
                break
            print("not yet")

        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
