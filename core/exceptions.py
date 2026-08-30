"""
Custom exceptions for EasyStock.

Why custom exceptions instead of returning None/False/error strings:
Calling code should never have to guess what went wrong. Each exception
type here maps to exactly one failure scenario, so a service or UI layer
can catch precisely what it knows how to handle and let everything else
propagate. This also means a function's return value always means
"success" - failure is always communicated via exception, never via a
sentinel value that could be mistaken for valid data.
"""


class EasyStockError(Exception):
    """Base class for all application-specific exceptions.

    Lets calling code catch 'any EasyStock-specific failure' with a single
    except clause when it doesn't need to distinguish the cause (e.g. at
    the top-level UI boundary, to show a generic error message).
    """
    pass


class ValidationError(EasyStockError):
    """Raised when user-provided input fails validation rules.

    Carries a human-readable message intended to be shown directly to the
    user (e.g. "Mobile number must be 10 digits").
    """
    pass


class DatabaseError(EasyStockError):
    """Raised when a database operation fails unexpectedly.

    Wraps lower-level sqlite3 errors so callers depend on an EasyStock
    exception type, not on sqlite3 internals leaking through every layer.
    """
    pass


class OCRError(EasyStockError):
    """Raised when OCR extraction fails in a way that is recoverable.

    Carries a human-readable message for the UI (e.g. "Could not parse
    the response from Gemini"). Distinct from GeminiAPIError so callers
    can choose to handle parse failures differently from network/auth
    failures if needed later.
    """
    pass


class GeminiAPIError(EasyStockError):
    """Raised when the Gemini API call itself fails: timeout, rate limit,
    invalid API key, network error, or any other API-level failure.

    Always carries a human-readable message that does NOT include the raw
    API key or internal token values, since this message will be shown
    directly in the UI via st.error().
    """
    pass


class SupabaseConfigError(EasyStockError):
    """Raised when Supabase configuration (SUPABASE_URL / SUPABASE_KEY
    for the business-data client, or SUPABASE_URL / SUPABASE_ANON_KEY
    for the Auth client) is missing or blank in Streamlit secrets.

    Raised instead of silently returning None/a broken client, matching
    every other exception in this file: a missing configuration value
    must be an explicit, catchable failure, never a value that could be
    mistaken for a working connection.
    """
    pass


class SupabaseAuthError(EasyStockError):
    """Raised when a Supabase Auth operation (sign up, sign in, sign
    out) fails: invalid credentials, an already-registered email, a
    password Supabase itself rejects, or any other Auth-level failure.

    Wraps whatever the supabase-py/gotrue client raises into a single
    EasyStock-specific type with a human-readable message, the same
    pattern GeminiAPIError already uses for a different third-party
    client - callers depend on one EasyStock exception type, never on
    the underlying package's own exception classes.
    """
    pass
