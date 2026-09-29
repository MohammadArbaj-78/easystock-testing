"""
UI behavior tests for the Product Management "custom minimum stock
threshold" checkbox, using Streamlit's AppTest framework.

These exist specifically because a prior fix to this checkbox's
show/hide behavior was claimed as verified without an actual rerun
test having been run - this file is that verification, made real and
re-runnable, so the same regression can be caught automatically next
time rather than relying on a manual claim.

Run with: pytest tests/test_products_ui_threshold_checkbox.py -v
"""

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from core.database import initialize_database
from modules.products import service as products_service


def signup(store_name: str, owner_name: str, mobile_number: str, password: str) -> int:
    """Create a store row directly via SQLite, bypassing Supabase Auth
    (core.supabase_auth) - this project's authentication provider since
    the Supabase Auth migration. See tests/test_expiry_alerts.py's
    identical helper for the full rationale.
    """
    from core.database import get_connection
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO stores (store_name, owner_name, mobile_number, password_hash) "
            "VALUES (?, ?, ?, ?)",
            (store_name, owner_name, mobile_number, "test-only-not-a-real-hash"),
        )
        return cursor.lastrowid


@pytest.fixture
def logged_in_app(tmp_path, monkeypatch):
    """Provide an AppTest instance logged in as a fresh test store.

    Uses a temporary, isolated database per test so these tests never
    touch or depend on real data, and can run in any order without
    interfering with each other.

    core.database imports DATABASE_PATH by value at module load time
    (`from config.settings import DATABASE_PATH`), so patching
    config.settings.DATABASE_PATH after that import has already happened
    has no effect - the module still holds its own bound reference. The
    fix is to patch core.database.DATABASE_PATH directly, which is the
    name actually used inside get_connection().
    """
    import core.database as database_module

    db_path = tmp_path / "test_easystock.db"
    monkeypatch.setattr(database_module, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(database_module, "DATA_DIR", str(tmp_path))

    initialize_database()
    mobile = "9876500000"
    signup("Test Store", "Test Owner", mobile, "pass123")

    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    at.text_input[0].input(mobile)
    at.text_input[1].input("pass123")
    at.button[0].click()
    at.run()
    at.sidebar.radio[0].set_value("💊 Products").run()

    return at


def _threshold_field_visible(tab) -> bool:
    """Check whether the Minimum Stock Level number input is currently
    rendered in the given tab."""
    return any("Minimum Stock" in ni.label for ni in tab.number_input)


class TestAddProductCheckboxRerun:
    """Verifies the checkbox on the Add Product form reruns the script
    immediately, with no submit click required."""

    def test_field_hidden_by_default(self, logged_in_app):
        add_tab = logged_in_app.tabs[1]
        assert not _threshold_field_visible(add_tab)

    def test_checking_box_shows_field_instantly(self, logged_in_app):
        add_tab = logged_in_app.tabs[1]
        assert not _threshold_field_visible(add_tab)

        add_tab.checkbox[0].set_value(True).run()

        add_tab_after = logged_in_app.tabs[1]
        assert _threshold_field_visible(add_tab_after), (
            "Minimum Stock Level field did not appear immediately after "
            "checking the box - no submit button was clicked."
        )

    def test_unchecking_box_hides_field_instantly(self, logged_in_app):
        add_tab = logged_in_app.tabs[1]
        add_tab.checkbox[0].set_value(True).run()
        assert _threshold_field_visible(logged_in_app.tabs[1])

        logged_in_app.tabs[1].checkbox[0].set_value(False).run()
        assert not _threshold_field_visible(logged_in_app.tabs[1]), (
            "Minimum Stock Level field did not disappear immediately "
            "after unchecking the box."
        )

    def test_no_validation_error_from_toggling_alone(self, logged_in_app):
        logged_in_app.tabs[1].checkbox[0].set_value(True).run()
        assert len(logged_in_app.error) == 0, (
            "Toggling the checkbox alone must never trigger a validation "
            "error - validation should only run on Save."
        )

    def test_save_with_checkbox_on_and_blank_value_shows_correct_error(self, logged_in_app):
        add_tab = logged_in_app.tabs[1]
        add_tab.text_input[0].input("UI Test Med")
        add_tab.text_input[1].input("UI001")
        add_tab.checkbox[0].set_value(True).run()

        for ni in logged_in_app.tabs[1].number_input:
            if ni.label == "Quantity":
                ni.set_value(10)
            elif ni.label == "MRP":
                ni.set_value(15.0)
            # Minimum Stock Level intentionally left blank

        save_button = next(b for b in logged_in_app.tabs[1].button if "Add Product" in b.label)
        save_button.click().run()

        errors = [e.value for e in logged_in_app.error]
        assert any("Please enter a custom minimum stock level" in e for e in errors)


class TestEditProductCheckboxRerun:
    """Verifies the same instant show/hide behavior on the Edit Product
    form, which has the added complexity of an inline expander driven
    by session state."""

    def test_checking_box_shows_field_instantly_in_edit_form(self, logged_in_app, monkeypatch):
        # Seed one product so there's something to edit.
        from core.session import start_session

        store_id = 1  # the only store created by the logged_in_app fixture
        products_service.add_product(store_id, {
            "name": "Edit Test Med",
            "batch_number": "E001",
            "expiry_date": date.today() + timedelta(days=100),
            "quantity": 20,
            "mrp": 10.0,
            "_minimum_stock_threshold_enabled": False,
            "minimum_stock_threshold": None,
        })

        logged_in_app.sidebar.radio[0].set_value("💊 Products").run()
        list_tab = logged_in_app.tabs[0]
        edit_button = next(b for b in list_tab.button if "Edit" in b.label)
        edit_button.click().run()

        list_tab_after = logged_in_app.tabs[0]
        assert not _threshold_field_visible(list_tab_after)

        list_tab_after.checkbox[0].set_value(True).run()
        list_tab_final = logged_in_app.tabs[0]
        assert _threshold_field_visible(list_tab_final), (
            "Minimum Stock Level field did not appear immediately in the "
            "Edit Product form after checking the box."
        )
