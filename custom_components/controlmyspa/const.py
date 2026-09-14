"""Constants for the ControlMySpa integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "controlmyspa"

# The cloud API. Every route hangs off the /web prefix; the older /idm
# discovery document was removed upstream and no longer exists.
API_BASE: Final = "https://iot.controlmyspa.com"
API_ROOT: Final = f"{API_BASE}/web"

ENDPOINT_LOGIN: Final = f"{API_ROOT}/auth/login"
ENDPOINT_REFRESH: Final = f"{API_ROOT}/auth/refresh"
ENDPOINT_PROFILE: Final = f"{API_ROOT}/auth/profile"
ENDPOINT_SPAS: Final = f"{API_ROOT}/spas"
ENDPOINT_COMMANDS: Final = f"{API_ROOT}/spa-commands"

# Every command names its origin. The portal sends WEB; the other values the
# service accepts are MOBILE, GATEWAY, SCHEDULED and ALEXA.
COMMAND_VIA: Final = "WEB"

# How long to wait after an accepted command before re-reading state. The
# service reflected commands within three seconds when tested, so reading back
# immediately would fetch the old value and briefly undo the optimistic update.
COMMAND_REFRESH_DELAY: Final = 5

# Requests hang indefinitely without this; upstream had no timeout set and a
# single bad gateway stalled the poll loop for a full minute.
REQUEST_TIMEOUT: Final = 20

# Access tokens are issued with a 24h lifetime. Renew early so a long poll
# cannot straddle the expiry boundary.
TOKEN_EXPIRY_MARGIN: Final = 300

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

# The API supplies its own staleTimestamp, roughly three minutes after each
# uplink. That window describes how fresh a reading is, not how long the spa is
# worth listening to: spas uplink far less often than every three minutes, so
# this drives the "stale data" diagnostic only, never availability.
STALE_GRACE: Final = 120

# Availability backstop. An online spa whose last uplink is older than this has
# stopped reporting in any meaningful sense, whatever its online flag claims.
STALE_AFTER: Final = 3600

# The payload's "celsius" field reports an app display preference, not the unit
# the values are actually in, so the unit is inferred from the configured
# limits instead. Spa maximums are ~40C / ~104F, so nothing sits near this
# boundary and the test cannot be ambiguous.
FAHRENHEIT_THRESHOLD: Final = 50

MANUFACTURER: Final = "Balboa Water Group"
