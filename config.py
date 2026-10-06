"""Configuration for the Uber Eats Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT             port the API listens on (default 8000)
    UBER_EATS_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                     (default: none — direct). Direct works out of the box.
                     Uber Eats guards its store, feed and search data per IP:
                     after a few hundred calls from one address it answers
                     403 with a reCAPTCHA challenge. When that happens, set
                     this to a residential proxy and keep going.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

UBER_EATS_PROXY = os.environ.get("UBER_EATS_PROXY") or None

# After a 403 / 429 a worker keeps using the proxy (when one is set) this long.
UBER_EATS_BLOCK_COOLDOWN = 900


def uber_eats_proxy():
    """Proxy for every session (None = direct)."""
    return os.environ.get("UBER_EATS_PROXY") or None


def uber_eats_fallback_proxy():
    """Proxy a worker falls back to after a block (None = no fallback)."""
    return os.environ.get("UBER_EATS_PROXY") or None
