"""
Focused tests for Requirement 2: Supabase Authentication.

The `supabase` package is not installed in this offline sandbox and
there is no network access, so these tests mock
core.supabase_auth._build_supabase_auth_client() - the same seam
pattern modules/invoice_scan/ocr_service.py's tests already use for
_build_genai_client(). This proves the project's own code (session
extraction, store creation/resolution, session-state storage, sign-out
behavior, error mapping) is correct; it does NOT and cannot verify a
real network call to a live Supabase project.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from core.database import initialize_database, get_connection
from core.exceptions import SupabaseAuthError, SupabaseConfigError, ValidationError
import core.supabase_auth as supabase_auth


def _setup_isolated_db(tmp_path, monkeypatch):
    import core.database as database_module
    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))
    initialize_database()
    return db_path


def _set_secrets(monkeypatch, url="https://example.supabase.co", anon_key="fake-anon-key"):
    """The harness's streamlit stub has no st.secrets - set one as a
    plain dict (Streamlit's real st.secrets is itself dict-like:
    supports `[...]` lookups), scoped to this test only."""
    secrets = {}
    if url is not None:
        secrets["SUPABASE_URL"] = url
    if anon_key is not None:
        secrets["SUPABASE_ANON_KEY"] = anon_key
    monkeypatch.setattr(st, "secrets", secrets)


def _mock_auth_response(user_id="user-uuid-1", email="owner@example.com",
                         access_token="access-tok-1", refresh_token="refresh-tok-1"):
    response = MagicMock()
    response.user.id = user_id
    response.user.email = email
    response.session.access_token = access_token
    response.session.refresh_token = refresh_token
    return response


def _reset_auth_client_singleton() -> None:
    """core.supabase_auth caches its client in module-level globals
    (the same lazy-singleton pattern core/supabase_client.py already
    uses). Called explicitly at the start of every test below that
    touches the client, rather than via an autouse pytest fixture,
    since this project's offline test harness (run_tests.py - real
    pytest is not installable here, no network access) only injects
    the `monkeypatch`/`tmp_path` fixtures by parameter name and does
    not execute autouse fixtures - without this explicit reset, one
    test's mocked client would leak into the next test's assertions."""
    supabase_auth._auth_client = None
    supabase_auth._url = None
    supabase_auth._anon_key = None


class TestSignUp:
    def test_sign_up_creates_store_linked_to_supabase_user(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = _mock_auth_response(user_id="uid-signup-1")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        result = supabase_auth.sign_up_and_create_store(
            "My Store", "Owner Name", "owner@example.com", "password123"
        )

        assert result["store_name"] == "My Store"
        assert result["owner_name"] == "Owner Name"
        assert result["access_token"] == "access-tok-1"
        assert result["refresh_token"] == "refresh-tok-1"
        assert isinstance(result["store_id"], int)

        mock_client.auth.sign_up.assert_called_once_with(
            {"email": "owner@example.com", "password": "password123"}
        )

        with get_connection() as connection:
            row = connection.execute(
                "SELECT store_name, owner_name, mobile_number, supabase_user_id FROM stores WHERE store_id = ?",
                (result["store_id"],),
            ).fetchone()
        assert row["supabase_user_id"] == "uid-signup-1"
        assert row["mobile_number"] == "owner@example.com"  # email reused, not a real phone number

    def test_sign_up_rejects_blank_store_name(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)
        with pytest.raises(ValidationError):
            supabase_auth.sign_up_and_create_store("", "Owner", "owner@example.com", "password123")

    def test_sign_up_maps_supabase_error_to_supabase_auth_error(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_up.side_effect = Exception("User already registered")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError, match="already registered"):
            supabase_auth.sign_up_and_create_store(
                "My Store", "Owner", "owner@example.com", "password123"
            )

    def test_sign_up_duplicate_email_in_local_store_table_raises_friendly_error(self, tmp_path, monkeypatch):
        """Same Supabase user signs up twice (e.g. a retried request) -
        the local UNIQUE constraint on mobile_number (now holding the
        email) must surface as SupabaseAuthError, not a raw DatabaseError."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = _mock_auth_response(user_id="uid-dup")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_up_and_create_store("Store A", "Owner", "dup@example.com", "password123")

        mock_client.auth.sign_up.return_value = _mock_auth_response(user_id="uid-dup-2")
        with pytest.raises(SupabaseAuthError, match="already exists"):
            supabase_auth.sign_up_and_create_store("Store B", "Owner", "dup@example.com", "password456")


class TestRestoreSession:
    def test_restore_session_with_valid_refresh_token(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = _mock_auth_response(user_id="uid-restore-1")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)
        signed_up = supabase_auth.sign_up_and_create_store(
            "Restore Store", "Owner", "restore@example.com", "password123"
        )

        mock_client.auth.refresh_session.return_value = _mock_auth_response(
            user_id="uid-restore-1", access_token="new-access-tok", refresh_token="new-refresh-tok"
        )
        result = supabase_auth.restore_session("old-refresh-tok")

        assert result["store_id"] == signed_up["store_id"]
        assert result["store_name"] == "Restore Store"
        assert result["access_token"] == "new-access-tok"
        assert result["refresh_token"] == "new-refresh-tok"
        mock_client.auth.refresh_session.assert_called_once_with("old-refresh-tok")

    def test_restore_session_with_invalid_token_raises_supabase_auth_error(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.refresh_session.side_effect = Exception("Invalid Refresh Token")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError, match="Invalid Refresh Token"):
            supabase_auth.restore_session("expired-or-bogus-token")

    def test_restore_session_with_blank_token_raises_without_calling_supabase(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError):
            supabase_auth.restore_session("")
        mock_client.auth.refresh_session.assert_not_called()

    def test_restore_session_for_user_with_no_linked_store_raises(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.refresh_session.return_value = _mock_auth_response(user_id="uid-orphan-2")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError, match="not linked to a store"):
            supabase_auth.restore_session("some-token")

    def test_restore_session_never_crashes_the_caller_pattern(self, tmp_path, monkeypatch):
        """Mirrors exactly how app.py's _attempt_session_restoration()
        must handle this: catch SupabaseAuthError/SupabaseConfigError,
        never let an invalid token propagate as an unhandled crash."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.refresh_session.side_effect = Exception("Token has expired")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        try:
            supabase_auth.restore_session("expired-token")
            assert False, "should have raised"
        except (SupabaseAuthError, SupabaseConfigError):
            pass  # exactly what app.py catches - no crash


class TestSignIn:
    def test_sign_in_resolves_existing_store(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_up.return_value = _mock_auth_response(user_id="uid-login-1")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)
        signed_up = supabase_auth.sign_up_and_create_store(
            "Login Store", "Owner", "login@example.com", "password123"
        )

        mock_client.auth.sign_in_with_password.return_value = _mock_auth_response(
            user_id="uid-login-1", access_token="access-tok-2", refresh_token="refresh-tok-2"
        )
        result = supabase_auth.sign_in_and_resolve_store("login@example.com", "password123")

        assert result["store_id"] == signed_up["store_id"]
        assert result["store_name"] == "Login Store"
        assert result["access_token"] == "access-tok-2"
        mock_client.auth.sign_in_with_password.assert_called_once_with(
            {"email": "login@example.com", "password": "password123"}
        )

    def test_sign_in_with_invalid_credentials_raises_supabase_auth_error(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError, match="Invalid login credentials"):
            supabase_auth.sign_in_and_resolve_store("nobody@example.com", "wrongpass")

    def test_sign_in_with_no_linked_store_raises_supabase_auth_error(self, tmp_path, monkeypatch):
        """A Supabase-authenticated user with no matching local store
        row (never completed Sign Up in this app) must get a clear
        error, not a crash."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_in_with_password.return_value = _mock_auth_response(user_id="uid-orphan")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        with pytest.raises(SupabaseAuthError, match="not linked to a store"):
            supabase_auth.sign_in_and_resolve_store("orphan@example.com", "password123")


class TestSignOut:
    def test_sign_out_ends_only_this_users_session(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_out("some-access-token", "some-refresh-token")
        mock_client.auth.set_session.assert_called_once_with("some-access-token", "some-refresh-token")
        mock_client.auth.sign_out.assert_called_once_with({"scope": "local"})

    def test_sign_out_never_touches_the_shared_client(self, tmp_path, monkeypatch):
        """The shared client holds whichever user signed in last - signing
        out on it would end that OTHER user's session."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        shared_client = MagicMock()
        supabase_auth._auth_client = shared_client
        supabase_auth._url = "https://example.supabase.co"
        supabase_auth._anon_key = "fake-anon-key"

        private_client = MagicMock()
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: private_client)

        supabase_auth.sign_out("acc", "ref")
        shared_client.auth.sign_out.assert_not_called()
        private_client.auth.sign_out.assert_called_once_with({"scope": "local"})

    def test_sign_out_without_tokens_signs_nobody_out(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_out("only-access-token")
        supabase_auth.sign_out()
        mock_client.auth.sign_out.assert_not_called()

    def test_sign_out_never_raises_even_if_supabase_call_fails(self, tmp_path, monkeypatch):
        """Logout must always succeed from the app's point of view -
        core.session.end_session() always clears local state regardless."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("network error")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_out("some-token", "some-refresh")  # must not raise

    def test_sign_out_never_raises_when_set_session_fails(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.set_session.side_effect = Exception("token expired")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_out("some-token", "some-refresh")  # must not raise
        
    def test_sign_out_never_raises_even_if_supabase_call_fails(self, tmp_path, monkeypatch):
        """Logout must always succeed from the app's point of view -
        core.session.end_session() always clears local state regardless."""
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch)

        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = Exception("network error")
        monkeypatch.setattr(supabase_auth, "_build_supabase_auth_client", lambda: mock_client)

        supabase_auth.sign_out("some-token")  # must not raise


class TestConfigMissing:
    def test_missing_supabase_url_raises_supabase_config_error(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch, url=None, anon_key="fake-key")
        with pytest.raises(SupabaseConfigError, match="SUPABASE_URL"):
            supabase_auth.sign_in_and_resolve_store("a@example.com", "password123")

    def test_missing_supabase_anon_key_raises_supabase_config_error(self, tmp_path, monkeypatch):
        _setup_isolated_db(tmp_path, monkeypatch)
        _reset_auth_client_singleton()
        _set_secrets(monkeypatch, url="https://example.supabase.co", anon_key=None)
        with pytest.raises(SupabaseConfigError, match="SUPABASE_ANON_KEY"):
            supabase_auth.sign_in_and_resolve_store("a@example.com", "password123")


class TestSessionPersistence:
    def test_start_session_stores_supabase_tokens(self, tmp_path, monkeypatch):
        """core.session.start_session() (called by core/login_ui.py
        immediately after a successful sign-in/sign-up) must store the
        Supabase access/refresh tokens in st.session_state alongside
        store_id/store_name/owner_name - the same st.session_state a
        normal Streamlit rerun/navigation already persists automatically,
        so no second Python-only session mechanism is needed."""
        from core.session import (
            start_session, get_current_store_id, get_current_access_token, is_logged_in,
        )
        st.session_state.clear()
        start_session(
            store_id=42, store_name="S", owner_name="O",
            access_token="tok-abc", refresh_token="refresh-xyz",
        )
        assert is_logged_in()
        assert get_current_store_id() == 42
        assert get_current_access_token() == "tok-abc"
        st.session_state.clear()

    def test_end_session_clears_everything(self, tmp_path, monkeypatch):
        from core.session import start_session, end_session, is_logged_in
        st.session_state.clear()
        start_session(store_id=1, store_name="S", owner_name="O", access_token="t", refresh_token="r")
        assert is_logged_in()
        end_session()
        assert not is_logged_in()


class TestOldAuthRemoved:
    def test_core_auth_module_no_longer_exists(self):
        with pytest.raises(ImportError):
            import core.auth  # noqa: F401

    def test_no_production_file_imports_core_auth(self):
        """Confirms no parallel/hidden old authentication system was
        left behind anywhere in the actual application code (test
        files are expected to reference the old module name only in
        prose, in the comments explaining their own signup() helper
        replacement - checked separately, not here)."""
        import subprocess
        project_root = Path(__file__).parent.parent
        production_dirs = ["app.py", "core", "modules", "config", "utils"]
        offenders = []
        for entry in production_dirs:
            path = project_root / entry
            paths = [path] if path.is_file() else path.rglob("*.py")
            for py_file in paths:
                text = py_file.read_text()
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith(("import core.auth", "from core.auth")):
                        offenders.append(str(py_file))
        assert offenders == []
