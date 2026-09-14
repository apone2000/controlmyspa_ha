# ControlMySpa for Home Assistant

A Home Assistant custom integration for Balboa **ControlMySpa** hot tubs, built
against the current `/web` cloud API.

It talks to the cloud service directly and creates native Home Assistant
entities. There is no MQTT broker, no add-on, and no external process to run —
it works on every Home Assistant install type (OS, Container, Supervised, Core)
and declares no extra Python dependencies.

> **Status: early control.** Spa state is published into Home Assistant, and the
> target temperature, light, blower and heat mode can be controlled. Jets and
> temperature range are not implemented yet — see [Write support](#write-support).

## Requirements

- Home Assistant 2025.2 or newer
- A ControlMySpa account (the same one the mobile app uses)
- Internet access from Home Assistant — this is a cloud API, not a local one

No Python dependencies. The integration uses only what Home Assistant already
ships, so there is nothing to install and nothing to conflict.

## Install

### Via HACS

1. **HACS → ⋮ (top right) → Custom repositories**
2. Paste `https://github.com/apone2000/controlmyspa_ha`, type **Integration**, **Add**
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

**Controls** — a thermostat, light (on/off), blower (on/off switch), and heat
mode (Ready / Rest).

The thermostat (`climate.spa`) shows the water temperature and sets the
target, within the limits of the active temperature range (High or Low). It
has no off mode — the heater cannot be switched off through the API, only moved
to Rest. Ready and Rest are its presets, so the thermostat row reads e.g.
"Idle (Heat - Rest)" and the thermostat card can switch between them.

The API works in Fahrenheit. In a Celsius Home Assistant the thermostat and
temperature sensors show values the way the portal and the spa's panel do —
converted and rounded to the nearest half degree, so 100 °F reads 37.5 °C
rather than an exact 37.8 — and the target steps in half degrees.

The spa only keeps whole degrees Fahrenheit: a half degree is accepted but
rounded away. A Celsius target is therefore sent as the nearest whole °F, so
every value the spa can display sets exactly. A few half steps have no
whole-°F equivalent — 38.0 °C falls between 100 °F (37.5) and 101 °F (38.5) —
and settle on a neighbour, just as they do in the portal.

The light and blower are created from the devices the spa itself
reports, so a spa without a blower gets no blower switch, and a spa with
several lights gets them numbered. Both switch on at their strongest setting.

The **Heater mode** sensor reports Ready, Rest, or Ready-in-Rest. Ready-in-Rest
means the spa is in Rest mode but the jets have been used, so it heats for an
hour and then returns to Rest by itself. It cannot be chosen, so the **Heat
mode** control shows Rest meanwhile.

A command's effect shows immediately and is re-read five seconds later to
confirm it. If ControlMySpa refuses a command, Home Assistant shows the
service's own message and the state is left as it was.

Spas with Tri-Zone Lighting also get a **Light** binary sensor from their TZL
status.

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

`scripts/verify_controls.py` runs the integration's own client and parsing
against your spa and prints what the light, blower and heat mode entities would
show. It is read-only unless given `--light`, `--blower`, `--heat-mode` or `--temp`, which
send that one command and re-read until the spa reports it:

```bash
python scripts/verify_controls.py --email you@example.com
python scripts/verify_controls.py --email you@example.com --blower on
```

## Write support

Command formats were recovered from the ControlMySpa web portal's own
JavaScript rather than guessed, and the temperature, light, blower and heat
mode commands were all verified against a real spa:

```json
POST /web/spa-commands/component-state
{"spaId": "...", "via": "WEB", "componentType": "light", "state": "HIGH", "deviceNumber": 0}

POST /web/spa-commands/temperature/heater-mode
{"spaId": "...", "via": "WEB", "mode": "REST"}

POST /web/spa-commands/temperature/value
{"spaId": "...", "via": "WEB", "value": 101}
```

The temperature `value` is always Fahrenheit, even for spas displayed in
Celsius: the portal converts before sending and rounds to the nearest half
degree.

Device state comes from `GET /web/spas/{id}/current-state`, whose `components`
array lists every controllable device — lights, pumps, blower, circulation
pump, filters — with its current value and the values it accepts. It reflected
an accepted command within three seconds when tested.

Not implemented yet: switching the temperature range, and jets. Their payloads
are known (`temperature/range` with `{spaId, via, range}` as `HIGH` or `LOW`,
and `component-state` with `jet`) but untested.

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
