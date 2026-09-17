# ControlMySpa for Home Assistant

A Home Assistant custom integration for Balboa **ControlMySpa** hot tubs, built
against the current `/web` cloud API.

It talks to the cloud service directly and creates native Home Assistant
entities. There is no MQTT broker, no add-on, and no external process to run —
it works on every Home Assistant install type (OS, Container, Supervised, Core)
and declares no extra Python dependencies.

> **Status: early control.** Spa state is published into Home Assistant, and the
> target temperature, temperature range, heat mode, light, blower and panel lock
> can be controlled. Jets, the spa clock and filter cycles are not implemented
> yet — see [Roadmap](#roadmap).

## Requirements

- Home Assistant 2025.2 or newer (2026.3 or newer to show the integration's
  icon)
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

### Updating

In HACS, open **ControlMySpa** and choose **Update** (if none is offered yet,
use **⋮ → Update information** first), then restart Home Assistant.

Read the [Changelog](#changelog) before updating. When a release replaces an
entity, the old one is left behind as *no longer provided*: point any
automations, scripts or dashboards at the new entity, then delete the old one
from the device page.

## Set up

**Settings → Devices & Services → Add Integration → ControlMySpa**, then sign in
with the same email and password you use in the ControlMySpa app.

Credentials are verified before the entry is created, so a wrong password fails
immediately with a clear message rather than producing a broken device. They are
stored in the integration's config entry, like any other integration's, and if
the password is ever rejected later Home Assistant prompts you to
re-authenticate rather than silently going offline. See [SECURITY.md](SECURITY.md)
for how credentials and tokens are handled, and how to report a vulnerability.

The polling interval defaults to **5 minutes** and can be changed via
**Configure** on the integration (10–600 seconds); a change applies as soon as
it is saved. If the interval has ever been saved there, that value is kept and
the default does not apply.

The spa itself only reports to the cloud every 2–3 minutes, so faster polling
mostly re-reads the same data and loads someone else's API. Changes made at the
spa's panel or in the app reach Home Assistant at the next poll. Commands sent
*from* Home Assistant show immediately whatever the interval, and are confirmed
by a re-read five seconds later.

### Checking it worked

You should get one device named **Spa**, showing your controller type as the
model and its firmware version, and a thermostat named **Spa** on it. Water
temperature should match what the spa's own panel shows. If your panel reads in
Celsius and this reads the same, the unit handling is working — see
[Temperature units](#temperature-units) for why that is worth checking.

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

All entities hang off a single device named **Spa**; the IDs below are the ones
Home Assistant gives them. *Diagnostic* entities are listed under Diagnostic on
the device page rather than with the controls and sensors. Entities marked
*disabled* are created disabled; enable them from the device page if you want
them.

**Controls**

| Entity | ID | Notes |
|---|---|---|
| Thermostat | `climate.spa` | Water temperature, target, Ready / Rest presets |
| Heat mode | `select.spa_heat_mode` | Ready / Rest |
| Ready mode | `switch.spa_ready_mode` | On for Ready, off for Rest |
| Temperature range | `select.spa_temperature_range` | High / Low |
| Light | `light.spa_light` | On / off; only if the spa reports a light |
| Blower | `switch.spa_blower` | On / off; only if the spa reports a blower |
| Panel lock | `lock.spa_panel_lock` | Locks the spa's own buttons |
| Time | `time.spa_time` | The spa's own clock, which schedules filtering |
| Sync time | `button.spa_sync_time` | Sets the clock from Home Assistant |
| Refresh | `button.spa_refresh` | Re-reads the spa now |

**Sensors**

| Entity | ID | Notes |
|---|---|---|
| Water temperature | `sensor.spa_water_temperature` | Last good reading held; the one to graph |
| Water temperature (raw) | `sensor.spa_water_temperature_raw` | Diagnostic; exactly as the API sends it |
| Target temperature | `sensor.spa_target_temperature` | |
| Heater mode | `sensor.spa_heater_mode` | Ready, Rest or Ready-in-Rest |
| Run mode | `sensor.spa_run_mode` | |
| Ambient temperature | `sensor.spa_ambient_temperature` | Diagnostic |
| High limit temperature | `sensor.spa_high_limit_temperature` | Diagnostic, disabled |
| Error code | `sensor.spa_error_code` | Diagnostic |
| Wi-Fi health | `sensor.spa_wi_fi_health` | Diagnostic |
| Last uplink | `sensor.spa_last_uplink` | Diagnostic; stays available during an outage |
| Filter 1 reminder | `sensor.spa_filter_1_reminder` | Diagnostic, days |
| Filter 2 reminder | `sensor.spa_filter_2_reminder` | Diagnostic, days, disabled |
| Water change reminder | `sensor.spa_water_change_reminder` | Diagnostic, days |
| ClearRay reminder | `sensor.spa_clearray_reminder` | Diagnostic, days, disabled |
| Filter 1 start time | `sensor.spa_filter_1_start_time` | Diagnostic; `HH:MM` |
| Filter 1 duration | `sensor.spa_filter_1_duration` | Diagnostic, minutes |
| Filter 2 start time | `sensor.spa_filter_2_start_time` | Diagnostic; `HH:MM` |
| Filter 2 duration | `sensor.spa_filter_2_duration` | Diagnostic, minutes |

**Binary sensors**

| Entity | ID | Notes |
|---|---|---|
| Heating | `binary_sensor.spa_heating` | On while the heater is running |
| Temperature reached | `binary_sensor.spa_temperature_reached` | |
| Eco mode | `binary_sensor.spa_eco_mode` | |
| Soak mode | `binary_sensor.spa_soak_mode` | |
| Cleanup cycle | `binary_sensor.spa_cleanup_cycle` | |
| Light | `binary_sensor.spa_light` | Tri-Zone Lighting spas only, from their TZL status |
| Online | `binary_sensor.spa_online` | Diagnostic; stays available during an outage |
| Stale data | `binary_sensor.spa_stale_data` | Diagnostic, disabled; stays available during an outage |
| Water temperature held | `binary_sensor.spa_water_temperature_held` | Diagnostic |
| Error | `binary_sensor.spa_error` | Diagnostic |
| Priming mode | `binary_sensor.spa_priming_mode` | Diagnostic, disabled |
| Temperature lock | `binary_sensor.spa_temperature_lock` | Diagnostic |
| Settings lock | `binary_sensor.spa_settings_lock` | Diagnostic, disabled |
| Maintenance lock | `binary_sensor.spa_maintenance_lock` | Diagnostic, disabled |

A spa with several lights or blowers gets them numbered, e.g. `light.spa_light_1`.

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

**Ready mode** is the same choice as a one-tap switch: on for Ready, off for
Rest. It reads off during Ready-in-Rest, which is Rest mode.

**Panel lock** (`lock.spa_panel_lock`) locks the spa's own control panel, so its
buttons do nothing until it is unlocked again.

**Temperature range** (`select.spa_temperature_range`) switches between High and
Low. Each range has its own limits from the spa's setup, such as 80–104 °F and
50–99 °F, and the thermostat's minimum and maximum follow the choice. Each
range also keeps its own target: the new limits show straight away, and the
thermostat picks up that range's target when it re-reads a few seconds later.

A command's effect shows immediately and is re-read five seconds later to
confirm it. If ControlMySpa refuses a command, Home Assistant shows the
service's own message and the state is left as it was.

**Refresh** re-reads the spa from ControlMySpa straight away instead of waiting
for the next poll. It can only fetch what the cloud already has: the spa itself
reports every two to three minutes, so pressing it more often than that mostly
returns the same data. If the read fails, Home Assistant shows why.

**Time** (`time.spa_time`) is the clock the spa keeps for itself, and it is what
decides when the filter cycles run — so a spa an hour out filters an hour late.
Setting it does not change whether the spa displays 12- or 24-hour time; that
setting is sent back unchanged.

**Sync time** (`button.spa_sync_time`) sets the clock from Home Assistant's own
local time. The spa keeps no seconds and no date, so its clock drifts and a
daylight saving change leaves it an hour out until it is set again. An
automation pressing this daily keeps it right:

```yaml
automation:
  - alias: Keep the spa clock right
    triggers:
      - trigger: time
        at: "03:30:00"
    actions:
      - action: button.press
        target:
          entity_id: button.spa_sync_time
```

Both are unavailable while the spa reports that its controller link (RS485) is
down, because the controller is what keeps the time — the ControlMySpa portal
disables its own dialog for the same reason.

**Filter cycles** are reported as one pair of sensors per cycle the spa has:
when it starts, and how many minutes it runs for. They are **read-only on
purpose.** ControlMySpa accepts a schedule change and then either ignores it or
applies a different one — saving in the ControlMySpa portal itself resets the
times — so a control here would claim to have done something it had not.

Each sensor carries a `status` attribute holding the cycle's own state: `ON`
means the cycle is **enabled**, not that it is filtering at this moment, and
`DISABLED` means it is switched off, so its start and duration are inert. The
spa reports no field for "filtering right now" — that can only be worked out
from the start and duration against **Time** (`time.spa_time`), the clock the
spa schedules from.

### Temperature units

The payload's `celsius` field describes how the mobile app *displays*
temperatures, not the unit the API sends. It has been observed reading `true`
on a spa reporting `currentTemp: "100.00"` with a configured maximum of `104` —
plainly Fahrenheit. The `alerts` block carries the same contradiction under a
differently misspelled `celcius` key.

The unit is therefore inferred from `setupParams`: every spa tops out near 40C
/ 104F, so a maximum above 50 can only be Fahrenheit.

Displayed temperatures follow Home Assistant's own unit system (Settings →
System → General). A Fahrenheit install shows the spa's whole degrees as they
are. A Celsius install gets Celsius directly from the integration, rounded the
way the portal and the spa's panel round it rather than converted exactly — see
[Entities](#entities). There is deliberately no separate °C/°F option: Home
Assistant converts climate and sensor temperatures to its unit system whatever
an integration reports, so such an option could not change what you see. The
one exception is **Water temperature (raw)**, which deliberately has no
temperature device class and so stays in the spa's own unit.

### Unreported fields

Controllers return `0` for hardware they do not have. Ambient temperature, high
limit temperature, and the four reminder counters are treated as *unknown* when
zero rather than published as real readings, since "0 days until filter clean"
would otherwise read as permanently overdue.

The water temperature needs the same care. The spa's sensor sits in the
plumbing, so when the pump has not run for a while — routine in Rest mode
between filter cycles — the panel shows `---` and the API reports an
impossible value (around 262 °F). Like the ControlMySpa portal, anything above
150 °F or at or below 1 °F is treated as no reading. Rather than leave a gap,
the last good reading is **held** until the pump runs again:

- **Water temperature held** (diagnostic) is on while the value is held. Put it
  in the same History Graph card as the water temperature and it draws as a
  coloured bar under the line, marking where the value was not measured.
- The water temperature sensor's `measured_at` attribute is when its value was
  actually taken.
- **Water temperature (raw)** (diagnostic) is `currentTemp` exactly as the API
  sends it each poll: in the spa's own unit with no conversion or rounding, and
  with nothing filtered or held, so the ~262 °F no-reading value shows as it
  is. Graph the ordinary water temperature; use this one to see what the spa
  really reported.

After a Home Assistant restart there is nothing to hold, so the temperature is
*Unknown* until the spa next measures it.

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
available during an outage — they are how you see what is going on. The
**Refresh** button stays available too, so a failed read can be retried.

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
against your spa and prints what the thermostat, temperature range, heat mode,
light, blower and lock entities would show — the way to check a change before
releasing it. It is read-only unless given one of `--light`, `--blower`,
`--heat-mode`, `--temp` (in the spa's own unit), `--temp-c` (Celsius, converted
as a Celsius Home Assistant would), `--panel-lock` or `--temp-range`, which
sends that one command and re-reads until the spa reports it:

```bash
python scripts/verify_controls.py --email you@example.com
python scripts/verify_controls.py --email you@example.com --blower on
python scripts/verify_controls.py --email you@example.com --temp-c 38.5
python scripts/verify_controls.py --email you@example.com --temp-range low
```

`scripts/light_control.py` is a lower-level diagnostic that talks to the
component endpoints directly. Its `--watch SECONDS` polls and reports every
component change — the way to see whether, and how quickly, a change made at
the spa's panel reaches the cloud. `--raw` dumps the components array (with
identifying fields redacted) and `--mqtt` the spa's recent uplinks.

All the scripts read the password from `CONTROLMYSPA_PASSWORD` or prompt for it.

## Write support

Command formats were recovered from the ControlMySpa web portal's own
JavaScript rather than guessed, and the temperature, temperature range, light,
blower, heat mode and panel lock commands were all verified against a real spa:

```json
POST /web/spa-commands/component-state
{"spaId": "...", "via": "WEB", "componentType": "light", "state": "HIGH", "deviceNumber": 0}

POST /web/spa-commands/temperature/heater-mode
{"spaId": "...", "via": "WEB", "mode": "REST"}

POST /web/spa-commands/temperature/value
{"spaId": "...", "via": "WEB", "value": 101}

POST /web/spa-commands/panel/state
{"spaId": "...", "via": "WEB", "state": "LOCK_PANEL"}

POST /web/spa-commands/temperature/range
{"spaId": "...", "via": "WEB", "range": "LOW"}
```

The temperature `value` is always Fahrenheit, even for spas displayed in
Celsius. The portal converts and sends half degrees, but the spa keeps only
whole ones (100.5 was accepted and stored as 100), so the integration sends the
nearest whole degree.

Device state comes from `GET /web/spas/{id}/current-state`, whose `components`
array lists every controllable device — lights, pumps, blower, circulation
pump, filters — with its current value and the values it accepts. It reflected
an accepted command within three seconds when tested.

Everything else the portal can do is listed under [Roadmap](#roadmap).

## Roadmap

Planned, not yet released. Command formats for all of these were recovered from
the portal's own JavaScript; each will be verified against a real spa with
`scripts/verify_controls.py` before release, as the current controls were.

- **Spa clock** — show the spa's current time, set it, and a **Sync time**
  button that sets it to Home Assistant's local time in one tap, keeping the
  spa's 12/24-hour setting. The spa keeps no seconds and does not adjust for
  daylight saving, so a daily automation pressing Sync is worthwhile.
  (`POST /web/spa-commands/time` with `time` as `"HH:MM"` and
  `isMilitaryFormat`.)
- **Jets** — control each pump at its two speeds, Low and High.
  (`component-state` with `jet` and the pump's port.)
- **Filter cycles 1 and 2** — each cycle's start time and duration, and turning
  filter cycle 2 on or off (filter 1 always runs). The schedule controls are
  built, but on the test spa a schedule change was accepted and never took
  effect, not even when made in the ControlMySpa portal itself, so they are
  held back while that is investigated. (`filter-cycles/schedule` with `time` as
  `"HH:MM"` and `numOfIntervals` in 15-minute blocks;
  `filter-cycles/toggle-filter2-state`.)
- **Keep the held water temperature across a restart**, so it is not unknown
  until the pump next runs.

## Changelog

### Unreleased

- **Spa clock.** `time.spa_time` reads and sets the clock the spa keeps for
  itself, which is what schedules its filter cycles.
- **Sync time button.** `button.spa_sync_time` sets that clock from Home
  Assistant's local time, for correcting drift and daylight saving. Both
  entities are unavailable while the spa reports its controller link is down.
- **Heating now reads On / Off.** It was declared with the `heat` device
  class, so Home Assistant rendered it as Hot / Normal, which reads as a
  temperature warning rather than whether the heater is running. Display only:
  the state is unchanged, so existing automations keep working.
- **Filter cycle schedules.** `sensor.spa_filter_N_start_time` and
  `sensor.spa_filter_N_duration` report when each cycle starts and how long it
  runs, with the cycle's own `ON` / `OFF` / `DISABLED` state as a `status`
  attribute. Read-only: ControlMySpa does not reliably apply a schedule change,
  even from its own portal.

### v0.2.4

- **Ready mode switch.** A one-tap toggle for the heat mode: on for Ready, off
  for Rest.
- **Panel lock.** Lock and unlock the spa's control panel from Home Assistant.
  **Breaking:** this lock entity (`lock.spa_panel_lock`) replaces the Panel lock
  binary sensor. Update any automation that used `binary_sensor.spa_panel_lock`,
  then delete the old entity from the device page.
- **Water temperature (raw) sensor.** The water temperature exactly as the API
  returns it, including the no-reading value, alongside the existing filtered
  and held one.
- **Temperature range select.** Switch between High and Low; the thermostat's
  limits follow. **Breaking:** this select (`select.spa_temperature_range`)
  replaces the Temperature range sensor. Update any automation that used
  `sensor.spa_temperature_range` (its states were `HIGH` / `LOW`; the select's
  are `high` / `low`), then delete the old entity from the device page.
- `scripts/verify_controls.py --panel-lock` and `--temp-range`; it also shows
  the lock and range values from both of the API's records.

### v0.2.3

- **Refresh button.** Re-reads the spa from ControlMySpa immediately instead of
  waiting for the next poll.

### v0.2.2

- **Integration icon.** A hot tub badge now shows on the Integrations page, in
  Home Assistant 2026.3 or newer.

### v0.2.1

- **Celsius display matches the spa.** In a Celsius Home Assistant, the
  thermostat and temperature sensors round as the portal and panel do (100 °F
  reads 37.5 °C, not 37.8), and the target steps in half degrees.
- **Celsius targets set exactly.** Targets are sent as whole °F, because the
  spa discards half degrees.
- **Ready / Rest thermostat presets**, so the thermostat row reads e.g.
  "Idle (Heat - Rest)".
- **No more impossible water temperature.** The ~262 °F value the spa reports
  when its pump has not run (panel shows `---`) is ignored, and the last good
  reading is held instead. New **Water temperature held** diagnostic sensor and
  `measured_at` attribute show when that is happening.
- **Polls every 5 minutes by default** instead of every 30 seconds.
- `scripts/verify_controls.py --temp-c`, and `scripts/light_control.py` for
  component-level debugging.

### v0.2.0

- **Controls:** thermostat (target temperature), light, blower, and heat mode
  (Ready / Rest), all verified against a real spa.
- Device state read from `/web/spas/{id}/current-state`.
- **Breaking:** the Heater mode sensor now reports `ready` / `rest` /
  `ready_rest` instead of `READY` / `REST` / `READY_REST`.

### v0.1.0

- Read-only release: temperatures, heater and run state, locks, reminders, and
  connectivity diagnostics.

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

The icon in `custom_components/controlmyspa/brand/` is rendered from
`scripts/icon.svg`. After changing the SVG, regenerate both sizes on a Mac:

```bash
swift scripts/render_icon.swift scripts/icon.svg custom_components/controlmyspa/brand/icon.png 256
swift scripts/render_icon.swift scripts/icon.svg custom_components/controlmyspa/brand/icon@2x.png 512
```

## Branches and releases

HACS installs from GitHub **releases**, not from branches. If a repository has
no releases it falls back to the default branch, which is why the branch layout
and the release process do separate jobs:

| Branch | Role |
|---|---|
| `main` | Stable. Tagged and released from here. |
| `develop` | Work in progress. Never installed directly by anyone. |

Cutting a release:

1. On `develop`, bump `"version"` in `custom_components/controlmyspa/manifest.json`
   and rename the changelog's **Unreleased** heading to the new version
2. Merge `develop` into `main` (fast-forward)
3. Tag it to match, e.g. `git tag -a v0.2.0 -m "..."` and push the tag
4. Create a GitHub release from that tag — HACS ignores a tag without one

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
