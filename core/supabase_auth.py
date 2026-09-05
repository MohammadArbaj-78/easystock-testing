"""
Supabase Authentication.

Replaces the old custom application-level login/signup (formerly
core/auth.py - deleted as part of this migration, since a bug in a
Python-only bcrypt/password system, and Supabase's own managed identity
service, would otherwise silently coexist as two parallel authentication
systems). Supabase Auth is now the ONLY authentication provider - Email
+ Password, matching what this project already had (no Google/GitHub/
phone/OAuth/magic-link providers are added here).

This module is the ONLY place in the application that calls into
supabase-py's `auth` client. It does NOT touch core/supabase_client.py
(the existing, separate business-data client used by
modules/products/repository.py etc. when ACTIVE_DB_BACKEND=="supabase")
- Auth deliberately uses its own client and its own secret
(SUPABASE_ANON_KEY, the public/anon key, never the service-role key),
kept apart from whatever key core/supabase_client.py is configured with
for business-table access, so the two concerns (identity vs. business
data) can never accidentally share or leak a privileged credential.

The `stores` table (core/database.py) still holds business identity
(store_name, owner_name) exactly as before - this migration does NOT
redesign or drop that table. It gains exactly one new column,
`supabase_user_id` (see core/database.py's initialize_database()), used
here only to look up which store row belongs to a given Supabase-
authenticated user. The old `mobile_number`/`password_hash` columns are
left in place, unused by any new signup from this point on (see
sign_up_and_create_store()'s docstring for how a NOT NULL/UNIQUE
mobile_number and a NOT NULL password_hash are satisfied without a
schema change) - old rows created by the removed custom system have no
`supabase_user_id` and simply cannot be signed into anymore, which
matches the project owner's explicit instruction that this old
authentication data is not important and does not need to be migrated.

Session persistence: a Streamlit rerun (radio nav click, form submit,
page change) re-executes this script inside the SAME server-side
browser session, and st.session_state already survives that
automatically - exactly the mechanism the old custom system already
relied on via core/session.py. So "don't force login again on a normal
rerun/navigation" falls out of storing the Supabase session (access
token + refresh token, alongside store_id/store_name/owner_name) in
st.session_state once at login, the same way core/session.py already
stored a plain store_id before this migration - no second, Python-only
session system is introduced to imitate Supabase; st.session_state IS
the persistence layer core/session.py already owned, now holding a
Supabase-issued session instead of a locally-authenticated one.
"""

from typing import Optional, Tuple

import streamlit as st

from core.database import get_connection
from core.exceptions import SupabaseAuthError, SupabaseConfigError, DatabaseError, ValidationError
from utils.validators import validate_required_text, validate_password

# Module-level singleton state, exactly mirroring core/supabase_client.py's
# own lazy-singleton pattern - but a SEPARATE client/cache, since this
# one is configured with SUPABASE_ANON_KEY (public/anon key, safe for a
# client-facing auth flow), not whatever key core/supabase_client.py
# uses for business-table access.
_auth_client = None
_url: Optional[str] = None
_anon_key: Optional[str] = None


def _read_auth_config() -> Tuple[str, str]:
    """Read and validate SUPABASE_URL / SUPABASE_ANON_KEY from st.secrets.

    Returns:
        (url, anon_key) as stripped, non-empty strings.

    Raises:
        SupabaseConfigError: If either secret is missing or blank.
    """
    try:
        url = st.secrets["SUPABASE_URL"]
    except (KeyError, FileNotFoundError):
        url = None

    try:
        anon_key = st.secrets["SUPABASE_ANON_KEY"]
    except (KeyError, FileNotFoundError):
        anon_key = None

    if not url or not str(url).strip():
        raise SupabaseConfigError(
            "SUPABASE_URL is missing from Streamlit secrets. Add it to "
            ".streamlit/secrets.toml (or your deployment's secrets "
            "settings) before signing in."
        )

    if not anon_key or not str(anon_key).strip():
        raise SupabaseConfigError(
            "SUPABASE_ANON_KEY is missing from Streamlit secrets. Add "
            "the project's public/anon key (never the service-role key) "
            "to .streamlit/secrets.toml before signing in."
        )

    return str(url).strip(), str(anon_key).strip()


def _build_supabase_auth_client():
    """Create a fresh, unconfigured Supabase client for Auth calls.

    Split out as its own function (rather than inlined into
    _get_auth_client()) purely so tests can patch this one seam - the
    same pattern modules/invoice_scan/ocr_service.py's
    _build_genai_client() already establishes for mocking a third-party
    client in tests without needing the real package installed or a
    real network call.
    """
    from supabase import create_client
    return create_client(_url, _anon_key)


def _get_auth_client():
    """Get the single shared Supabase Auth client, creating it on first
    use (lazy singleton - importing this module never requires
    SUPABASE_URL/SUPABASE_ANON_KEY to be configured or the `supabase`
    package to be installed, matching core/supabase_client.py's own
    lazy-import discipline).

    Raises:
        SupabaseConfigError: If SUPABASE_URL or SUPABASE_ANON_KEY is
            missing or blank in Streamlit secrets.
    """
    global _auth_client, _url, _anon_key
    if _auth_client is None:
        _url, _anon_key = _read_auth_config()
        _auth_client = _build_supabase_auth_client()
    return _auth_client


def _extract_session(auth_response) -> dict:
    """Pull the fields this app actually needs out of a gotrue
    AuthResponse (returned by both sign_up() and
    sign_in_with_password()), so the rest of this module - and its
    tests - depend on one small plain dict shape, not on gotrue's own
    response object structure.

    Returns:
        {"user_id": str, "email": str, "access_token": str,
         "refresh_token": str}

    Raises:
        SupabaseAuthError: If the response has no session (e.g. Supabase
            is configured to require email confirmation before a
            session is issued) or no user.
    """
    user = getattr(auth_response, "user", None)
    session = getattr(auth_response, "session", None)
    if user is None or session is None:
        raise SupabaseAuthError(
            "Sign-up succeeded but no session was returned. If your "
            "Supabase project requires email confirmation, confirm the "
            "email address first, then log in."
        )
    return {
        "user_id": user.id,
        "email": user.email,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }


def sign_up_and_create_store(store_name: str, owner_name: str, email: str, password: str) -> dict:
    """Create a new Supabase Auth user (Email + Password) and the
    business `stores` row that represents them.

    The old custom system's `stores.mobile_number` (NOT NULL UNIQUE)
    and `stores.password_hash` (NOT NULL) columns are satisfied without
    a schema change: mobile_number stores this same email address
    (still genuinely unique and non-null, just no longer literally a
    phone number - the column's old purpose is obsolete now that
    Supabase, not this table, verifies identity) and password_hash
    stores a fixed sentinel string, never a real password or anything
    derived from one - Supabase Auth is now the sole holder of the
    actual credential, so duplicating even a hash of it here would be a
    pointless security liability, not a genuine second factor.

    Args:
        store_name: Name of the medical store.
        owner_name: Name of the store owner.
        email: Owner's email address.
        password: Plaintext password (Supabase enforces its own
            minimum requirements; validate_password() additionally
            enforces this project's existing 6-20 character rule
            client-side before the network call).

    Returns:
        A dict with keys "store_id", "store_name", "owner_name",
        "access_token", "refresh_token" - ready for
        core.session.start_session().

    Raises:
        ValidationError: If store_name/owner_name is blank or the
            password fails this project's existing length rule.
        SupabaseAuthError: If Supabase rejects the sign-up (e.g. email
            already registered, invalid email, weak password) or the
            local store row cannot be created afterward.
    """
    clean_store_name = validate_required_text(store_name, "Store Name")
    clean_owner_name = validate_required_text(owner_name, "Owner Name")
    clean_email = validate_required_text(email, "Email")
    validate_password(password)

    try:
        auth_response = _get_auth_client().auth.sign_up(
            {"email": clean_email, "password": password}
        )
    except SupabaseConfigError:
        raise
    except Exception as error:
        raise SupabaseAuthError(_friendly_auth_error(error, context="sign up")) from error

    session = _extract_session(auth_response)

    try:
        store_id = _create_store_row(
            clean_store_name, clean_owner_name, clean_email, session["user_id"]
        )
    except DatabaseError as error:
        if "UNIQUE constraint failed" in str(error):
            raise SupabaseAuthError(
                "An account already exists for this email. Please log in instead."
            ) from error
        raise SupabaseAuthError(f"Account created, but saving store details failed: {error}") from error

    store = _fetch_store_by_supabase_user_id(session["user_id"])

    if store is None:
        raise SupabaseAuthError(
            "Account was created, but the store could not be resolved."
        )
    
    return {
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "owner_name": store["owner_name"],
        "low_stock_minimum": store["low_stock_minimum"],
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
    }


def sign_in_and_resolve_store(email: str, password: str) -> dict:
    """Authenticate an existing store owner via Supabase Auth (Email +
    Password), then resolve which local `stores` row belongs to them.

    Args:
        email: Email address as entered at login.
        password: Plaintext password as entered at login.

    Returns:
        A dict with keys "store_id", "store_name", "owner_name",
        "access_token", "refresh_token" - ready for
        core.session.start_session().

    Raises:
        SupabaseAuthError: If Supabase rejects the credentials, or if
            the credentials are valid but no local store row is linked
            to this Supabase user yet (e.g. the account exists in
            Supabase but Sign Up was never completed in this app).
    """
    clean_email = validate_required_text(email, "Email")

    try:
        auth_response = _get_auth_client().auth.sign_in_with_password(
            {"email": clean_email, "password": password}
        )
    except SupabaseConfigError:
        raise
    except Exception as error:
        raise SupabaseAuthError(_friendly_auth_error(error, context="login")) from error

    session = _extract_session(auth_response)

    store = _fetch_store_by_supabase_user_id(session["user_id"])
    if store is None:
        raise SupabaseAuthError(
            "This account is not linked to a store yet. Please use "
            "Sign Up to finish creating your store."
        )

    return {
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "owner_name": store["owner_name"],
        "low_stock_minimum": store["low_stock_minimum"],
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
    }


def restore_session(refresh_token: str) -> dict:
    """Restore a previously-issued Supabase session from a saved
    refresh token (Requirement 2 - browser close/reopen persistence).

    Called by app.py on a fresh Streamlit connection (empty
    st.session_state) when a refresh token was recovered from the
    browser's localStorage - see app.py's startup-restoration block.
    Uses Supabase Auth's own refresh_session() call, the standard way
    to exchange a still-valid refresh token for a new access token
    without asking the user to re-enter a password - no new
    authentication library or system is introduced; this is the same
    Supabase Auth client/session model already used by sign_in_and_resolve_store().

    Args:
        refresh_token: The refresh token previously saved to
            localStorage at login (see core/login_ui.py).

    Returns:
        A dict with keys "store_id", "store_name", "owner_name",
        "access_token", "refresh_token" - the exact same shape
        sign_in_and_resolve_store() returns, ready for
        core.session.start_session().

    Raises:
        SupabaseAuthError: If the refresh token is invalid, expired, or
            revoked, or if it's valid but the resolved user has no
            linked local store row. Callers (app.py) must catch this
            and fall back to the normal login screen - an invalid
            stored token must never crash the app.
    """
    if not refresh_token or not str(refresh_token).strip():
        raise SupabaseAuthError("No stored session to restore.")

    try:
        auth_response = _get_auth_client().auth.refresh_session(refresh_token)
    except SupabaseConfigError:
        raise
    except Exception as error:
        raise SupabaseAuthError(_friendly_auth_error(error, context="session restore")) from error

    # Both calls below used to sit outside any try/except here. Left
    # unguarded, an unexpected failure from either (e.g. a raw sqlite3
    # error from _fetch_store_by_supabase_user_id) would propagate
    # uncaught past this function and past app.py's
    # _attempt_session_restoration(), which only catches
    # (SupabaseAuthError, SupabaseConfigError) - Streamlit would then
    # render it as a red error box during startup restoration. Wrapped
    # the same way the refresh_session() call above already is:
    # SupabaseAuthError raised directly by _extract_session() (its own,
    # already-correct failure signal) passes through unchanged; anything
    # else is converted to SupabaseAuthError via the same
    # _friendly_auth_error() helper, so app.py's existing catch handles
    # it exactly as before - no new exception type, no change to the
    # caught-error recovery path (st.query_params.clear(), rerun, etc.).
    try:
        session = _extract_session(auth_response)
        store = _fetch_store_by_supabase_user_id(session["user_id"])
    except SupabaseAuthError:
        raise
    except Exception as error:
        raise SupabaseAuthError(_friendly_auth_error(error, context="session restore")) from error

    if store is None:
        raise SupabaseAuthError(
            "This account is not linked to a store yet. Please use "
            "Sign Up to finish creating your store."
        )

    return {
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "owner_name": store["owner_name"],
        "low_stock_minimum": store["low_stock_minimum"],
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
    }


def sign_out(access_token: str = None) -> None:
    """Sign out of the current Supabase session.

    Safe to call even if Supabase is not configured or the sign-out
    call itself fails (e.g. token already expired) - logout must always
    succeed from the application's point of view (core.session.end_session()
    always clears the local session regardless), so any Supabase-side
    failure here is swallowed rather than blocking the user from
    logging out.

    Args:
        access_token: Unused by supabase-py's sign_out() (it operates
            on the client's own currently-set session), accepted for a
            clear call-site signature and possible future use.
    """
    try:
        _get_auth_client().auth.sign_out()
    except Exception:
        pass


def _friendly_auth_error(error: Exception, context: str) -> str:
    """Turn whatever supabase-py/gotrue raises into one plain-language
    message, never exposing internal exception class names or raw
    provider payloads to the UI.
    """
    message = str(error).strip()
    if not message:
        message = f"Could not complete {context}."
    return message


# =====================================================================
# Supabase store-row lookup/creation - the only place this module
# touches the `stores` table directly, via core.supabase_client's
# shared client (the same one modules/products/repository.py and
# modules/sales/repository.py already use for products/sales_history).
# Confirmed schema: store_id (bigint, PK), created_at, store_name
# (nullable), owner_name (nullable), UID (uuid, nullable, FK to
# auth.users.id).
# =====================================================================


def _create_store_row(store_name: str, owner_name: str, email: str, supabase_user_id: str) -> int:
    """Insert the new store into Supabase's `stores` table, linked to
    the Auth user via the `UID` column - the Supabase-hosted
    replacement for the old local-SQLite store row (that table's
    confirmed schema is store_id, created_at, store_name, owner_name,
    UID - no email/mobile column). `email` is accepted only for
    call-site compatibility with sign_up_and_create_store(), which
    already passes it - it is not written here, since there is nowhere
    in the confirmed schema to put it and Supabase Auth already owns
    that value on the auth.users row itself.

    Raises:
        DatabaseError: If the insert fails for any reason other than a
            missing/blank Supabase configuration - converted here the
            same way core.database.get_connection() used to convert a
            raw sqlite3.Error, so the existing
            "except DatabaseError" handling in sign_up_and_create_store()
            keeps working unchanged.
        SupabaseConfigError: Propagated as-is (not converted) if
            SUPABASE_URL/SUPABASE_KEY are missing - matches how every
            other Supabase-config failure in this file is handled, and
            is already caught by login_ui.py's UI-layer except clause.
    """
    from core.supabase_client import get_supabase_client

    try:
        response = (
            get_supabase_client()
            .table("stores")
            .insert({
                "store_name": store_name,
                "owner_name": owner_name,
                "UID": supabase_user_id,
            })
            .execute()
        )
    except SupabaseConfigError:
        raise
    except Exception as error:
        raise DatabaseError(str(error)) from error

    if not response.data:
        raise DatabaseError("Supabase stores insert returned no row.")

    return response.data[0]["store_id"]

def update_store_low_stock_minimum(store_id: int, value: int) -> None:
    """Update the global Low Stock minimum for one store."""

    from core.supabase_client import get_supabase_client

    try:
        (
            get_supabase_client()
            .table("stores")
            .update({"low_stock_minimum": value})
            .eq("store_id", store_id)
            .execute()
        )
    except SupabaseConfigError:
        raise
    except Exception as error:
        raise DatabaseError(str(error)) from error

def _fetch_store_by_supabase_user_id(supabase_user_id: str):
    """Look up the store linked to this Auth user via Supabase's
    `stores.UID` column - the Supabase-hosted replacement for the old
    local-SQLite lookup by `supabase_user_id`. Returns the same shape
    as before (store_id, store_name, owner_name) so callers
    (sign_in_and_resolve_store, restore_session) are unaffected.
    """
    from core.supabase_client import get_supabase_client

    response = (
        get_supabase_client()
        .table("stores")
        .select("store_id, store_name, owner_name, low_stock_minimum")
        .eq("UID", supabase_user_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None
