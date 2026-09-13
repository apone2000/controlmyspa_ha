#!/usr/bin/env python3
"""Hunt for light state that the main spa endpoint does not expose.

Ordinary (non-TZL) light state lived in the removed components array. This
searches the full payload for anything light-shaped and probes the other known
read endpoints to see whether any of them carry it:

    python scripts/find_lights.py --email you@example.com

Every request is a GET. Nothing is changed on the account.
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

_package = types.ModuleType("controlmyspa_find")
_package.__path__ = [str(SOURCE)]
sys.modules["controlmyspa_find"] = _package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"controlmyspa_find.{name}", SOURCE / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"controlmyspa_find.{name}"] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
api = _load("api")

# Substring matching this time: the previous exact-match list let prefixed
# variants such as spaSerialNumber through.
REDACT_SUBSTRINGS = (
    "address",
    "dealer",
    "email",
    "latitude",
    "longitude",
    "oem",
    "owner",
    "postal",
    "regkey",
    "serial",
    "spaid",
    "username",
    "_id",
    "zip",
)

# Keys worth surfacing when hunting for light state.
LIGHT_TOKENS = ("light", "lamp", "led", "rgb", "colour", "color", "zone", "bright")


def is_sensitive(key: str) -> bool:
    """Return True when a key name looks account-identifying."""
    lowered = key.lower()
    return any(token in lowered for token in REDACT_SUBSTRINGS)


def scrub(value, key: str = ""):
    """Recursively replace identifying values while preserving structure."""
    if is_sensitive(key):
        return f"<redacted {type(value).__name__}>"
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, key) for v in value]
    return value


def walk(value, path: str = ""):
    """Yield every (path, key, value) leaf in a nested structure."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            yield child_path, key, child
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from walk(child, child_path)


async def main() -> int:
    """Search the spa payload and probe other endpoints for light state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
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
        broker = (spa.get("gatewayBroker") or {}).get("brokerId")
        # brokerId expands to a full broker record rather than an identifier.
        broker_id = broker.get("_id", "") if isinstance(broker, dict) else (broker or "")
        if isinstance(broker, dict):
            print("=== gateway broker (MQTT push channel) ===")
            print(
                f"  {broker.get('name')} {broker.get('domain')}:{broker.get('port')} "
                f"primary={broker.get('primary')} disabled={broker.get('disabled')}\n"
            )

        print("=== anything light-shaped anywhere in the spa payload ===")
        found = False
        for path, key, value in walk(spa):
            if any(token in key.lower() for token in LIGHT_TOKENS):
                if isinstance(value, (dict, list)):
                    continue
                print(f"  {path} = {value!r}")
                found = True
        if not found:
            print("  (nothing)")

        print("\n=== lastMqttMessages ===")
        print(
            json.dumps(scrub(spa.get("lastMqttMessages")), indent=2, default=str)[:4000]
        )

        print("\n=== alerts ===")
        print(json.dumps(scrub(spa.get("alerts")), indent=2, default=str)[:2000])

        print("\n=== other read endpoints ===")
        candidates = [
            f"{const.API_ROOT}/spas/{spa_id}",
            f"{const.API_ROOT}/spas/{spa_id}/components",
            f"{const.API_ROOT}/spas/{spa_id}/devices",
            f"{const.API_ROOT}/dashboard",
            f"{const.API_ROOT}/broker",
            f"{const.API_ROOT}/gateway-broker",
            f"{const.API_ROOT}/gateway-broker/{broker_id}" if broker_id else "",
            f"{const.API_ROOT}/catalog",
            f"{const.API_ROOT}/events?spaId={spa_id}",
            f"{const.API_ROOT}/spa-schedules",
            f"{const.API_ROOT}/auth/profile",
            f"{const.API_ROOT}/health",
        ]

        for url in [c for c in candidates if c]:
            await client.async_ensure_token()
            label = url.replace(const.API_ROOT, "")
            try:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {client.access_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    status = response.status
                    try:
                        body = await response.json()
                    except (aiohttp.ContentTypeError, ValueError):
                        body = None
            except (TimeoutError, aiohttp.ClientError) as err:
                print(f"  {status_label(label)} FAILED {type(err).__name__}")
                continue

            if status != 200:
                print(f"  {status_label(label)} {status}")
                continue

            payload = body.get("data", body) if isinstance(body, dict) else body
            keys = (
                sorted(payload) if isinstance(payload, dict) else type(payload).__name__
            )
            print(f"  {status_label(label)} 200  keys={keys}")

            hits = [
                f"{path}={value!r}"
                for path, key, value in walk(payload)
                if any(token in key.lower() for token in LIGHT_TOKENS)
                and not isinstance(value, (dict, list))
            ]
            for hit in hits[:15]:
                print(f"        LIGHT? {hit}")

    return 0


def status_label(label: str) -> str:
    """Pad an endpoint label so the status column lines up."""
    return f"{label:<34}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
