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

## Requirements

- Home Assistant 2025.2 or newer
- A ControlMySpa account (the same one the mobile app uses)
- Internet access from Home Assistant — this is a cloud API, not a local one

No Python dependencies. The integration uses only what Home Assistant already
ships, so there is nothing to install and nothing to conflict.

## Install

### Via HACS

1. **HACS → ⋮ (top right) → Custom repositories**
2. Paste `https://github.com/apone2000/controlmyspa_mqtt_ha`, type **Integration**, **Add**
3. Find **ControlMySpa** in the HACS list and click **Download**
4. **Restart Home Assistant** (Settings → System → Restart)

### Manually

Copy the `custom_components/controlmyspa` folder — the folder itself, not its
contents — into your Home Assistant configuration directory, so that you end up
with exactly this:

```
config/
└── custom_components/
    └── controlmyspa/
        ├── manifest.json
        ├── __init__.py
        ├── api.py
        └── ...
```

Create `custom_components` first if it does not exist. Check that
`config/custom_components/controlmyspa/manifest.json` is present before going
further: a nested `controlmyspa/controlmyspa/`, or the files sitting loose in
`custom_components/`, are the two usual slips and both fail silently.

On Home Assistant OS the configuration directory is not on the machine you are
copying from, so you need one of the **Samba share**, **Advanced SSH & Web
Terminal**, or **File editor** add-ons to reach it. With Samba mounted, it is a
drag; with SSH it is one command:

```bash
scp -r custom_components/controlmyspa root@<your-ha-ip>:/config/custom_components/
```

Then **restart Home Assistant**.

> **A restart is required, not a reload.** Home Assistant imports custom
> integrations at startup, so a folder that was not there when it booted is
> invisible to it. This applies to *updates* as well: after copying changed
> files, the integration's Reload button re-runs setup against the module
> Python still has cached in memory, so your changes appear to do nothing.
> Always restart.

## Set up

**Settings → Devices & Services → Add Integration → ControlMySpa**, then sign in
with the same email and password you use in the ControlMySpa app.

Credentials are verified before the entry is created, so a wrong password fails
immediately with a clear message rather than producing a broken device. They are
stored in Home Assistant's encrypted config entry store, and if the password is
ever rejected later Home Assistant prompts you to re-authenticate rather than
silently going offline.

The polling interval defaults to 30 seconds and can be changed via **Configure**
on the integration (10–600 seconds). The cloud service is not a local device —
polling every few seconds gains little and loads someone else's API.

### Checking it worked

You should get one device named **Spa**, showing your controller type as the
model and its firmware version. Water temperature should match what the spa's
own panel shows. If your panel reads in Celsius and this reads the same, the
unit handling is working — see [Temperature units](#temperature-units) for why
that is worth checking.

### If it does not appear

- **Not in the Add Integration list** — the restart did not pick it up. Confirm
  `config/custom_components/controlmyspa/manifest.json` exists, then check
  **Settings → System → Logs** for `controlmyspa`; an import error shows there.
  A hard refresh of the browser also helps, as the integration list is cached.
- **All entities Unavailable** — the spa is reporting itself offline. Check the
  **Online** and **Last uplink** diagnostic entities, which stay available
  during an outage precisely so you can see this.
- **Setup fails with "cannot connect"** — Home Assistant cannot reach
  `iot.controlmyspa.com`. Check its DNS and internet access.

For anything else, `scripts/probe.py` exercises the API directly from any
machine with Python and prints what the service actually returns — usually
faster than reading Home Assistant logs. See
[Verifying before you install](#verifying-before-you-install).

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

Availability follows the spa's own `online` flag, which the service maintains
from the gateway connection, plus a one-hour backstop on the last uplink for a
spa that claims to be online after going quiet.

Each payload also carries a `staleTimestamp` about three minutes after its
uplink. That is *not* used for availability: spas uplink far less often than
every three minutes, so a reading past its stated expiry is routine rather than
a fault. It drives the optional **Stale data** diagnostic sensor instead, for
anyone who wants to see or automate on reading freshness.

The `Online`, `Stale data`, and `Last uplink` entities deliberately stay
available during an outage — they are how you see what is going on.

## Verifying before you install

`scripts/probe.py` exercises the API on its own, with no Home Assistant
involved. Useful for confirming credentials or seeing what your spa actually
reports:

```bash
python scripts/probe.py --email you@example.com
```

Add `--dump spa.json` to write the full raw record out for inspection. **That
file contains account identifiers** -- serial number, owner email, dealer
details, `regKey` and IP address -- so it is gitignored and must not be shared
as-is. Use `scripts/inspect_payload.py` instead when you want to show someone
the payload shape: it strips identifying fields first. No password or token is
ever printed by either script.

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

## Branches and releases

HACS installs from GitHub **releases**, not from branches. If a repository has
no releases it falls back to the default branch, which is why the branch layout
and the release process do separate jobs:

| Branch | Role |
|---|---|
| `main` | Stable. Tagged and released from here. |
| `develop` | Work in progress. Never installed directly by anyone. |

Cutting a release:

1. Merge `develop` into `main`
2. Bump `"version"` in `custom_components/controlmyspa/manifest.json`
3. Tag it to match, e.g. `git tag -a v0.2.0 -m "..."` and push the tag
4. Create a GitHub release from that tag

**The manifest version and the tag must match.** HACS compares them, and a
mismatch makes updates behave unpredictably.

For a beta, tag a pre-release version (`v0.2.0-beta.1`) and tick
**"This is a pre-release"** when creating the GitHub release. Only users who
have enabled **Show beta versions** on this repository in HACS will be offered
it; everyone else stays on the latest stable release.

## License

MIT -- see [LICENSE](LICENSE). Use it, change it, ship it; just keep the
copyright notice.

Not affiliated with or endorsed by Balboa Water Group. "ControlMySpa" is their
trademark, used here only to say what this talks to. The API surface was mapped
by observing the service with an ordinary account, for interoperability with
hardware the account owner already owns.
