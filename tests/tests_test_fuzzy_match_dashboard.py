"""Invoice save: similar agency / medicine names are reused; Dashboard tiles and the Low Stock number."""
import types
from unittest.mock import patch

from core.name_matching import agency_similarity, similar_medicine_names
from modules.agencies import repository as agencies_repo
from modules.alerts import mode
from modules.dashboard import ui as dash
from modules.low_stock_diary import ui as diary_ui
from modules.products import service as products_service


# ---- agency names ----------------------------------------------------------
def test_agency_same_despite_space_entity_and_spelling():
    assert agency_similarity("Sharma Pharma", "SHARMAPHARMA") == 1.0
    assert agency_similarity("Sharma Pharma Pvt. Ltd.", "Sharma Pharma") == 1.0
    assert agency_similarity("Sharma", "Sharma Pharma") == 1.0           # a word added
    assert agency_similarity("Sharma Pharmaceuticals", "Sharma Pharma") == 1.0
    assert agency_similarity("Shree Krishna Medical", "Shree Krishna Medicals") == 1.0


def test_agency_different_names_stay_different():
    assert agency_similarity("Sharma Pharma", "Sharma Medical") == 0.0
    assert agency_similarity("Sharma Pharma", "Verma Pharma") == 0.0
    assert agency_similarity("Shree 1 Medical", "Shree 2 Medical") == 0.0
    assert agency_similarity("Gupta Agency", "Gupta Traders") == 0.0
    assert agency_similarity("Rajesh Gupta", "Rakesh Gupta") == 0.0     # spelling slips are NOT merged


def test_best_similar_agency_ambiguous_means_new():
    rows = [{"agency_id": 1, "agency_name": "Sharma Pharma"}, {"agency_id": 2, "agency_name": "Sharma Pharma"}]
    assert agencies_repo._best_similar_agency("Sharma Pharma Ltd", rows) is None
    assert agencies_repo._best_similar_agency("Sharma Pharma Ltd", rows[:1]) == 1
    assert agencies_repo._best_similar_agency("Verma", rows) is None


# ---- medicine names --------------------------------------------------------
def test_medicine_similar_names():
    assert similar_medicine_names("TELSAR H 40", "TELSARH 40")
    assert similar_medicine_names("Telsar 40 Tablets IP", "Telsar 40")
    assert similar_medicine_names("Pantoprazole 40 Tab", "Pantoprazol 40 Tablet")


def test_medicine_different_names_stay_different():
    assert not similar_medicine_names("Telsar 40", "Telsar 80")
    assert not similar_medicine_names("Provanol Plus 5", "Provanol 5")
    assert not similar_medicine_names("Sinarest New Tablet", "Sinarest New Nasal Spray")
    assert not similar_medicine_names("Dolo 650", "Dolo 500")
    assert not similar_medicine_names("Pantocid DSR", "Pantocid D")


def _prod(pid, name, batch, expiry):
    return {"product_id": pid, "name": name, "batch_number": batch, "expiry_date": expiry, "quantity": 5}


def test_lot_match_uses_similar_name_with_same_batch_and_expiry():
    stock = [_prod(1, "TELSAR H 40 TAB", "B12", "03/27")]
    read = lambda term: stock
    hit = products_service.find_exact_lot_match(1, "Telsarh 40 Tab", "b12", "03/27", read=read)
    assert hit and hit["product_id"] == 1
    assert products_service.find_exact_lot_match(1, "Telsarh 40 Tab", "B13", "03/27", read=read) is None
    assert products_service.find_exact_lot_match(1, "Telsarh 40 Tab", "B12", "04/27", read=read) is None
    assert products_service.find_exact_lot_match(1, "Telsarh 40 Tab", "", "03/27", read=read) is None


# ---- dashboard -------------------------------------------------------------
class _St:
    def __init__(self):
        self.session_state, self.out = {}, []

    def markdown(self, text, **_):
        self.out.append(text)


METRICS = {"total_products": 256, "expiring_soon_count": 0, "expired_count": 0, "low_stock_count": 203,
           "expired_items": [], "expiring_soon_items": [], "low_stock_items": []}


def test_tiles_are_a_two_column_grid_with_four_tiles():
    html = dash._tiles_html(METRICS)
    assert html.count("class='db-tile'") == 4
    assert "256" in html and "203" in html
    assert "grid-template-columns: 1fr 1fr" in dash._CSS


def test_low_stock_is_diary_count_when_switch_off():
    rows = [{"diary_id": 1, "name": "A", "agency_id": None}, {"diary_id": 2, "name": "B", "agency_id": 7}]
    st = _St()
    st.session_state[mode.DIARY_STATE_KEY] = {"store_id": 1, "rows": rows}
    with patch.object(mode, "st", st), patch.object(mode, "alerts_enabled", return_value=False):
        out = dash._with_low_stock_mode(1, METRICS)
    assert out["low_stock_count"] == 2 and out["low_stock_diary"] == rows
    assert METRICS["low_stock_count"] == 203                      # input untouched


def test_low_stock_unchanged_when_switch_on():
    with patch.object(mode, "alerts_enabled", return_value=True):
        assert dash._with_low_stock_mode(1, METRICS) is METRICS


def test_diary_state_key_is_the_diary_screens_key():
    assert mode.DIARY_STATE_KEY == diary_ui._STATE


def test_list_leaves_count_when_order_done():
    rows = [{"diary_id": 1, "name": "A", "agency_id": 7}]
    st = _St()
    st.session_state[mode.DIARY_STATE_KEY] = {"store_id": 1, "rows": rows}
    with patch.object(mode, "st", st), patch.object(mode, "alerts_enabled", return_value=False):
        assert dash._with_low_stock_mode(1, METRICS)["low_stock_count"] == 1
        st.session_state[mode.DIARY_STATE_KEY] = {"store_id": 1, "rows": []}   # what "Order ho gaya" leaves
        assert dash._with_low_stock_mode(1, METRICS)["low_stock_count"] == 0
