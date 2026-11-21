"""
Dashboard screen UI.

Renders the four headline inventory metrics as large, clearly-labeled
cards - consistent with the project's UI rule of large buttons/numbers
and minimal clicks, since the target user often checks this screen in a
few seconds between customers rather than doing a detailed review.

Contains no business logic - it calls modules.dashboard.service for
numbers and renders them. If a metric card's number looks wrong, the
bug is in service.py or repository.py, never in this file.
"""

import html

import streamlit as st

from modules.dashboard.service import get_dashboard_metrics
from modules.alerts import service as alerts_service
from config.alert_theme import render_alert_banner
from core.session import get_current_store_id, get_current_low_stock_minimum
from core.cache_utils import get_cache_epoch
from modules.alerts import mode as alerts_mode


@st.cache_data(show_spinner=False)
def _get_dashboard_metrics_cached(store_id: int, low_stock_minimum: int, _epoch: int) -> dict:
    return get_dashboard_metrics(store_id, low_stock_minimum)

def render_dashboard() -> None:
    """Render the Dashboard screen for the currently logged-in store."""
    st.subheader("📊 Dashboard")

    store_id = get_current_store_id()
    metrics = _get_dashboard_metrics_cached(
        store_id,
        get_current_low_stock_minimum(),
        get_cache_epoch(store_id),
    )

    metrics = _with_low_stock_mode(store_id, metrics)

    if metrics["total_products"] == 0 and metrics["low_stock_count"] == 0:
        st.info(
            "No products yet. Once you add products, your inventory "
            "summary will appear here."
        )
        return

    st.markdown(_CSS, unsafe_allow_html=True)
    _render_metric_cards(metrics)
    _render_expiring_soon_warning(store_id)
    _render_detail_sections(metrics)


def _with_low_stock_mode(store_id: int, metrics: dict) -> dict:
    """When the store does not keep real quantities (Quick Setup "Asli qty
    save" OFF) there are no stock alerts, so Low Stock is the Diary list:
    every medicine written there, with or without an agency. It leaves only
    when its agency order is done ("Order ho gaya") or it is removed from
    the Diary. When the switch is ON the normal low stock numbers stay."""
    try:
        if alerts_mode.alerts_enabled(store_id):
            return metrics
        rows = alerts_mode.diary_rows(store_id)
    except Exception:
        return metrics
    result = dict(metrics)
    result["low_stock_count"] = len(rows)
    result["low_stock_items"] = []
    result["low_stock_diary"] = list(rows)
    return result

@st.cache_data(show_spinner=False)
def _get_alert_counts_cached(store_id: int, _epoch: int) -> dict:
    return alerts_service.get_alert_counts(store_id)

def _render_expiring_soon_warning(store_id: int) -> None:
    """Show a single color-coded warning card for the most urgent
    non-empty expiry bucket, mirroring the existing Low Stock warning
    card's placement and tone.

    Reuses modules.alerts.service.get_alert_counts() for bucket counts,
    and config.alert_theme.render_alert_banner() for the HTML card -
    the same function Expiry Alerts uses for its product rows, so both
    pages are guaranteed to look and feel identical.
    """
    counts = _get_alert_counts_cached(store_id, get_cache_epoch(store_id))
    
    if counts.get(alerts_service.ALERT_TYPE_15_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_15_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 15 days — action needed soon."
    elif counts.get(alerts_service.ALERT_TYPE_30_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_30_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 30 days."
    elif counts.get(alerts_service.ALERT_TYPE_60_DAYS, 0) > 0:
        alert_type = alerts_service.ALERT_TYPE_60_DAYS
        message = f"{counts[alert_type]} product(s) expiring within 60 days."
    else:
        return

    st.markdown(render_alert_banner(message, alert_type), unsafe_allow_html=True)


_CSS = """
<style>
/* four tiles, always two per row (also on a phone) */
.db-tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; margin: 0.2rem 0 0.8rem 0; }
.db-tile { background: #fff; border: 1px solid rgba(49,51,63,0.14); border-radius: 0.8rem;
           padding: 0.7rem 0.8rem; min-width: 0; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.db-ico { width: 2.1rem; height: 2.1rem; border-radius: 50%; display: flex; align-items: center;
          justify-content: center; font-size: 1.1rem; margin-bottom: 0.35rem; }
.db-tl { font-size: 0.8rem; color: #777; line-height: 1.2; }
.db-tv { font-size: 1.7rem; font-weight: 800; line-height: 1.2; }
.db-ts { font-size: 0.72rem; color: #999; min-height: 1rem; }
.db-list { display: flex; flex-direction: column; gap: 0.3rem; margin: 0.2rem 0 0.3rem 0; }
.db-row { background: #fff; border: 1px solid rgba(49,51,63,0.12); border-radius: 0.6rem; padding: 0.4rem 0.7rem; }
.db-n { font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; }
.db-s { font-size: 0.78rem; color: #777; }
</style>
"""

_TILES = (
    # key, label, icon, colour, background, sub-text when > 0
    ("total_products", "Total Products", "💊", "#1565C0", "#E3F2FD", ""),
    ("expiring_soon_count", "Expiring Soon", "⏳", "#F9A825", "#FFF8E1", "30 din ke andar"),
    ("expired_count", "Expired", "⛔", "#D32F2F", "#FFEBEE", "Action needed"),
    ("low_stock_count", "Low Stock", "📉", "#EF6C00", "#FFF3E0", "Reorder soon"),
)


def _tiles_html(metrics: dict) -> str:
    parts = []
    for key, label, icon, color, background, sub in _TILES:
        value = int(metrics.get(key) or 0)
        if key == "total_products":
            sub_text = ""
        elif key == "expiring_soon_count":
            sub_text = sub
        else:
            sub_text = sub if value > 0 else ""
        parts.append(
            f"<div class='db-tile'><div class='db-ico' style='background:{background};color:{color}'>{icon}</div>"
            f"<div class='db-tl'>{label}</div>"
            f"<div class='db-tv' style='color:{color}'>{value}</div>"
            f"<div class='db-ts'>{sub_text}</div></div>"
        )
    return "<div class='db-tiles'>" + "".join(parts) + "</div>"


def _render_metric_cards(metrics: dict) -> None:
    """The four numbers as a 2x2 grid of tiles (two per row on a phone too,
    like Khatabook): Total Products, Expiring Soon, Expired, Low Stock."""
    st.markdown(_tiles_html(metrics), unsafe_allow_html=True)


def _rows_html(items: list, sub_fn) -> str:
    return "<div class='db-list'>" + "".join(
        f"<div class='db-row'><div class='db-n'>{html.escape(str(item.get('name') or ''))}</div>"
        f"<div class='db-s'>{html.escape(sub_fn(item))}</div></div>"
        for item in items
    ) + "</div>"


def _lot_sub(item: dict) -> str:
    return (f"Batch {item.get('batch_number') or '-'} • Exp {item.get('expiry_date') or '-'} • "
            f"Qty {item.get('quantity')} • MRP {item.get('mrp')} • Rate {item.get('rate')}")


def _low_sub(item: dict) -> str:
    return (f"Batch {item.get('batch_number') or '-'} • Qty {item.get('quantity')} / "
            f"Limit {item.get('effective_threshold')} • MRP {item.get('mrp')} • Rate {item.get('rate')}")


def _render_detail_sections(metrics: dict) -> None:
    """Expandable lists for each tile that has items (the screen stays
    simple by default; tap in for specifics)."""
    if metrics["expired_count"] > 0:
        with st.expander(f"🔴 {metrics['expired_count']} Expired Product(s)"):
            _render_item_table(metrics["expired_items"])

    if metrics["expiring_soon_count"] > 0:
        with st.expander(f"🟡 {metrics['expiring_soon_count']} Expiring Soon"):
            _render_item_table(metrics["expiring_soon_items"])

    if metrics["low_stock_count"] > 0:
        with st.expander(f"🟠 {metrics['low_stock_count']} Low Stock Product(s)"):
            if "low_stock_diary" in metrics:
                st.markdown(
                    _rows_html(
                        metrics["low_stock_diary"],
                        lambda row: "Agency ko bhej di" if row.get("agency_id") else "Diary me",
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(_rows_html(metrics["low_stock_items"], _low_sub), unsafe_allow_html=True)


def _render_item_table(items: list) -> None:
    """A thin list of products: name, then batch / expiry / qty / prices."""
    st.markdown(_rows_html(items, _lot_sub), unsafe_allow_html=True)