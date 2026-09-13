#!/usr/bin/env python3
"""Check credentials and dump spa state without involving Home Assistant.

Run this first to confirm the account works and to see what the API actually
returns for your spa:

    python scripts/probe.py --email you@example.com

The password is read from the CONTROLMYSPA_PASSWORD environment variable, or
prompted for. Neither the password nor any token is printed.
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
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "controlmyspa"

# Load the Home-Assistant-free modules directly; the package __init__ imports HA.
_package = types.ModuleType("controlmyspa_probe")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_probe"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_probe.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_probe.{name}"] = module
    spec.loader.exec_module(module)
    return module


_load("const")
api = _load("api")
models = _load("models")


async def main() -> int:
    """Log in, fetch the spa, and print a readable summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="ControlMySpa account email")
    parser.add_argument(
        "--dump",
        metavar="PATH",
        help="write the full raw spa record to a JSON file for inspection",
    )
    args = parser.parse_args()

    password = os.environ.get("CONTROLMYSPA_PASSWORD") or getpass.getpass("Password: ")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.ControlMySpaClient(session, args.email, password)
        try:
            await client.async_login()
            print("Login OK")
            raw = await client.async_get_spa()
        except api.ControlMySpaError as err:
            print(f"Failed: {type(err).__name__}: {err}")
            return 1

    state = models.SpaState.from_api(raw)
    unit = "C" if state.celsius else "F"

    print(f"\nSpa {state.serial_number or state.spa_id}")
    print(f"  online            {state.online}")
    print(f"  available         {state.available} (stale={state.is_stale})")
    print(f"  water temp        {state.current_temp} {unit}")
    print(f"  target temp       {state.target_temp} {unit}")
    print(f"  ambient temp      {state.ambient_temp} {unit}")
    print(f"  range / limits    {state.temp_range} ({state.min_temp}-{state.max_temp})")
    print(f"  heater mode       {state.heater_mode} (heating={state.heating})")
    print(f"  run mode          {state.run_mode}")
    print(f"  error code        {state.error_code}")
    print(f"  wifi health       {state.wifi_health}")
    print(f"  controller        {state.controller_version}")
    print(f"  light             {state.light_on}")
    print(f"  last uplink       {state.uplink_timestamp}")

    if args.dump:
        Path(args.dump).write_text(json.dumps(raw, indent=2, default=str))
        print(f"\nRaw record written to {args.dump}")
        print("It contains account identifiers — do not commit or share it as-is.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
