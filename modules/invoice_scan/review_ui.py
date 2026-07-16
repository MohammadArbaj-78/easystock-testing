"""
Review & Edit UI for invoice OCR results.

Renders an editable table of medicines extracted from an invoice.
Owners can edit any field, delete rows, or add new empty rows.

This module ends BEFORE the database save step:
  - No database imports.
  - No repository calls.
  - No INSERT / UPDATE / commit.
  - All state lives in st.session_state via review_service.

Architecture note: one form per row (not one giant form for the whole
table). This is deliberate — a single form would require the owner to
click Save after every field edit. Per-row inline editing means each
text_input change is reflected immediately in session state on the next
rerun, consistent with the "minimal clicks" UI principle.

Wait — Streamlit widgets outside a form trigger a rerun on every change,
which would re-render and lose focus between keystrokes. The better
approach for a multi-field editable row is to keep the row data in
session state keyed by a stable per-row id and field name, which is
exactly what review_service does. Each medicine is assigned a stable
_row_id when it enters the session (OCR extraction or "Add New
Medicine"), and every st.text_input's key is derived from that _row_id
— not from the row's position in the list. Position-based keys would
get silently reassigned to a different medicine whenever a row above
them is deleted (Streamlit ignores value= once key already exists in
session_state), which is exactly the bug this design avoids.

Mobile note: the table is wrapped in a keyed container purely so a
scoped, mobile-only (max-width: 768px) CSS rule can keep the row as a
single non-wrapping horizontal line with roughly desktop-sized columns
and let the container scroll horizontally, instead of Streamlit's own
default behavior of stacking st.columns() vertically on narrow
screens. The CSS applies to nothing above that breakpoint, so desktop
rendering is unaffected.
"""

import streamlit as st

from modules.invoice_scan import review_service

# Column display config: (field_key, label, width_hint)
# width_hint is a relative integer used to split st.columns() proportionally.
_COLUMNS = [
    ("name",         "Medicine Name",  3),
    ("batch_number", "Batch No",       2),
    ("expiry_date",  "Expiry (MM/YY)", 2),
    ("quantity",     "Qty",            1),
    ("mrp",          "MRP",            1),
    ("rate",         "Rate",           1),
    ("gst_percent",  "GST %",          1),
]


def render_review_ui(ocr_result: dict) -> None:
    """Public entry point called by upload_ui after OCR succeeds.

    Accepts the full ocr_result dict from ocr_service so the call site
    in upload_ui only needs to pass one argument. Extracts what it needs
    and delegates to render_review_section.

    Args:
        ocr_result: The dict returned by extract_medicines_from_file().
            Expected keys: medicines (list), medicine_count (int),
            extraction_time_seconds (float), model (str).
            source_file is read from ocr_result["source_file"] if present,
            or derived from the medicines list otherwise. Since upload_ui
            calls this immediately after OCR with the same uploaded_file
            object, the filename is passed via the "source_file" key that
            upload_ui adds before calling this function.
    """
    medicines = ocr_result.get("medicines", [])
    source_filename = ocr_result.get("source_file", "invoice")
    render_review_section(source_filename, medicines)


def render_review_section(source_filename: str, medicines: list) -> None:
    """Render the editable review table from the current session state.

    Called by upload_ui after the session has already been initialised
    by _render_ocr_section. Does not initialise the session itself —
    that is always done upstream, keyed by SHA-256 file hash, before
    this function is reached.

    Args:
        source_filename: Unused — kept in signature for compatibility
            with render_review_ui which passes it.
        medicines: Unused — kept for the same reason. Actual medicines
            are always read from session state via review_service.
    """
    st.markdown("**✏️ Review & Edit Medicines**")
    st.caption(
        "Check each row carefully. Edit any incorrect values directly. "
        "Delete rows that don't belong. Add rows if any medicine is missing."
    )
    st.info("✅ Please verify Batch Number and Expiry before saving.")

    _render_table()
    _render_global_actions()
    _render_summary()


def _render_table() -> None:
    """Render the editable medicine table: one row per medicine.

    Wrapped in a keyed container purely so the mobile-only CSS in
    _render_table_scroll_css can target this table specifically. The
    container itself adds no visible styling (no border/padding), so
    on its own it changes nothing — see _render_table_scroll_css for
    the actual (mobile-only) behavior change.
    """
    medicines = review_service.get_medicines()

    if not medicines:
        st.info("No medicines in the list. Use 'Add New Medicine' below to add one.")
        return

    _render_table_scroll_css()

    with st.container(key="review_table_scroll"):
        _render_table_header()

        errors_by_row = review_service.validate_all_medicines()
        for idx, medicine in enumerate(medicines):
            _render_medicine_row(idx, medicine, errors_by_row.get(idx, []))


def _render_table_scroll_css() -> None:
    """Inject mobile-only CSS so the review table scrolls horizontally
    instead of Streamlit's default of stacking st.columns() vertically
    on narrow screens.

    Everything here is inside `@media (max-width: 768px)`, so above
    that viewport width none of it applies at all — desktop rendering
    is pixel-identical to having no CSS block here whatsoever.

    Two things have to happen together for a usable mobile row, and
    both are needed — either alone reproduces a broken layout:
      1. `flex-wrap: nowrap` on the row itself, to override Streamlit's
         own built-in mobile rule that switches st.columns() to
         `flex-direction: column` (stacking) below its breakpoint.
      2. A fixed pixel width plus `flex-shrink: 0; flex-grow: 0` on
         each individual column, so columns can't shrink to illegible
         widths (the original bug) NOR stretch to fill the now-wide,
         non-wrapping row (the v2.2.3 bug — nowrap alone, without
         fixing column width, would still let text_input's 100%-width
         default blow each column up to the full row width).
    The container then scrolls horizontally because its content (the
    row, now wider than the viewport) no longer fits or wraps.

    Column widths approximate each column's desktop proportion (same
    relative weights as _COLUMNS) as fixed pixel values, so on mobile
    inputs are close to their normal desktop size — not shrunk, not
    stretched.
    """
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
            .st-key-review_table_scroll {
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            .st-key-review_table_scroll [data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                width: max-content !important;
            }
            .st-key-review_table_scroll [data-testid="stColumn"] {
                flex: none !important;
                min-width: 0 !important;
            }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(1) { width: 200px !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(2) { width: 140px !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(3) { width: 140px !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(4) { width: 70px  !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(5) { width: 70px  !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(6) { width: 70px  !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(7) { width: 70px  !important; }
            .st-key-review_table_scroll [data-testid="stColumn"]:nth-child(8) { width: 55px  !important; }
            .easystock-mobile-scroll-hint {
                display: block;
                font-size: 0.8rem;
                color: #6b7280;
                margin-bottom: 0.25rem;
            }
        }
        .easystock-mobile-scroll-hint {
            display: none;
        }
        </style>
        <div class="easystock-mobile-scroll-hint">↔️ Scroll sideways to see every column</div>
        """,
        unsafe_allow_html=True,
    )


def _render_table_header() -> None:
    """Render the column header row."""
    widths = [col[2] for col in _COLUMNS] + [1]  # +1 for Delete column
    cols = st.columns(widths)
    for col_widget, (_, label, _) in zip(cols[:-1], _COLUMNS):
        col_widget.markdown(f"**{label}**")
    cols[-1].markdown("**Action**")
    st.divider()


def _render_medicine_row(idx: int, medicine: dict, row_errors: list) -> None:
    """Render one editable medicine row.

    Each text_input is keyed by (row's stable _row_id, field_key) — NOT
    by the row's position — so Streamlit always maps a given widget key
    to the same medicine for that medicine's entire lifetime in the
    session, even as other rows are added or deleted around it. The
    write-back below keeps session state's medicines list current
    immediately, so the data is always up to date even without a Save
    button.

    Args:
        idx:        Row's current position (used only to call
                     update_medicine/delete_medicine, which operate on
                     list position — not used for widget identity).
        medicine:   The current field values for this row.
        row_errors: Validation errors for this row (shown below the row).
    """
    row_id = medicine.get("_row_id", idx)

    widths = [col[2] for col in _COLUMNS] + [1]
    cols = st.columns(widths)

    for col_widget, (field_key, label, _) in zip(cols[:-1], _COLUMNS):
        widget_key = f"review_row_{row_id}_{field_key}"
        current_value = medicine.get(field_key, "")

        new_value = col_widget.text_input(
            label=label,
            value=current_value,
            key=widget_key,
            label_visibility="collapsed",
        )
        # Write back immediately so session state always reflects the
        # current widget value. This is safe because text_input with an
        # explicit key is controlled by session state — Streamlit will not
        # re-initialise the widget on the next rerun as long as the key
        # exists in session state.
        if new_value != current_value:
            review_service.update_medicine(idx, field_key, new_value)

    # Delete button — keyed by the row's stable id, not its position.
    delete_key = f"delete_row_{row_id}"
    if cols[-1].button("🗑️", key=delete_key, help="Delete this row"):
        review_service.delete_medicine(idx)
        st.rerun()

    if row_errors:
        for err in row_errors:
            st.error(f"Row {idx + 1}: {err}")


def _render_global_actions() -> None:
    """Render the 'Add New Medicine' button below the table."""
    st.write("")
    if st.button("➕ Add New Medicine", key="add_new_medicine_row"):
        review_service.add_empty_medicine()
        st.rerun()


def _render_summary() -> None:
    """Show live medicine count, validation summary, Save and Clear buttons."""
    from core.session import get_current_store_id

    medicines = review_service.get_medicines()
    total = len(medicines)

    st.divider()
    st.metric("Total Medicines", total)

    errors_by_row = review_service.validate_all_medicines()
    if errors_by_row:
        error_count = sum(len(v) for v in errors_by_row.values())
        st.warning(
            f"⚠️ {error_count} validation issue(s) across "
            f"{len(errors_by_row)} row(s). Please fix the highlighted "
            "fields before saving."
        )

    st.write("")
    col_save, col_clear = st.columns([2, 1])

    with col_save:
        save_clicked = st.button(
            "💾 Save Medicines",
            key="save_medicines_btn",
            use_container_width=True,
            type="primary",
            disabled=(total == 0),
        )

    with col_clear:
        clear_clicked = st.button(
            "🗑 Clear Review",
            key="clear_review_btn",
            use_container_width=True,
        )

    # --- Clear ---
    if clear_clicked:
        review_service.clear_session()
        st.rerun()

    # --- Save ---
    if save_clicked:
        if errors_by_row:
            st.error(
                "Please fix all validation errors before saving. "
                "Check the highlighted rows above."
            )
            return

        store_id = get_current_store_id()
        with st.spinner("Saving medicines to inventory…"):
            result = review_service.save_invoice_medicines(store_id)

        saved = result["saved"]
        skipped = result["skipped"]

        if saved > 0:
            st.success(f"✅ {saved} medicine(s) saved successfully to inventory.")

        if skipped:
            for item in skipped:
                st.error(
                    f"Row {item['row']} — {item['name']}: {item['error']}"
                )
