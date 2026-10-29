"""Billing service - the store's seal/sign image and the printable bill.

No Streamlit, no SQL. The bill is built as plain HTML (inline styles only,
so the same text works inside the page as a preview and inside the print
page). All amounts come from modules/sales/bill_service.py.
"""

import base64
import html
import io
from datetime import datetime

from core.exceptions import ValidationError
from modules.billing import repository as billing_repository
from modules.sales import bill_service

MAX_SEAL_UPLOAD_BYTES = 3 * 1024 * 1024
_SEAL_MAX_SIZE = (500, 250)


# ---------------------------------------------------------------------------
# Seal / sign image
# ---------------------------------------------------------------------------

def get_seal_sign(store_id: int):
    """The store's seal/sign as a data-URI string, or None if not uploaded."""
    return billing_repository.get_seal_sign(store_id)


def save_seal_sign(store_id: int, file_bytes: bytes) -> None:
    """Validate, shrink and save an uploaded seal/sign image. It stays until
    the store uploads another one.

    Raises:
        ValidationError: Empty / too big file, or not a readable image.
    """
    from PIL import Image

    if not file_bytes:
        raise ValidationError("Image file khaali hai.")
    if len(file_bytes) > MAX_SEAL_UPLOAD_BYTES:
        raise ValidationError("Image 3 MB se chhoti honi chahiye.")
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
        image = image.convert("RGBA")
    except Exception:
        raise ValidationError("Ye image file padhi nahi ja saki. PNG ya JPG upload karo.")

    image.thumbnail(_SEAL_MAX_SIZE)            # small enough to keep in the database
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    billing_repository.save_seal_sign(store_id, f"data:image/png;base64,{encoded}")


# ---------------------------------------------------------------------------
# The bill
# ---------------------------------------------------------------------------

def _now_text() -> str:
    """Current date and time for the bill, in Indian time where the system
    knows it (a cloud server often runs in UTC)."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.now()
    return now.strftime("%d %b %Y, %I:%M %p")


def _mrp_cell(line: dict) -> str:
    text = bill_service.line_mrp_text(line)
    return html.escape(text) if text else "—"


def _amount_cell(line: dict) -> str:
    amount = bill_service.line_amount(line)
    return html.escape(bill_service.money(amount)) if amount > 0 else "—"


def build_bill_body_html(store_name: str, lines: list, customer_name: str = "", seal_uri=None, when: str = None) -> str:
    """The bill itself (no <html>/<body>), on ONE line of text with inline
    styles only - safe to show in the page with st.markdown and to print."""
    cell = "padding:6px 4px;border-bottom:1px solid #ccc;"
    rows = []
    for number, line in enumerate(lines, start=1):
        rows.append(
            "<tr>"
            f"<td style='{cell}'>{number}</td>"
            f"<td style='{cell}'>{html.escape(line['name'])}</td>"
            f"<td style='{cell}text-align:center;'>{html.escape(bill_service.quantity_text(line))}</td>"
            f"<td style='{cell}text-align:right;'>{_mrp_cell(line)}</td>"
            f"<td style='{cell}text-align:right;'>{_amount_cell(line)}</td>"
            "</tr>"
        )
    total = bill_service.bill_total(lines)
    customer = (customer_name or "").strip()
    customer_html = (
        f"<div style='margin:4px 0;'>Customer: <b>{html.escape(customer)}</b></div>" if customer else ""
    )
    seal_html = (
        f"<img src='{seal_uri}' style='max-width:220px;max-height:110px;' alt='seal and sign'>"
        if seal_uri else ""
    )
    head = "padding:6px 4px;border-bottom:2px solid #000;"
    return (
        "<div style='background:#fff;color:#000;padding:14px;border:1px solid #bbb;"
        "font-family:Arial,Helvetica,sans-serif;font-size:14px;'>"
        f"<div style='text-align:center;font-size:20px;font-weight:700;'>{html.escape(store_name or '')}</div>"
        f"<div style='text-align:center;font-size:12px;margin-bottom:8px;'>{html.escape(when or _now_text())}</div>"
        f"{customer_html}"
        "<table style='width:100%;border-collapse:collapse;margin-top:6px;'>"
        "<thead><tr>"
        f"<th style='{head}text-align:left;'>#</th>"
        f"<th style='{head}text-align:left;'>Medicine</th>"
        f"<th style='{head}text-align:center;'>Qty</th>"
        f"<th style='{head}text-align:right;'>MRP</th>"
        f"<th style='{head}text-align:right;'>Amount</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        f"<div style='text-align:right;font-size:18px;font-weight:700;margin-top:10px;'>"
        f"Total: {html.escape(bill_service.money(total))}</div>"
        f"<div style='text-align:right;margin-top:24px;min-height:30px;'>{seal_html}</div>"
        "</div>"
    )


def build_print_document(store_name: str, lines: list, customer_name: str = "", seal_uri=None) -> str:
    """A complete page that opens the browser's print window by itself."""
    body = build_bill_body_html(store_name, lines, customer_name, seal_uri)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Bill</title>"
        "<style>@page{margin:8mm;}body{margin:0;background:#fff;}</style></head><body>"
        f"{body}"
        "<script>window.onload=function(){setTimeout(function(){"
        "try{window.focus();window.print();}catch(e){}},300);};</script>"
        "</body></html>"
    )