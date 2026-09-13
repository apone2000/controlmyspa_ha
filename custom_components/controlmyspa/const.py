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
# uplink. A grace period on top of it stops entities flapping when an uplink
# arrives slightly late.
STALE_GRACE: Final = 120

# Fallback when the payload carries no staleTimestamp at all.
STALE_AFTER: Final = 900

# The payload's "celsius" field reports an app display preference, not the unit
# the values are actually in, so the unit is inferred from the configured
# limits instead. Spa maximums are ~40C / ~104F, so nothing sits near this
# boundary and the test cannot be ambiguous.
FAHRENHEIT_THRESHOLD: Final = 50

MANUFACTURER: Final = "Balboa Water Group"
