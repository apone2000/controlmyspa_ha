#!/usr/bin/env python3
"""Print the shape of the live spa payload with identifiers removed.

Used to confirm field names and units against a real account without moving
anything account-identifying out of the machine it runs on:

    python scripts/inspect_payload.py --email you@example.com
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

_package = types.ModuleType("controlmyspa_inspect")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_inspect"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_inspect.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_inspect.{name}"] = module
    spec.loader.exec_module(module)
    return module


_load("const")
api = _load("api")

# Anything that identifies the account, the hardware, or its location. Keys are
# matched case-insensitively so variants do not slip through.
REDACT = {
    "_id",
    "activatoremail",
    "address",
    "brokerid",
    "city",
    "dealerid",
    "dealername",
    "email",
    "ipaddress",
    "latitude",
    "longitude",
    "oemid",
    "oemname",
    "owneremail",
    "ownerid",
    "ownername",
    "postalcode",
    "regkey",
    "registrationdate",
    "salesdate",
    "serialnumber",
    "spaid",
    "state",
    "username",
    "zip",
}


def scrub(value, key: str = ""):
    """Recursively replace identifying values while preserving structure."""
    if key.lower() in REDACT:
        return f"<redacted {type(value).__name__}>"
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    return value


async def main() -> int:
    """Fetch the spa and print the scrubbed structure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = os.environ.get("CONTROLMYSPA_PASSWORD") or getpass.getpass("Password: ")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = api.ControlMySpaClient(session, args.email, password)
        try:
            await client.async_login()
            raw = await client.async_get_spa()
        except api.ControlMySpaError as err:
            print(f"Failed: {type(err).__name__}: {err}")
            return 1

    current = raw.get("currentState") or {}

    print("=== top-level keys ===")
    print(sorted(raw.keys()))

    print("\n=== unit / temperature related ===")
    for key in sorted(current):
        if any(
            token in key.lower()
            for token in ("temp", "celsius", "fahrenheit", "unit", "scale", "range")
        ):
            print(f"  {key} = {current[key]!r}")

    print("\n=== setupParams ===")
    print(json.dumps(current.get("setupParams"), indent=2, default=str))

    print("\n=== tzlState ===")
    print(json.dumps(scrub(raw.get("tzlState")), indent=2, default=str))

    print("\n=== c8zCurrentState ===")
    print(json.dumps(scrub(raw.get("c8zCurrentState")), indent=2, default=str))

    print("\n=== all currentState keys ===")
    print(json.dumps(scrub(current), indent=2, default=str, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
