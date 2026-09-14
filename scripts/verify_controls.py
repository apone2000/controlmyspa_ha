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

Without --light, --blower, --heat-mode, --temp or --temp-c nothing is sent.
--temp is in the unit the spa reports; --temp-c is Celsius, converted as a
Celsius Home Assistant would.
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
    if state.fahrenheit:
        def c(value):
            return models.display_temperature(value, True, True)

        print(f"in a Celsius HA: current {c(state.current_temp)} C, target "
              f"{c(state.target_temp)} C, targets {c(state.min_temp)}-{c(state.max_temp)} C")
    print(f"/web/spas desiredTemp     = {(spa.get('currentState') or {}).get('desiredTemp')!r}")
    print(f"current-state desiredTemp = {current.get('desiredTemp')!r}")

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

        else:
            print("\nRead-only. Pass --light, --blower, --heat-mode or --temp "
                  "to send a command.")
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
