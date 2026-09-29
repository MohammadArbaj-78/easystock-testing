"""
Supabase connection layer - Phase 1 (infrastructure preparation only).

IMPORTANT: this module is not called from anywhere else in the codebase
yet. It exists purely to prepare a shared Supabase client for a future
migration phase. The application's active database remains SQLite via
core/database.py - no repository, service, or UI file imports this
module, and nothing here changes what the app actually does today.

Configuration is read from Streamlit's own secrets store (st.secrets) -
the standard place a Streamlit app keeps secrets (.streamlit/secrets.toml
locally, or the hosting platform's secrets UI when deployed) - not
environment variables. Two secrets are required:

    SUPABASE_URL - the Supabase project's REST API base URL.
    SUPABASE_ANON_KEY - the Supabase project's API key (anon or service role).

Both must be present and non-blank, or SupabaseConfigError is raised
immediately - this module never silently falls back to a missing or
partially-configured client. This matches every other exception in
core/exceptions.py: a missing configuration value is always an explicit,
catchable failure, never a value that could be mistaken for a working
connection.

The client itself is a lazy-initialized singleton: importing this module
never requires Supabase to be configured, and never opens a connection.
The client is created only the first time get_supabase_client() (or
verify_supabase_connection(), which calls it) is actually invoked, and
the same instance is reused for the lifetime of the process after that.
"""

from typing import Optional, Tuple

import streamlit as st
from supabase import create_client, Client

from core.exceptions import SupabaseConfigError

# Module-level singleton state. Populated on first use only - see
# get_supabase_client(). The URL/key are cached alongside the client
# (rather than read back off the Client object later) so
# verify_supabase_connection() never has to depend on the supabase
# package's internal attribute names.
_client: Optional[Client] = None
_url: Optional[str] = None
_key: Optional[str] = None


def _read_config() -> Tuple[str, str]:
    """Read and validate SUPABASE_URL / SUPABASE_ANON_KEY from st.secrets.

    Returns:
        (url, key) as stripped, non-empty strings.

    Raises:
        SupabaseConfigError: If either secret is missing or blank.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
    except (KeyError, FileNotFoundError):
        url = None

    try:
        key = st.secrets["SUPABASE_ANON_KEY"]
    except (KeyError, FileNotFoundError):
        key = None

    if not url or not str(url).strip():
        raise SupabaseConfigError(
            "SUPABASE_URL is missing from Streamlit secrets. Add it to "
            ".streamlit/secrets.toml (or your deployment's secrets "
            "settings) before using the Supabase client."
        )

    if not key or not str(key).strip():
        raise SupabaseConfigError(
            "SUPABASE_ANON_KEY is missing from Streamlit secrets. Add it to "
            ".streamlit/secrets.toml (or your deployment's secrets "
            "settings) before using the Supabase client."
        )

    return str(url).strip(), str(key).strip()


def get_supabase_client() -> Client:
    """Get the single shared Supabase client, creating it on first use.

    Raises:
        SupabaseConfigError: If SUPABASE_URL or SUPABASE_ANON_KEY is missing
            or blank in Streamlit secrets.

    Returns:
        The shared supabase.Client instance (the same object on every
        call after the first).
    """
    global _client, _url, _key
    if _client is None:
        _url, _key = _read_config()
        _client = create_client(_url, _key)
    return _client


def verify_supabase_connection() -> bool:
    """Lightweight, read-only check that the configured Supabase project
    is reachable. Does not read, insert, update, or delete any table row,
    and does not assume any particular table exists.

    Requests the REST API's own root endpoint (PostgREST's base path,
    not a specific table) using the same HTTP client the Supabase Python
    package itself already depends on (httpx) - so this adds no new
    dependency beyond what installing `supabase` already brings in.

    Any HTTP response at all (including a 4xx) confirms the network path
    and the Supabase project are reachable; only a connection-level
    failure (DNS failure, timeout, connection refused) means "not
    reachable" and is allowed to propagate as an httpx exception, since
    this function makes no claim about handling those - callers decide
    how to surface a connectivity failure.

    Raises:
        SupabaseConfigError: If SUPABASE_URL or SUPABASE_ANON_KEY is missing
            (propagated from get_supabase_client()).

    Returns:
        True if a response was received from the Supabase REST endpoint
        (status code below 500 - i.e. the server itself responded,
        rather than erroring internally). False if the server responded
        with a 5xx (reachable, but unhealthy).
    """
    get_supabase_client()  # validates config and populates _url/_key

    import httpx

    response = httpx.get(
        f"{_url}/rest/v1/",
        headers={"apikey": _key},
        timeout=10,
    )
    return response.status_code < 500
