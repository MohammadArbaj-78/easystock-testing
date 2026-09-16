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
from core.cache_utils import bump_cache_epoch

# Human-readable labels for the advisory (non-blocking) validation flags
# attached by modules/invoice_scan/validation.py. Purely cosmetic - the
# flag codes themselves are the source of truth.
_FLAG_LABELS = {
    "MRP_LESS_THAN_RATE": "Rate is higher than MRP.",
    "GST_OUTLIER": "GST % looks unusual.",
    "EMPTY_BATCH": "Batch number is empty.",
    "EMPTY_EXPIRY": "Expiry is empty.",
    "EMPTY_MRP": "MRP is empty.",
    "EMPTY_RATE": "Rate is empty.",
    "DUPLICATE_BATCH": "Duplicate batch number — please check.",
    # Phase 7: presentation-only friendly label for Phase 6's new
    # advisory flag - the flag itself and its trigger condition
    # (validation.py) are unchanged, this only replaces the raw code
    # "INVALID_EXPIRY_FORMAT" with readable text when shown.
    "INVALID_EXPIRY_FORMAT": "Invalid expiry format — please verify.",
}

# Warning flags whose meaning is fully covered by a RED "required" error
# once that same field is blank. RED always wins: when both would fire
# for the same field, only RED is shown, never a duplicate YELLOW for
# the identical missing-field issue.
_WARNING_FIELD_OVERLAP = {
    "EMPTY_BATCH": "batch_number",
    "EMPTY_EXPIRY": "expiry_date",
    "EMPTY_MRP": "mrp",
    "EMPTY_RATE": "rate",
    # Phase 7: the existing blocking "Enter a valid expiry date" error
    # (review_service.py, unchanged) already explains an invalid-format
    # expiry - suppress the duplicate-looking YELLOW for the identical
    # issue on the same field, same RED-wins rule as the EMPTY_* flags
    # above. Presentation only - validation.py's flag itself is unchanged.
    "INVALID_EXPIRY_FORMAT": "expiry_date",
}

# Display-only mapping from a review_service.validate_medicine() error
# message to the field it's about, plus a human "Expected" description.
# This does NOT change any validation logic - review_service.py's
# validate_medicine()/validate_all_medicines() are unmodified this
# sprint, still return the exact same list-of-strings they always have
# (locked in by tests/test_review_service.py). This table only lets the
# UI figure out, after the fact, which column to highlight and what to
# show under "Expected:" for a message it already produced.
_BLOCKING_FIELD_INFO = [
    ("Medicine name is required", "name", "A medicine name."),
    ("Batch number is required", "batch_number", "A batch number."),
    ("Expiry is required", "expiry_date", "MM/YY, MM/YYYY, or Month-YYYY (e.g. 03/28)."),
    ("Enter a valid expiry date", "expiry_date", "MM/YY, MM/YYYY, or Month-YYYY (e.g. 03/28)."),
    ("Quantity is required", "quantity", "A numeric quantity (required)."),
    ("Enter a valid quantity", "quantity", "Numeric value only."),
    ("MRP is required", "mrp", "A numeric MRP value (required)."),
    ("Enter a valid MRP", "mrp", "Numeric value only."),
    ("Rate is required", "rate", "A numeric Rate value (required)."),
    ("Enter a valid rate", "rate", "Numeric value only."),
    ("GST is required", "gst_percent", "A numeric GST % value (required)."),
    ("Enter a valid GST value", "gst_percent", "Numeric value only."),
]

# Column display config: (field_key, label, width_hint)
# width_hint is a relative integer used to split st.columns() proportionally.
_COLUMNS = [
    ("name",         "Medicine Name",  3),
    ("batch_number", "Batch No",       2),
    ("expiry_date",  "Expiry (MM/YY)", 2),
    ("quantity",     "TQT",            1),
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

    # Final stabilization fix (validation refresh timing): must run
    # before _render_table()/_render_summary() below - see
    # _sync_pending_widget_edits()'s docstring for why.
    _sync_pending_widget_edits()

    _render_table()
    _render_global_actions()
    _render_summary()


def _sync_pending_widget_edits() -> None:
    """Write every row's CURRENT widget value into the medicines list
    before anything is validated or rendered this rerun.

    Root cause this fixes: Streamlit resolves a keyed widget's value
    into st.session_state[widget_key] BEFORE the script body runs - so
    by the time this function is called, st.session_state already holds
    whatever the user just typed and confirmed (Enter/blur), for every
    row, not just the one that triggered this rerun. But the review's
    own medicines list is separate state that previously only got that
    same value written into it later, INSIDE _render_medicine_row's own
    st.text_input() call for that specific row - which happens AFTER
    _render_table() had already computed that rerun's errors/warnings
    from the list's still-stale value. The correction was real, but the
    red/yellow display for THIS rerun was computed one step too early to
    see it - so it only cleared on the NEXT rerun (e.g. after editing a
    different field), not the one that actually fixed it.

    Reading each row's already-resolved widget value directly here,
    before validation runs, closes that one-rerun lag. No validation
    RULE changes - validate_medicine()/validate_medicines() are
    untouched; only the timing of when a correction's fresh value
    becomes visible to them changes. _render_medicine_row's own
    identical sync-on-change check further down is unaffected and
    simply becomes a no-op on every rerun after this one already wrote
    the same value.
    """
    medicines = review_service.get_medicines()
    for idx, medicine in enumerate(medicines):
        row_id = medicine.get("_row_id")
        if not row_id:
            continue
        for field_key, _, _ in _COLUMNS:
            widget_key = f"review_row_{row_id}_{field_key}"
            if widget_key not in st.session_state:
                continue
            widget_value = st.session_state[widget_key]
            if widget_value != medicine.get(field_key, ""):
                review_service.update_medicine(idx, field_key, widget_value)


def _render_table() -> None:
    """Render the editable medicine table: one row per medicine.

    Wrapped in a keyed container purely so the mobile-only CSS in
    _render_table_scroll_css can target this table specifically. The
    container itself adds no visible styling (no border/padding), so
    on its own it changes nothing — see _render_table_scroll_css for
    the actual (mobile-only) behavior change.
    """
    medicines = review_service.get_medicines_with_live_warnings()

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


def _map_blocking_error(message: str, medicine: dict) -> dict:
    """Turn one plain-string error from review_service.validate_medicine()
    into a display-friendly dict: {field, message, found, expected}.

    Purely additive/cosmetic - does not change what triggers an error or
    its wording; only figures out, from the message text, which field it
    belongs to (via _BLOCKING_FIELD_INFO) so the UI can highlight that
    column and show the row's actual current value as "Found".
    """
    for substring, field_key, expected in _BLOCKING_FIELD_INFO:
        if substring in message:
            found = str(medicine.get(field_key, "")).strip()
            return {
                "field": field_key,
                "message": message,
                "found": found if found else "(blank)",
                "expected": expected,
            }
    # Unrecognised message shape - still shown to the user, just without
    # field-specific highlighting or a Found/Expected line.
    return {"field": None, "message": message, "found": "", "expected": ""}


def _field_column_index(field_key: str):
    """Return this field's position in _COLUMNS (for CSS nth-child
    targeting), or None if it's not one of the editable columns."""
    for i, (key, _, _) in enumerate(_COLUMNS):
        if key == field_key:
            return i
    return None


def _effective_warning_flags(medicine: dict, row_errors: list) -> list:
    """Return this row's advisory flags (from the live-recomputed
    "_validation" set by review_service.get_medicines_with_live_warnings())
    with any flag suppressed whose issue is already covered by a RED
    blocking error on the same field this rerun.

    Priority rule: RED always wins. A blank Batch Number, for example,
    already produces a RED "Batch number is required." error (since the
    RED-validation sprint) - EMPTY_BATCH would otherwise ALSO fire as a
    YELLOW warning for the exact same reason. This filters that
    duplicate out so the reviewer only ever sees it once, as RED. Does
    not change validation.py's rules - a suppressed flag is still
    present in "_validation", just not shown here.
    """
    flags = medicine.get("_validation", {}).get("flags", [])
    if not flags:
        return []
    error_fields = {
        mapped["field"]
        for mapped in (_map_blocking_error(msg, medicine) for msg in row_errors)
        if mapped["field"] is not None
    }
    return [f for f in flags if _WARNING_FIELD_OVERLAP.get(f) not in error_fields]


def _render_row_highlight_css(container_key: str, has_error: bool, has_warning: bool, error_field_indexes: list) -> None:
    """Inject scoped CSS to highlight one review row - exactly two
    visual levels, per Sprint 2.1 Part B:
      - Red left-border + tinted background: this row has at least one
        blocking validation error (review_service.validate_medicine()).
      - Yellow (amber) left-border + tinted background: no blocking
        error, but at least one advisory Validation Layer flag
        (modules/invoice_scan/validation.py - unchanged this sprint).
      - Nothing: clean row.

    Reuses the same scoped-CSS-via-keyed-container technique already
    used elsewhere in this file (_render_table_scroll_css, targeting
    the auto-generated `.st-key-<container_key>` class) - no new UI
    pattern introduced.

    error_field_indexes additionally draws a red border around the
    specific offending input(s) within an error row, where a field
    could be identified from the error message - "highlight the
    affected field if possible".
    """
    if has_error:
        color = "#dc2626"
        bg = "rgba(220, 38, 38, 0.07)"
    elif has_warning:
        color = "#d97706"
        bg = "rgba(217, 119, 6, 0.07)"
    else:
        return

    field_css = "\n".join(
        f'.st-key-{container_key} [data-testid="stColumn"]:nth-child({i + 1}) '
        f'[data-testid="stTextInput"] input {{ border: 2px solid {color} !important; }}'
        for i in error_field_indexes
    )

    st.markdown(
        f"""
        <style>
        .st-key-{container_key} {{
            border-left: 4px solid {color};
            background-color: {bg};
            padding: 0.5rem 0.5rem 0.1rem 0.6rem;
            border-radius: 4px;
            margin-bottom: 0.3rem;
        }}
        {field_css}
        </style>
        """,
        unsafe_allow_html=True,
    )


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
        row_errors: Blocking validation errors for this row, from
                     review_service.validate_medicine() (unchanged this
                     sprint - still a plain list of strings).
    """
    row_id = medicine.get("_row_id", idx)

    validation_meta = medicine.get("_validation", {})
    flags = _effective_warning_flags(medicine, row_errors)
    flag_confidence = validation_meta.get("flag_confidence", {})
    normal_flags = [f for f in flags if flag_confidence.get(f, "normal") != "low"]
    low_confidence_flags = [f for f in flags if flag_confidence.get(f, "normal") == "low"]

    has_error = bool(row_errors)
    has_warning = bool(flags)  # any NON-SUPPRESSED advisory flag -> yellow row

    mapped_errors = [_map_blocking_error(msg, medicine) for msg in row_errors]
    error_field_indexes = sorted({
        _field_column_index(e["field"])
        for e in mapped_errors
        if e["field"] is not None
    })

    row_container_key = f"review_row_container_{row_id}"
    _render_row_highlight_css(row_container_key, has_error, has_warning, error_field_indexes)

    with st.container(key=row_container_key):
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

        # 🔴 Blocking validation errors. Each distinct reason is shown
        # exactly once, directly below the row, with the exact reason
        # plus what was found and what's expected - never a duplicate
        # generic "Row N has errors" message on top of this. Blocking:
        # the Save button below still checks validate_all_medicines()
        # and refuses to save while any of these remain.
        #
        # Kept to a single line (same visual height as the 🟡 warning
        # line below) - same information as before (message, found,
        # expected), just laid out inline instead of across several
        # blank-line-separated paragraphs.
        for err in mapped_errors:
            body = f"🔴 {err['message']}"
            if err["expected"]:
                body += f" Found: `{err['found']}` — Expected: {err['expected']}"
            st.error(body)

        # 🟡 Non-blocking advisory warnings (Validation Layer - unchanged
        # this sprint). Never block Save. Normal-confidence flags use
        # st.warning; low-confidence DUPLICATE_BATCH (Sprint 2) stays a
        # quieter st.caption - the row itself is still highlighted
        # yellow either way, so the row-level highlight stays a strict
        # two-level system (red/yellow) even though message prominence
        # can still vary within "yellow". Each flag's reason is shown
        # exactly once - no repeated or aggregated restatement.
        for flag in normal_flags:
            st.warning(f"🟡 {_FLAG_LABELS.get(flag, flag)}")
        for flag in low_confidence_flags:
            st.caption(f"🟡 {_FLAG_LABELS.get(flag, flag)}")


def _render_global_actions() -> None:
    """Render the 'Add New Medicine' button below the table."""
    st.write("")
    if st.button("➕ Add New Medicine", key="add_new_medicine_row"):
        review_service.add_empty_medicine()
        st.rerun()


def _render_summary() -> None:
    """Show live medicine count, validation summary, Save and Clear buttons.

    The three validation metrics below are computed from the exact same
    two sources that drive each row's red/yellow highlight in
    _render_medicine_row (review_service.validate_all_medicines() for
    blocking errors, and each row's "_validation" flags for warnings),
    counted per ROW rather than per individual issue - so these numbers
    always match the number of red/yellow highlighted rows above,
    one-to-one.
    """
    from core.session import get_current_store_id

    medicines = review_service.get_medicines_with_live_warnings()
    total = len(medicines)

    st.divider()

    errors_by_row = review_service.validate_all_medicines()
    error_row_indexes = set(errors_by_row.keys())

    warning_row_indexes = {
        idx for idx, m in enumerate(medicines)
        if _effective_warning_flags(m, errors_by_row.get(idx, []))
    }

    # "Ready to Save" is computed live, the same way as the other three -
    # never cached in session_state. A row counts as ready only if it has
    # neither a blocking error nor an advisory warning right now.
    ready_row_indexes = {
        idx for idx in range(total)
        if idx not in error_row_indexes and idx not in warning_row_indexes
    }

    col_total, col_errors, col_warnings, col_ready = st.columns(4)
    col_total.metric("📦 Total Medicines", total)
    col_errors.metric("🔴 Needs Fix (Save Blocked)", len(error_row_indexes))
    col_warnings.metric("🟡 Please Check (Optional)", len(warning_row_indexes))
    col_ready.metric("✅ Ready to Save", len(ready_row_indexes))

    if error_row_indexes:
        st.error(
            f"🔴 {len(error_row_indexes)} row(s) have a blocking validation "
            "error. Please fix the highlighted fields above before saving."
        )
    if warning_row_indexes:
        st.caption(
            f"🟡 {len(warning_row_indexes)} row(s) have a warning worth a "
            "second look (see above). This does not block saving."
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
            bump_cache_epoch()
            st.success(f"✅ {saved} medicine(s) saved successfully to inventory.")

        if skipped:
            for item in skipped:
                st.error(
                    f"Row {item['row']} — {item['name']}: {item['error']}"
                )

    _render_pending_matches()


def _render_pending_matches() -> None:
    """Render a "Possible Match Found" confirmation for every row left
    over from the last Save whose batch number was blank and might be
    the same lot as an existing product with a real batch number (see
    review_service.save_invoice_medicines /
    products.service.find_possible_batch_match).

    A row here was deliberately NOT auto-merged and NOT auto-saved -
    the store owner must pick "Yes" (merge into the existing lot) or
    "Create New" (save as a new lot instead) before it enters the
    inventory at all.
    """
    pending = review_service.get_pending_matches()
    if not pending:
        return

    st.write("")
    st.warning(f"⚠️ {len(pending)} row(s) need a decision before they can be saved.")

    for idx, entry in enumerate(pending):
        match = entry["match"]
        lot = entry["lot_data"]
        with st.container(border=True):
            st.markdown(f"**Possible Match Found — Row {entry['row']}**")
            st.write(
                f"Existing: **{match['name']}** • Batch: {match['batch_number']} • "
                f"Expires: {match['expiry_date']} • Qty: {match['quantity']}"
            )
            st.write(
                f"New: **{lot['name']}** • Batch: (blank) • "
                f"Expires: {lot['expiry_date']} • Qty: {lot['quantity']}"
            )
            col_yes, col_new = st.columns(2)
            with col_yes:
                if st.button("Yes, Merge", key=f"pending_merge_{idx}", use_container_width=True):
                    review_service.resolve_pending_match(idx, "merge")
                    bump_cache_epoch()
                    st.rerun()
            with col_new:
                if st.button("Create New", key=f"pending_create_{idx}", use_container_width=True):
                    review_service.resolve_pending_match(idx, "create_new")
                    bump_cache_epoch()
                    st.rerun()