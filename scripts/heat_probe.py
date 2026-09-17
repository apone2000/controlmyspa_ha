#!/usr/bin/env python3
"""Find which payload field actually tracks the spa's heater.

binary_sensor.spa_heating reads currentState.heaterCooling, which was never
confirmed against the hardware -- and an overnight heat-up left no trace in
Home Assistant, so it probably is not the right field.

This polls both records and reports every numeric or boolean field that
CHANGES between polls, so whatever moves when the heater starts names itself.
Run it across the moment heating begins: either switch the spa to Ready, or
leave it running over the filter cycle that heats overnight.

    python scripts/heat_probe.py --email you@example.com --watch 30

Only booleans, numbers and a short allowlist of enum-like strings are printed,
so nothing account-identifying is shown.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "controlmyspa"

_package = types.ModuleType("controlmyspa_heat")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_heat"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_heat.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_heat.{name}"] = module
    spec.loader.exec_module(module)
    return module


_load("const")
api = _load("api")

# Enum-like strings worth watching. Everything else non-numeric is skipped so
# serials, emails, addresses and keys can never be printed.
SAFE_STRINGS = {
    "heaterMode", "tempRange", "runMode", "wifiConnectionHealth",
    "controllerType", "value", "componentType", "primaryTZLStatus",
}
# Values that move on their own every poll and would drown the real signal.
NOISE = {"uplinkTimestamp", "staleTimestamp", "lastUpdateTimestamp", "timestamp"}


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """Return {path: value} for every scalar worth watching."""
    found: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in NOISE:
                continue
            found.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(flatten(value, f"{prefix}[{index}]"))
    else:
        leaf = prefix.rsplit(".", 1)[-1].split("[")[0]
        if isinstance(node, (bool, int, float)):
            found[prefix] = node
        elif isinstance(node, str) and leaf in SAFE_STRINGS:
            found[prefix] = node
    return found


async def sample(client) -> dict[str, Any]:
    """Fetch both records and flatten them together."""
    spa = await client.async_get_spa()
    spa_id = str(spa.get("_id") or "")
    current = await client.async_get_current_state(spa_id)
    combined = flatten(spa.get("currentState") or {}, "spas")
    combined.update(flatten(current, "current-state"))
    return combined


async def main() -> int:
    """Poll and report what changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--watch", type=int, default=30, metavar="SECONDS",
                        help="seconds between polls (default 30)")
    parser.add_argument("--grep", default="",
                        help="only show fields whose name contains this")
    args = parser.parse_args()

    password = os.environ.get("CONTROLMYSPA_PASSWORD") or getpass.getpass("Password: ")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.ControlMySpaClient(session, args.email, password)
        try:
            previous = await sample(client)
        except api.ControlMySpaError as err:
            print(f"Failed: {type(err).__name__}: {err}")
            return 1

        interesting = [k for k in sorted(previous) if args.grep.lower() in k.lower()]
        stamp = datetime.now().strftime("%H:%M:%S")  # noqa: DTZ005 - local clock
        print(f"[{stamp}] baseline, {len(previous)} fields watched")
        for key in interesting:
            if any(w in key.lower() for w in ("heat", "temp", "pump", "filter", "circ")):
                print(f"    {key} = {previous[key]!r}")
        print(f"\nPolling every {args.watch}s. Ctrl-C to stop.\n")

        while True:
            await asyncio.sleep(args.watch)
            try:
                current = await sample(client)
            except api.ControlMySpaError as err:
                print(f"  read failed: {err}")
                continue

            stamp = datetime.now().strftime("%H:%M:%S")  # noqa: DTZ005
            changes = [
                (key, previous.get(key), value)
                for key, value in sorted(current.items())
                if previous.get(key) != value and args.grep.lower() in key.lower()
            ]
            gone = [k for k in previous if k not in current]
            if not changes and not gone:
                print(f"[{stamp}] no change")
            for key, was, now in changes:
                print(f"[{stamp}] {key}: {was!r} -> {now!r}")
            for key in gone:
                print(f"[{stamp}] {key}: disappeared")
            previous = current


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nstopped")
