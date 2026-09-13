# ControlMySpa for Home Assistant

A Home Assistant custom integration for Balboa **ControlMySpa** hot tubs, built
against the current `/web` cloud API.

It talks to the cloud service directly and creates native Home Assistant
entities. There is no MQTT broker, no add-on, and no external process to run —
it works on every Home Assistant install type (OS, Container, Supervised, Core)
and declares no extra Python dependencies.

> **Status: read-only.** This release publishes spa state into Home Assistant.
> Setting the temperature and controlling the light are not implemented yet —
> see [Write support](#write-support).

## Install

### HACS

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/apone2000/controlmyspa_mqtt_ha` as an **Integration**
3. Install **ControlMySpa**, then restart Home Assistant

### Manual

Copy `custom_components/controlmyspa` into your Home Assistant `config/custom_components/`
directory and restart.

## Set up

**Settings → Devices & Services → Add Integration → ControlMySpa**, then sign in
with the same email and password you use in the ControlMySpa app.

Credentials are stored in Home Assistant's encrypted config entry store. If the
password is ever rejected later, Home Assistant prompts you to re-authenticate
rather than silently going offline.

The polling interval defaults to 30 seconds and can be changed under the
integration's **Configure** option (10–600 seconds). The cloud service is not a
local device — polling every few seconds gains little and loads someone else's
API.

## Entities

All entities hang off a single spa device.

**Sensors** — water temperature, target temperature, ambient temperature, high
limit temperature, heater mode, temperature range, run mode, error code, Wi-Fi
health, last uplink, and the filter / water-change / ClearRay reminder counters.

**Binary sensors** — online, heating, temperature reached, error, eco mode,
soak mode, cleanup cycle, priming mode, and the panel / temperature / settings
/ maintenance locks.

A light entity is created **only** on spas with Tri-Zone Lighting, which report
`primaryTZLStatus` as present. Spas with ordinary lights report
`TZL_NOT_PRESENT`: those lights work, but their state lived in the removed
`components` array and has no replacement in this API. No entity is created
rather than one reporting a confident wrong value — see below.

Less commonly useful entities are created disabled; enable them from the device
page if you want them.

### Temperature units

The payload's `celsius` field describes how the mobile app *displays*
temperatures, not the unit the API sends. It has been observed reading `true`
on a spa reporting `currentTemp: "100.00"` with a configured maximum of `104` —
plainly Fahrenheit. The `alerts` block carries the same contradiction under a
differently misspelled `celcius` key.

The unit is therefore inferred from `setupParams`: every spa tops out near 40C
/ 104F, so a maximum above 50 can only be Fahrenheit. The integration then
declares that as the native unit and lets Home Assistant convert to whatever
your system is set to. If your spa displays 38C, this reports 38C — by way of
100F, honestly labelled.

### Unreported fields

Controllers return `0` for hardware they do not have. Ambient temperature, high
limit temperature, and the four reminder counters are treated as *unknown* when
zero rather than published as real readings, since "0 days until filter clean"
would otherwise read as permanently overdue.

### Availability

Each payload carries a `staleTimestamp`, roughly three minutes after its
uplink — the service stating how long the reading stays good. Past that, plus a
two-minute grace period so a slightly late uplink does not make entities flap,
the spa's entities go **unavailable** rather than continuing to report the last
known reading. A hot tub frozen at a plausible-looking temperature is worse
than one that plainly says it has lost contact.

Payloads without a `staleTimestamp` fall back to a 15-minute uplink age check.

The `Online`, `Stale data`, and `Last uplink` entities deliberately stay
available during an outage — they are how you see what is going on.

## Verifying before you install

`scripts/probe.py` exercises the API on its own, with no Home Assistant
involved. Useful for confirming credentials or seeing what your spa actually
reports:

```bash
python scripts/probe.py --email you@example.com
```

Add `--dump spa.json` to write the full raw record out for inspection. That file
contains account identifiers, so do not commit or share it as-is. No password or
token is ever printed.

## Write support

Commands go to `POST /web/spa-commands`, but **the request body format is not
publicly documented and has not yet been captured**, so no write path is
implemented. Guessing at the payload would produce an integration whose controls
silently do nothing, which is worse than not offering them.

Capturing it is straightforward: open the ControlMySpa web portal with the
browser's network inspector recording, filter to XHR/fetch, clear the log, and
toggle the light once. The single non-`GET` request that appears is the answer —
its path and request body field names are all that is needed.

Once that is known, target temperature and light control can be added, and the
separate temperature sensors replaced by a proper climate entity.

Jets, blowers, pumps, ozone, and ordinary (non-TZL) light state are a larger
unknown: the `components` array the older API exposed is absent from the
current one, and twelve read endpoints were probed without finding a
replacement. `/web/broker` and `/web/gateway-broker` both return `403` rather
than `404` — the routes exist, but an ordinary account token is not permitted.

One promising lead: `gatewayBroker.brokerId` expands to a full broker record
rather than an identifier, naming `iot.controlmyspa.com:8883` (MQTT over TLS)
as the spa's push channel, and `lastMqttMessages` shows the traffic types
flowing over it — `SPA_STATE`, `TZL_STATE`, `FAULT_LOGS`. If those messages
carry full component state, subscribing would restore both live updates and the
missing devices. Topic structure and broker credentials are unknown.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio aiohttp
.venv/bin/python -m pytest
```

The `api` and `models` modules import no Home Assistant code, so they are tested
directly and no test contacts the live service. `tests/conftest.py` loads them
without running the package's Home Assistant imports.

Home Assistant itself requires Python 3.13+; the test suite above does not.

## Credits

The API surface this is built on was mapped by probing the live service after
the previous `/idm/tokenEndpoint` discovery route was removed. Prior art worth
knowing about: [`mikakoivisto/controlmyspa-ha-mqtt`](https://github.com/mikakoivisto/controlmyspa-ha-mqtt)
(JavaScript MQTT bridge) and [`arska/controlmyspa`](https://github.com/arska/controlmyspa)
(Python client) — both written against the older API.
