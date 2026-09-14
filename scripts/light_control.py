#!/usr/bin/env python3
"""Read component state (lights, pumps, blower) and optionally command it.

A low-level diagnostic that talks to the component endpoints directly, without
the integration's own parsing (use verify_controls.py to test that). Component
state lives in GET /web/spas/{id}/current-state, whose `components` array holds
every controllable device with its current value; the main /web/spas payload
carries none of it.

    # poll and report every component change, e.g. from the spa's panel
    python scripts/light_control.py --email you@example.com --watch 15

    # read-only: show what the spa reports
    python scripts/light_control.py --email you@example.com

    # cycle the light exactly as the portal's button does
    python scripts/light_control.py --email you@example.com --toggle

    # or set an explicit state
    python scripts/light_control.py --email you@example.com --set OFF

Without --toggle or --set nothing is sent and no hardware is touched.

Endpoint and payload format were recovered from the portal's own JavaScript
bundle (chunk-V2AH32Z7.js), not guessed.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "controlmyspa"

_package = types.ModuleType("controlmyspa_light")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_light"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_light.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_light.{name}"] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
api = _load("api")

# componentType as it appears in current-state -> the token spa-commands wants.
# Straight from the portal's to() helper; anything absent is not commandable.
API_COMPONENT_TYPE = {
    "PUMP": "jet",
    "CIRCULATION_PUMP": "circ-pump",
    "LIGHT": "light",
    "BLOWER": "blower",
    "MISTER": "mister",
    "MICROSILK": "microsilk",
    "AUX": "aux",
    "OZONE": "ozone",
}

# Types whose command body carries deviceNumber (the component's port).
PORTED = {"PUMP", "LIGHT", "BLOWER", "MISTER", "AUX"}

# Numeric values are decoded per component type -- lights and blowers run a
# four-step scale, pumps a three-step one.
NUMERIC_SCALE = {
    "LIGHT": ["OFF", "LOW", "MED", "HIGH"],
    "BLOWER": ["OFF", "LOW", "MED", "HIGH"],
    "PUMP": ["OFF", "LOW", "HIGH"],
    "CIRCULATION_PUMP": ["OFF", "LOW", "HIGH"],
}
VALUES = ("DISABLED", "HIGH", "LOW", "MED", "OFF", "ON")


# Raw dumps go on screen, so keep account-identifying fields out of them.
REDACT = ("address", "dealer", "email", "latitude", "longitude", "oem", "owner",
          "postal", "regkey", "serial", "spaid", "username", "_id", "zip")


def scrub(value, key: str = ""):
    """Recursively blank account-identifying values, preserving structure."""
    if any(token in key.lower() for token in REDACT):
        return f"<redacted {type(value).__name__}>"
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    return value


def normalise(value, component_type: str) -> str:
    """Decode a raw component value into the OFF/LOW/MED/HIGH/ON vocabulary."""
    if value is None or value == "":
        return "OFF"
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    text = str(value).strip()
    if text.isdigit():
        scale = NUMERIC_SCALE.get(component_type, ["OFF", "ON"])
        index = int(text)
        return scale[index] if index < len(scale) else "OFF"
    upper = text.upper()
    return upper if upper in VALUES else "OFF"


def next_value(current: str, available: list[str], component_type: str) -> str:
    """Return the value the portal's toggle button would send next."""
    choices = [normalise(v, component_type) for v in (available or [])]
    if not choices:
        choices = ["OFF", "ON"]
    try:
        index = choices.index(current)
    except ValueError:
        # ON and HIGH are the same rung under different names.
        alias = "HIGH" if current == "ON" else "ON" if current == "HIGH" else None
        index = choices.index(alias) if alias in choices else -1
    return choices[(index + 1) % len(choices)] if index >= 0 else choices[0]


def wire_state(value: str, api_type: str) -> str:
    """Apply the portal's io() fixups before the value goes on the wire."""
    if not value or value == "DISABLED":
        return "OFF"
    if api_type == "jet" and value == "ON":
        return "HIGH"
    return value


async def main() -> int:
    """Show component state, and command one component when asked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--component", default="LIGHT", help="componentType to act on")
    parser.add_argument("--port", type=int, help="disambiguate multiple components")
    parser.add_argument("--raw", action="store_true", help="dump raw component JSON")
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECONDS",
        help="re-poll every SECONDS and report changes (Ctrl-C to stop)",
    )
    parser.add_argument("--mqtt", action="store_true", help="show recent uplinks")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--toggle", action="store_true", help="advance one step")
    group.add_argument("--set", dest="state", choices=VALUES, help="set exactly")
    args = parser.parse_args()

    password = os.environ.get("CONTROLMYSPA_PASSWORD") or getpass.getpass("Password: ")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.ControlMySpaClient(session, args.email, password)
        try:
            await client.async_login()
            spa = await client.async_get_spa()
        except api.ControlMySpaError as err:
            print(f"Failed: {type(err).__name__}: {err}")
            return 1

        spa_id = spa.get("_id") or ""
        if not spa_id:
            print("No spa id in payload.")
            return 1

        async def get(url: str):
            await client.async_ensure_token()
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {client.access_token}"},
                timeout=aiohttp.ClientTimeout(total=const.REQUEST_TIMEOUT),
            ) as response:
                body = await response.json(content_type=None)
                return response.status, body

        url = f"{const.ENDPOINT_SPAS}/{spa_id}/current-state"
        status, body = await get(url)
        print(f"GET /spas/{{id}}/current-state -> {status}")
        if status != 200:
            print(json.dumps(body, indent=2)[:800])
            return 1

        state = body.get("data", body) if isinstance(body, dict) else {}
        components = state.get("components") or []
        print(f"online={state.get('online')} panelLock={state.get('panelLock')} "
              f"components={len(components)}\n")

        if not components:
            print("No components array. Keys present:", sorted(state))
            return 1

        print(f"{'componentType':<20} {'port':<5} {'value':<10} {'available':<28} registered")
        for item in components:
            ctype = item.get("componentType") or "?"
            value = normalise(item.get("value"), ctype)
            avail = ",".join(
                normalise(v, ctype) for v in (item.get("availableValues") or [])
            )
            print(
                f"{ctype:<20} {str(item.get('port')):<5} {value:<10} "
                f"{avail:<28} {bool(item.get('registeredTimestamp'))}"
            )

        # How old is this picture? Component values only move when the spa
        # uplinks, so a stale uplink explains a value that disagrees with the
        # hardware in front of you.
        print()
        for label in ("uplinkTimestamp", "staleTimestamp", "lastUpdated", "updatedAt"):
            if state.get(label) is not None:
                print(f"{label} = {state[label]}")
        print(f"local time now  = {datetime.now(timezone.utc).isoformat()}")

        if args.raw:
            print("\n=== raw components ===")
            print(json.dumps(scrub(components), indent=2, default=str))
            print("\n=== other current-state keys ===")
            print(sorted(k for k in state if k != "components"))

        if args.mqtt:
            status, body = await get(
                f"{const.ENDPOINT_SPAS}/{spa_id}/mqtt-messages?page=0&pageSize=5"
            )
            print(f"\n=== /mqtt-messages -> {status} ===")
            print(json.dumps(scrub(body), indent=2, default=str)[:4000])

        if args.watch:
            print(f"\nPolling every {args.watch}s. Change the light at the spa "
                  f"panel and watch for movement. Ctrl-C to stop.")
            previous = None
            while True:
                await asyncio.sleep(args.watch)
                status, body = await get(url)
                if status != 200:
                    print(f"  {status}")
                    continue
                fresh = (body.get("data", body) or {}).get("components") or []
                snapshot = {
                    f"{c.get('componentType')}:{c.get('port')}": normalise(
                        c.get("value"), c.get("componentType") or ""
                    )
                    for c in fresh
                }
                stamp = datetime.now().strftime("%H:%M:%S")
                if previous is None:
                    print(f"  {stamp} baseline {snapshot}")
                elif snapshot != previous:
                    changed = {
                        k: f"{previous.get(k)}->{v}"
                        for k, v in snapshot.items()
                        if previous.get(k) != v
                    }
                    print(f"  {stamp} CHANGED {changed}")
                else:
                    upl = (body.get("data", body) or {}).get("uplinkTimestamp")
                    print(f"  {stamp} no change (uplink {upl})")
                previous = snapshot

        if not (args.toggle or args.state):
            print("\nRead-only. Pass --toggle or --set to send a command.")
            return 0

        target_type = args.component.upper()
        matches = [
            c
            for c in components
            if (c.get("componentType") or "").upper() == target_type
            and (args.port is None or int(c.get("port") or 0) == args.port)
        ]
        if not matches:
            print(f"\nNo {target_type} component found.")
            return 1
        if len(matches) > 1:
            ports = [c.get("port") for c in matches]
            print(f"\nSeveral {target_type} components (ports {ports}); pass --port.")
            return 1

        component = matches[0]
        api_type = API_COMPONENT_TYPE.get(target_type)
        if not api_type:
            print(f"\n{target_type} is not commandable.")
            return 1

        current = normalise(component.get("value"), target_type)
        chosen = args.state or next_value(
            current, component.get("availableValues") or [], target_type
        )
        payload = {
            "spaId": spa_id,
            "via": "WEB",
            "componentType": api_type,
            "state": wire_state(chosen, api_type),
        }
        if target_type in PORTED:
            payload["deviceNumber"] = int(component.get("port") or 0)

        print(f"\n{current} -> {payload['state']}")
        # Echo the body with the account identifier masked, matching the other
        # scripts here -- the shape is the interesting part, not the spa id.
        print(
            "POST /spa-commands/component-state "
            f"{json.dumps({**payload, 'spaId': '<redacted>'})}"
        )

        await client.async_ensure_token()
        async with session.post(
            f"{const.API_ROOT}/spa-commands/component-state",
            json=payload,
            headers={"Authorization": f"Bearer {client.access_token}"},
            timeout=aiohttp.ClientTimeout(total=const.REQUEST_TIMEOUT),
        ) as response:
            result = await response.json(content_type=None)
            print(f"-> {response.status} {json.dumps(result)[:400]}")
            if response.status >= 300:
                return 1

        # Does the reported value follow the command, and how fast? This is the
        # question that decides whether a HA entity can mirror the spa or has to
        # assume its own state.
        print("\nRe-reading to see whether the reported value catches up:")
        key = f"{target_type}:{component.get('port')}"
        elapsed = 0
        for delay in (3, 5, 10, 15, 30):
            await asyncio.sleep(delay)
            elapsed += delay
            status, body = await get(url)
            if status != 200:
                print(f"  +{elapsed}s  read failed {status}")
                continue
            fresh = (body.get("data", body) or {}).get("components") or []
            match = next(
                (
                    c
                    for c in fresh
                    if (c.get("componentType") or "").upper() == target_type
                    and str(c.get("port")) == str(component.get("port"))
                ),
                None,
            )
            now = normalise(match.get("value") if match else None, target_type)
            flag = "MATCHES COMMAND" if now == payload["state"] else "still " + now
            print(f"  +{elapsed}s  {key} = {now:<6} {flag}")
            if now == payload["state"]:
                break

        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
