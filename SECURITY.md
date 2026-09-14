# Security policy

## Supported versions

Only the latest release receives fixes. Update through HACS before reporting,
in case the problem is already fixed.

| Version | Supported |
|---|---|
| Latest release | Yes |
| Anything older | No |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub instead: open the repository's **Security**
tab and choose **Report a vulnerability**. Only the maintainer can see the
report.

Include what you found, how to reproduce it, and what an attacker could do
with it. **Never include real credentials or account data** — no ControlMySpa
email or password, access or refresh tokens, spa id, serial number, `regKey`,
or a raw dump from `scripts/probe.py --dump`. Placeholder values are enough.

This is a personal project maintained in spare time, so reports are handled on
a best-effort basis. You will get a reply once the report has been read, and a
fix, if one is needed, goes out as a new release with a note in the changelog.

## Scope

In scope — this repository's code:

- How the integration handles your ControlMySpa credentials and access tokens
- Anything that could expose account data through logs, entity attributes or
  errors
- The scripts in `scripts/`, including their output redaction

Out of scope — please report these elsewhere:

- **The ControlMySpa cloud service or its apps** (`iot.controlmyspa.com`,
  the web portal, the mobile app) — these belong to Balboa Water Group, not
  this project.
- **Home Assistant itself** — see Home Assistant's own security policy.
- Problems that require someone who already has access to your Home Assistant
  configuration directory or its backups.

## How credentials and data are handled

- **Credentials** are the email and password you enter during setup. Home
  Assistant stores them in the integration's config entry, in
  `.storage/core.config_entries` under your configuration directory, as it
  does for other integrations. That file is plain JSON: it is protected by
  access to the configuration directory, and it is included in Home Assistant
  backups, so protect those (Home Assistant can encrypt backups).
- **Access tokens** are held in memory only and are never written to disk. The
  token's expiry is read to schedule renewal; nothing trusts its contents
  beyond that.
- **Network:** the integration talks only to `https://iot.controlmyspa.com`,
  over HTTPS, using Home Assistant's shared HTTP session with its default
  certificate verification.
- **Logs** never contain the password or tokens. Error messages are the
  service's own or describe the failure, not the request.
- **The scripts** read the password from the `CONTROLMYSPA_PASSWORD`
  environment variable or prompt for it, and never print it or a token.
  `inspect_payload.py` and `light_control.py` redact identifying fields in
  their output, so theirs is the output to share. The others print summaries
  meant for your own terminal — `probe.py`, for one, shows the spa's serial
  number — so review their output before posting it anywhere.
  `probe.py --dump` writes the full raw record, including account identifiers,
  to a file that is gitignored and must not be shared.
