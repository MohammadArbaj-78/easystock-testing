"""
PDF records (download) for Udhar Khata, Low Stock Diary and Agencies.

Why: a store owner who stops writing the paper register must still be able to
keep his own copy of everything. One tap on a small button gives a clean PDF.

Nothing here talks to the database or to Streamlit's data: every build_*
function receives plain lists / dicts and returns the PDF as bytes, so it is
easy to test and a problem here can never touch the screens' own data.
The PDF is made only when the button is pressed (Streamlit calls the function
then), so opening a screen costs nothing extra.

Needs the `reportlab` package (pure Python, free); it is imported only when a
PDF is really made, so the app itself starts even if the package is missing.
Text uses the PDF's built-in Helvetica font: Latin letters and digits print
fine, other scripts (for example Hindi letters) print as "?", and the rupee
sign is written "Rs.".
"""

import io
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

_IST = timezone(timedelta(hours=5, minutes=30))

_TEAL = "#1A7A6E"
_INK = "#1F2933"
_MUTED = "#6B7280"
_LINE = "#D9DEE3"
_ZEBRA = "#F5F8F8"
_RED = "#C62828"
_GREEN = "#2E7D32"


# ------------------------------------------------------------------ helpers

def now_ist() -> datetime:
    return datetime.now(_IST)


def money(amount) -> str:
    """Rs. 1,234.50 - always two decimals in a table so the columns line up."""
    return f"Rs. {float(amount or 0):,.2f}"


def clean_text(value) -> str:
    """Text the built-in PDF font can print (other characters become "?")."""
    text = "" if value is None else str(value)
    return text.encode("cp1252", "replace").decode("cp1252")


def _p(value) -> str:
    """Safe text for a Paragraph (escaped)."""
    return escape(clean_text(value))


def file_name(prefix: str) -> str:
    return f"EasyStock_{prefix}_{now_ist().strftime('%Y-%m-%d')}.pdf"


def _load():
    """The reportlab pieces, imported only now."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as canvas_module
    from reportlab.platypus import (
        BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate,
        Paragraph, Spacer, Table, TableStyle,
    )
    return {
        "colors": colors, "TA_RIGHT": TA_RIGHT, "A4": A4, "ParagraphStyle": ParagraphStyle, "mm": mm,
        "canvas": canvas_module, "BaseDocTemplate": BaseDocTemplate, "CondPageBreak": CondPageBreak,
        "Frame": Frame, "KeepTogether": KeepTogether, "PageTemplate": PageTemplate,
        "Paragraph": Paragraph, "Spacer": Spacer, "Table": Table, "TableStyle": TableStyle,
    }


class _Kit:
    """Styles and small builders shared by the three reports."""

    def __init__(self, store_name: str, title: str):
        self.rl = _load()
        rl = self.rl
        self.colors = rl["colors"]
        self.mm = rl["mm"]
        self.store_name = clean_text(store_name) or "My Store"
        self.title = clean_text(title)
        style = rl["ParagraphStyle"]
        ink = self.colors.HexColor(_INK)
        self.cell = style("cell", fontName="Helvetica", fontSize=9, leading=11.5, textColor=ink)
        self.cell_r = style("cell_r", parent=self.cell, alignment=rl["TA_RIGHT"])
        self.cell_b = style("cell_b", parent=self.cell, fontName="Helvetica-Bold")
        self.cell_br = style("cell_br", parent=self.cell_b, alignment=rl["TA_RIGHT"])
        self.head = style("head", fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, textColor=self.colors.white)
        self.head_r = style("head_r", parent=self.head, alignment=rl["TA_RIGHT"])
        self.h1 = style("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=ink)
        self.h2 = style("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=self.colors.HexColor(_TEAL),
                        spaceBefore=10, spaceAfter=4)
        self.sub = style("sub", fontName="Helvetica", fontSize=8.5, leading=11, textColor=self.colors.HexColor(_MUTED))
        self.note = style("note", parent=self.sub, fontSize=9, leading=12)

    # -- small pieces
    def para(self, text, style=None):
        return self.rl["Paragraph"](_p(text), style or self.cell)

    def para_colored(self, text, color, style=None):
        return self.rl["Paragraph"](f'<font color="{color}">{_p(text)}</font>', style or self.cell_br)

    def spacer(self, height_mm: float):
        return self.rl["Spacer"](1, height_mm * self.mm)

    def width(self):
        return self.rl["A4"][0] - 30 * self.mm

    def summary_strip(self, items: list):
        """Big numbers in a row: [(label, text, color or None), ...]."""
        rl, colors = self.rl, self.colors
        label_style = self.rl["ParagraphStyle"]("sl", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor(_MUTED))
        cells = []
        for label, value, color in items:
            big = self.rl["ParagraphStyle"](
                "sv", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=colors.HexColor(color or _INK),
            )
            cells.append([rl["Paragraph"](_p(label), label_style), rl["Paragraph"](_p(value), big)])
        table = rl["Table"]([[cell for cell in cells]], colWidths=[self.width() / len(cells)] * len(cells))
        table.setStyle(rl["TableStyle"]([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(_LINE)),
            ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor(_LINE)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFC")),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    def grid(self, header: list, rows: list, widths: list, total_row: list = None, align_right: set = ()):
        """A clean table: teal header (repeated on every page), light zebra
        rows, thin lines. `rows` hold ready Paragraphs or plain text."""
        rl, colors = self.rl, self.colors

        def cell(value, column, head=False, bold=False):
            if hasattr(value, "wrap"):
                return value
            if head:
                return self.para(value, self.head_r if column in align_right else self.head)
            right = column in align_right
            style = (self.cell_br if right else self.cell_b) if bold else (self.cell_r if right else self.cell)
            return self.para(value, style)

        data = [[cell(v, i, head=True) for i, v in enumerate(header)]]
        data += [[cell(v, i) for i, v in enumerate(row)] for row in rows]
        if total_row:
            data.append([cell(v, i, bold=True) for i, v in enumerate(total_row)])
        table = rl["Table"](data, colWidths=widths, repeatRows=1)
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_TEAL)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(_LINE)),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(_LINE)),
        ]
        last_body = len(rows)
        for index in range(1, last_body + 1):
            if index % 2 == 0:
                commands.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor(_ZEBRA)))
        if total_row:
            commands += [
                ("BACKGROUND", (0, last_body + 1), (-1, last_body + 1), colors.HexColor("#E7F1EF")),
                ("LINEABOVE", (0, last_body + 1), (-1, last_body + 1), 0.8, colors.HexColor(_TEAL)),
            ]
        table.setStyle(rl["TableStyle"](commands))
        return table

    # -- the whole document
    def build(self, story: list) -> bytes:
        rl, colors, mm = self.rl, self.colors, self.mm
        buffer = io.BytesIO()
        stamp = now_ist().strftime("%d %b %Y, %I:%M %p")
        store, title = self.store_name, self.title

        class _Numbered(rl["canvas"].Canvas):
            """A canvas that knows the page count ("Page 2 of 5")."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._saved = []

            def showPage(self):
                self._saved.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total = len(self._saved)
                for state in self._saved:
                    self.__dict__.update(state)
                    self._decorate(total)
                    super().showPage()
                super().save()

            def _decorate(self, total):
                width, height = rl["A4"]
                self.setStrokeColor(colors.HexColor(_LINE))
                self.setLineWidth(0.6)
                self.line(15 * mm, height - 17 * mm, width - 15 * mm, height - 17 * mm)
                self.setFillColor(colors.HexColor(_TEAL))
                self.setFont("Helvetica-Bold", 10)
                self.drawString(15 * mm, height - 13 * mm, store[:60])
                self.setFillColor(colors.HexColor(_MUTED))
                self.setFont("Helvetica", 8.5)
                self.drawRightString(width - 15 * mm, height - 13 * mm, title)
                self.line(15 * mm, 14 * mm, width - 15 * mm, 14 * mm)
                self.drawString(15 * mm, 9.5 * mm, f"Made with EasyStock  |  {stamp}")
                self.drawRightString(width - 15 * mm, 9.5 * mm, f"Page {self._pageNumber} of {total}")

        document = rl["BaseDocTemplate"](
            buffer, pagesize=rl["A4"], leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=23 * mm, bottomMargin=20 * mm, title=f"{store} - {title}", author="EasyStock",
        )
        frame = rl["Frame"](document.leftMargin, document.bottomMargin, document.width, document.height, id="f",
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        document.addPageTemplates([rl["PageTemplate"](id="p", frames=[frame])])
        document.build(story, canvasmaker=_Numbered)
        return buffer.getvalue()


def _title_block(kit: _Kit, heading: str, line: str) -> list:
    return [kit.para(heading, kit.h1), kit.para(line, kit.sub), kit.spacer(3)]


def _date_text(value) -> str:
    """A date (or a timestamp text) as 23 Nov 2026; anything else as it is."""
    text = str(value or "").strip()
    if not text:
        return "-"
    for size, pattern in ((10, "%Y-%m-%d"), (19, "%Y-%m-%d %H:%M:%S"), (19, "%Y-%m-%dT%H:%M:%S")):
        try:
            return datetime.strptime(text[:size], pattern).strftime("%d %b %Y")
        except ValueError:
            continue
    return text


# -------------------------------------------------------------- Udhar Khata

def build_udhar_pdf(store_name: str, customers: list, entries: list) -> bytes:
    """customers: [{"customer_id", "name", "mobile", "balance", ...}];
    entries: [{"customer_id", "kind" gave|got, "amount", "note", "entry_date", "entry_id"}]."""
    kit = _Kit(store_name, "Udhar Khata record")
    by_customer = {}
    for entry in entries:
        by_customer.setdefault(entry["customer_id"], []).append(entry)

    def totals(customer_id):
        gave = sum(e["amount"] for e in by_customer.get(customer_id, []) if e["kind"] == "gave")
        got = sum(e["amount"] for e in by_customer.get(customer_id, []) if e["kind"] == "got")
        return round(gave, 2), round(got, 2)

    ordered = sorted(customers, key=lambda row: (-float(row.get("balance") or 0), str(row["name"]).lower()))
    story = _title_block(kit, "Udhar Khata - Customer record", f"{kit.store_name}  |  {now_ist().strftime('%d %b %Y')}")

    total_gave = total_got = 0.0
    rows = []
    for number, customer in enumerate(ordered, 1):
        gave, got = totals(customer["customer_id"])
        total_gave += gave
        total_got += got
        balance = round(float(customer.get("balance") or 0), 2)
        rows.append([
            str(number), kit.para(customer["name"], kit.cell_b), customer.get("mobile") or "-",
            money(gave), money(got), _balance_cell(kit, balance), _date_text(customer.get("last_entry_date")),
        ])
    to_receive = round(sum(max(float(c.get("balance") or 0), 0) for c in ordered), 2)
    owing = sum(1 for c in ordered if float(c.get("balance") or 0) > 0)

    story.append(kit.summary_strip([
        ("Customers", str(len(ordered)), None),
        ("Total udhar diya", money(total_gave), None),
        ("Total jama (paise mile)", money(total_got), _GREEN),
        (f"Total baki ({owing} customer)", money(to_receive), _RED),
    ]))
    story.append(kit.spacer(4))
    if not ordered:
        story.append(kit.para("Abhi koi customer nahi hai.", kit.note))
        return kit.build(story)

    mm = kit.mm
    widths = [9 * mm, 47 * mm, 24 * mm, 24 * mm, 24 * mm, 28 * mm, 24 * mm]
    story.append(kit.grid(
        ["#", "Customer", "Mobile", "Udhar diya", "Jama", "Baki", "Last entry"], rows, widths,
        total_row=["", "Total", "", money(total_gave), money(total_got), money(to_receive), ""],
        align_right={3, 4, 5},
    ))

    with_entries = [c for c in ordered if by_customer.get(c["customer_id"])]
    if with_entries:
        story.append(kit.rl["CondPageBreak"](60 * mm))
        story.append(kit.para("Customer-wise entries", kit.h2))
    for customer in with_entries:
        story.append(kit.rl["CondPageBreak"](38 * mm))
        entries_sorted = sorted(by_customer[customer["customer_id"]], key=lambda e: (str(e.get("entry_date") or ""), e.get("entry_id") or 0))
        running = 0.0
        body = []
        for entry in entries_sorted:
            running = round(running + (entry["amount"] if entry["kind"] == "gave" else -entry["amount"]), 2)
            gave_text = money(entry["amount"]) if entry["kind"] == "gave" else ""
            got_text = money(entry["amount"]) if entry["kind"] == "got" else ""
            body.append([_date_text(entry.get("entry_date")), kit.para(entry.get("note") or "", kit.cell), gave_text, got_text, money(running)])
        balance = round(float(customer.get("balance") or 0), 2)
        gave, got = totals(customer["customer_id"])
        story.append(kit.para(f"{customer['name']}  -  {customer.get('mobile') or ''}", kit.cell_b))
        story.append(kit.spacer(1.5))
        story.append(kit.grid(
            ["Date", "Note", "Udhar diya", "Jama", "Balance"], body,
            [24 * mm, 66 * mm, 29 * mm, 29 * mm, 32 * mm],
            total_row=["Total", "", money(gave), money(got), money(balance)], align_right={2, 3, 4},
        ))
        story.append(kit.spacer(4))
    return kit.build(story)


def _balance_cell(kit: _Kit, balance: float):
    if balance > 0:
        return kit.para_colored(money(balance), _RED)
    if balance < 0:
        return kit.para_colored(money(-balance) + " adv.", _GREEN)
    return kit.para_colored("Rs. 0.00", _MUTED)


# ------------------------------------------------------------ Low Stock Diary

def build_diary_pdf(store_name: str, plain_rows: list, by_agency: list) -> bytes:
    """plain_rows: [{"name", "qty"}] (no agency chosen yet);
    by_agency: [(agency_name, [{"name", "qty"}, ...]), ...]."""
    kit = _Kit(store_name, "Low Stock Diary")
    mm = kit.mm
    total = len(plain_rows) + sum(len(rows) for _, rows in by_agency)
    story = _title_block(kit, "Low Stock Diary - Mangwani list", f"{kit.store_name}  |  {now_ist().strftime('%d %b %Y')}")
    story.append(kit.summary_strip([
        ("Total dawai", str(total), None),
        ("Diary me (agency nahi chuni)", str(len(plain_rows)), None),
        ("Agency ki list me", str(total - len(plain_rows)), None),
    ]))
    if not total:
        story += [kit.spacer(4), kit.para("Diary abhi khali hai.", kit.note)]
        return kit.build(story)

    def section(heading, rows):
        body = [[str(number), kit.para(row["name"], kit.cell_b), str(int(row["qty"])) if row.get("qty") else ""]
                for number, row in enumerate(rows, 1)]
        table = kit.grid(["#", "Medicine", "Qty"], body, [10 * mm, 140 * mm, 30 * mm], align_right={2})
        return [kit.rl["CondPageBreak"](35 * mm), kit.para(heading, kit.h2), table]

    if plain_rows:
        story += section(f"Diary list  ({len(plain_rows)} dawai)", plain_rows)
    for agency_name, rows in by_agency:
        if rows:
            story += section(f"{clean_text(agency_name)}  ({len(rows)} dawai)", rows)
    return kit.build(story)


# ------------------------------------------------------------------- Agencies

def build_agencies_pdf(store_name: str, agencies: list, details: dict) -> bytes:
    """agencies: [{"agency_id", "agency_name", "balance", ...}];
    details: {agency_id: {"bills": [...], "payments": [...], "total_billed", "total_paid", "balance"}}."""
    kit = _Kit(store_name, "Agency ledger")
    mm = kit.mm
    story = _title_block(kit, "Agencies - Bills aur hisab (ledger)", f"{kit.store_name}  |  {now_ist().strftime('%d %b %Y')}")

    def figures(agency):
        detail = details.get(agency["agency_id"]) or {}
        billed = round(sum(float(b.get("grand_total") or 0) for b in detail.get("bills", [])), 2)
        paid = round(sum(float(p.get("amount") or 0) for p in detail.get("payments", [])), 2)
        return billed, paid, round(billed - paid, 2)

    ordered = sorted(agencies, key=lambda a: str(a["agency_name"]).lower())
    summary_rows, all_billed, all_paid = [], 0.0, 0.0
    for number, agency in enumerate(ordered, 1):
        billed, paid, balance = figures(agency)
        all_billed += billed
        all_paid += paid
        summary_rows.append([str(number), kit.para(agency["agency_name"], kit.cell_b), money(billed), money(paid), _balance_cell(kit, balance)])
    outstanding = round(all_billed - all_paid, 2)
    story.append(kit.summary_strip([
        ("Agencies", str(len(ordered)), None),
        ("Total bills", money(all_billed), None),
        ("Total paid", money(all_paid), _GREEN),
        ("Total baki", money(outstanding), _RED if outstanding > 0 else None),
    ]))
    story.append(kit.spacer(4))
    if not ordered:
        story.append(kit.para("Abhi koi agency nahi hai.", kit.note))
        return kit.build(story)

    story.append(kit.grid(
        ["#", "Agency", "Total bills", "Total paid", "Baki"], summary_rows,
        [10 * mm, 74 * mm, 32 * mm, 32 * mm, 32 * mm],
        total_row=["", "Total", money(all_billed), money(all_paid), money(outstanding)], align_right={2, 3, 4},
    ))

    story.append(kit.rl["CondPageBreak"](60 * mm))
    story.append(kit.para("Agency-wise ledger", kit.h2))
    for agency in ordered:
        detail = details.get(agency["agency_id"]) or {}
        events = []
        for bill in detail.get("bills", []):
            events.append((str(bill.get("created_at") or ""), "bill", bill))
        for payment in detail.get("payments", []):
            events.append((str(payment.get("created_at") or ""), "payment", payment))
        if not events:
            continue
        events.sort(key=lambda item: item[0])               # the order they were saved in
        running, body = 0.0, []
        for _, kind, row in events:
            if kind == "bill":
                amount = float(row.get("grand_total") or 0)
                running = round(running + amount, 2)
                body.append([_date_text(row.get("invoice_date") or row.get("created_at")), "Bill", money(amount), "", money(running)])
            else:
                amount = float(row.get("amount") or 0)
                running = round(running - amount, 2)
                body.append([_date_text(row.get("paid_on") or row.get("created_at")), "Payment", "", money(amount), money(running)])
        billed, paid, balance = figures(agency)
        story.append(kit.rl["CondPageBreak"](38 * mm))
        story.append(kit.para(agency["agency_name"], kit.cell_b))
        story.append(kit.spacer(1.5))
        story.append(kit.grid(
            ["Date", "Particulars", "Bill amount", "Paid", "Balance"], body,
            [30 * mm, 38 * mm, 38 * mm, 38 * mm, 36 * mm],
            total_row=["Total", "", money(billed), money(paid), money(balance)], align_right={2, 3, 4},
        ))
        story.append(kit.spacer(4))
    return kit.build(story)


# ------------------------------------------------------------------ the button

_BUTTON_CSS = """
<style>
/* the small "download PDF" button: quiet, right aligned, same on every screen */
div[class*="st-key-pdfbtn_"] { display: flex; justify-content: flex-end; margin: 0 0 0.3rem 0; }
div[class*="st-key-pdfbtn_"] button, div[class*="st-key-pdfbtn_"] a {
    min-height: 2rem; padding: 0.1rem 0.8rem; font-size: 0.82rem; font-weight: 600;
    border-radius: 999px; background: #fff; border: 1px solid rgba(49,51,63,0.2); color: #1A7A6E;
}
</style>
"""


def pdf_button(label: str, build, name_prefix: str, key: str) -> None:
    """A small "download" button. `build` is a function without arguments that
    returns the PDF bytes; it runs only when the button is pressed (in another
    thread, so it must not use st.session_state) and the screen is not redrawn.
    If it fails, the file is a one-page PDF that says so - the screen is never
    broken by the button."""
    import streamlit as st

    def make() -> bytes:
        try:
            return build()
        except ImportError:
            message = "PDF banane ke liye `reportlab` package install hona chahiye (requirements.txt me hai)."
        except Exception as error:                 # never let the button break anything
            message = f"PDF nahi ban payi: {error}"
        return _error_pdf(message)

    try:
        st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
        with st.container(key=f"pdfbtn_{key}"):
            st.download_button(
                label, data=make, file_name=file_name(name_prefix), mime="application/pdf",
                key=f"pdfdl_{key}", on_click="ignore", icon=":material/download:",
            )
    except Exception:
        # An old Streamlit without these options: the screen simply has no button.
        pass


def _error_pdf(message: str) -> bytes:
    """A tiny valid PDF with one line of text (no reportlab needed)."""
    text = clean_text(message).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:150]
    stream = f"BT /F1 12 Tf 40 780 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, start)
    return out
