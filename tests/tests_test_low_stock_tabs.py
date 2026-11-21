"""Low Stock: which tabs show (Quick Setup switch), the Agency tab actions, the line html."""
import types
from unittest.mock import patch

from modules.alerts import low_stock_ui as ui
from modules.alerts import mode
from modules.low_stock_diary import agency_tab, repository, service


class _Settings:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def invoice_saves_real_quantity(self, store_id):
        self.calls += 1
        return self.value


def _with_session(state, settings):
    return (patch.object(mode, "st", types.SimpleNamespace(session_state=state)),
            patch.object(mode, "store_settings_service", settings))


def test_alerts_shown_when_switch_on_and_remembered():
    state, settings = {}, _Settings(True)
    a, b = _with_session(state, settings)
    with a, b:
        assert ui._alerts_enabled(1) is True
        assert ui._alerts_enabled(1) is True
    assert settings.calls == 1                       # the second look did not ask the database


def test_alerts_hidden_when_switch_off():
    state, settings = {}, _Settings(False)
    a, b = _with_session(state, settings)
    with a, b:
        assert ui._alerts_enabled(1) is False


def test_switch_change_is_seen_after_quick_setup_clears_the_memory():
    state, settings = {}, _Settings(True)
    a, b = _with_session(state, settings)
    with a, b:
        assert ui._alerts_enabled(1) is True
        settings.value = False
        assert ui._alerts_enabled(1) is True         # still the remembered value ...
        state.pop(ui._REAL_QTY_KEY)                  # ... until Quick Setup clears it
        assert ui._alerts_enabled(1) is False


def test_other_store_does_not_reuse_the_memory():
    state, settings = {}, _Settings(True)
    a, b = _with_session(state, settings)
    with a, b:
        ui._alerts_enabled(1)
        settings.value = False
        assert ui._alerts_enabled(2) is False


def test_alert_line_html():
    product = {"name": "Dolo <650>", "batch_number": "B1", "quantity": 2, "effective_threshold": 5, "mrp": 30.0, "rate": 0}
    text = ui._row_html(product, "warning")
    assert "Dolo &lt;650&gt;" in text and "Batch B1" in text and "MRP ₹30" in text
    assert "Rate" not in text and "Min 5" in text and ">2<" in text


def test_return_row_moves_it_back_to_the_diary():
    rows = [{"diary_id": 4, "name": "Dolo", "agency_id": 7}]
    state = {}
    with patch.object(agency_tab, "st", types.SimpleNamespace(session_state=state)), \
         patch.object(agency_tab.service, "return_to_diary") as moved, \
         patch.object(agency_tab.diary_ui, "_entries", return_value=rows):
        agency_tab._return_row(1, 4)
    moved.assert_called_once_with(1, [4])
    assert rows[0]["agency_id"] is None


def test_order_done_clears_and_tells():
    state = {}
    with patch.object(agency_tab, "st", types.SimpleNamespace(session_state=state)), \
         patch.object(agency_tab.service, "clear_agency_list", return_value=3) as cleared, \
         patch.object(agency_tab.diary_ui, "_reload") as reloaded:
        agency_tab._order_done(1, 7, "Sharma Agency")
    cleared.assert_called_once_with(1, 7)
    reloaded.assert_called_once_with(1)
    assert "Sharma Agency" in state[agency_tab._FLASH] and "3" in state[agency_tab._FLASH]
