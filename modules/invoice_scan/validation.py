"""
Validation Layer for invoice OCR results.

Sits in the pipeline strictly between Gemini extraction and the editable
Review table:

    Upload -> Preprocessing -> Gemini Extraction -> Validation -> Review -> Save

This module is deterministic and advisory only:
  - It NEVER calls Gemini, or any other model.
  - It NEVER modifies, corrects, or infers any extracted field value.
  - It ONLY reads the already-extracted medicine list and attaches a
    temporary "_validation" metadata dict to each row, flagging rows a
    human reviewer may want to double-check.
  - It NEVER blocks saving. Every flag here is advisory only.

The metadata is not part of the medicine schema (MEDICINE_FIELDS in
ocr_service.py is unchanged), is never written to the database, and
exists only for the lifetime of the review session.

Rules implemented (all flag-only, per Phase 9B):
  1. MRP_LESS_THAN_RATE - rate is greater than mrp.
  2. GST_OUTLIER        - gst_percent is a lone outlier against a single
                          clearly-dominant invoice-wide GST pattern.
                          (Sprint 2: see _gst_pattern - suppressed
                          entirely when the invoice legitimately mixes
                          multiple GST slabs, so mixed-slab invoices no
                          longer produce false warnings.)
  3. EMPTY_BATCH        - batch_number is blank.
  4. EMPTY_EXPIRY       - expiry_date is blank.
  5. EMPTY_MRP          - mrp is blank.
  6. EMPTY_RATE         - rate is blank.
  7. DUPLICATE_BATCH    - this batch_number appears on more than one row
                          in a way that looks genuinely suspicious.
                          (Sprint 2: see _is_suspicious_duplicate -
                          Phase 8 proved two genuinely different
                          medicines can legitimately share a batch
                          number, so the "obviously legitimate" pattern
                          confirmed there - different medicine name AND
                          different expiry - is no longer flagged at
                          all. When this rule does fire, it is always
                          marked "low" confidence in flag_confidence.)
  8. INVALID_EXPIRY_FORMAT (Phase 6) - expiry_date is non-blank but is
                          not a recognised Month/Year format. Reuses
                          utils.validators.is_valid_expiry() - the same
                          single canonical expiry validator already
                          used by review_service.py's blocking Save
                          check and modules/products/service.py - no
                          new date logic is introduced here. Only
                          fires when expiry_date is non-blank (blank is
                          already EMPTY_EXPIRY's job, rule 4).

None of these rules assume a flagged value is wrong - they only surface
it for review. See Phase 9B: e.g. two genuinely different medicines can
legitimately share a batch number, and a genuinely blank source cell is
not an error.
"""

from collections import Counter

from utils.validators import is_valid_expiry

_validation_metadata_template = {
    "status": "ok",
    "flags": [],
    "flag_confidence": {},
}

# Flags that are always attached with reduced ("low") confidence, even
# when they do fire - Sprint 2. A "low" confidence flag is still shown
# to the reviewer (never silently dropped once triggered) but is meant
# to read as "worth a glance", not "likely wrong".
_LOW_CONFIDENCE_FLAGS = {"DUPLICATE_BATCH"}


def _to_float(value) -> float | None:
    """Best-effort parse to float. Returns None (never raises) if the
    value is missing, blank, or not numeric."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _gst_pattern(medicines: list) -> dict:
    """Determine whether the invoice has a single clearly-dominant GST
    rate to compare rows against, or whether it legitimately mixes
    multiple GST slabs (in which case no row should be flagged at all).

    Sprint 2 fix: the original rule ("differs from the single most
    common value") produced false warnings on invoices that legitimately
    use more than one GST slab across different product categories.

    Logic:
      - If two or more distinct gst_percent values each appear on more
        than one row, the invoice clearly contains multiple legitimate
        GST clusters -> suppressed entirely (dominant=None).
      - If the single most common value only appears once (i.e. every
        row has a different gst_percent), there is no established
        majority pattern to compare against -> suppressed entirely.
      - Otherwise there is exactly one real majority cluster, and a row
        can be flagged only if its value is itself a singleton (occurs
        on exactly one row) and differs from that majority value. This
        reproduces the two confirmed Phase 8 GST errors, which were
        both lone outliers inside an otherwise uniform column.

    Returns:
        {"dominant": str | None, "counts": Counter}
        dominant is None whenever GST checking should be suppressed for
        this whole invoice.
    """
    values = [
        str(row.get("gst_percent", "")).strip()
        for row in medicines
        if str(row.get("gst_percent", "")).strip()
    ]
    counts = Counter(values)
    if not counts:
        return {"dominant": None, "counts": counts}

    dominant, dominant_count = counts.most_common(1)[0]
    clusters_with_multiple = [v for v, c in counts.items() if c > 1]

    if dominant_count == 1 or len(clusters_with_multiple) >= 2:
        # No established single pattern (all-unique values), or the
        # invoice genuinely mixes multiple GST slabs -> don't warn.
        return {"dominant": None, "counts": counts}

    return {"dominant": dominant, "counts": counts}


def _duplicate_batch_groups(medicines: list) -> dict:
    """Return {batch_number: [row, row, ...]} for every non-empty batch
    number that appears on more than one row. Rows are the actual dicts
    from `medicines`, so identity comparison against a specific row
    works for the suspicion check below."""
    by_batch: dict = {}
    for row in medicines:
        batch = str(row.get("batch_number", "")).strip()
        if batch:
            by_batch.setdefault(batch, []).append(row)
    return {batch: rows for batch, rows in by_batch.items() if len(rows) > 1}


def _is_suspicious_duplicate(row: dict, rows_sharing_batch: list) -> bool:
    """Decide whether a shared batch number is worth flagging.

    Sprint 2 fix: Phase 8 confirmed a real invoice where two genuinely
    different medicines (different name AND different expiry date)
    legitimately shared the same batch number. That exact pattern -
    different name AND different expiry for every other row sharing the
    batch - is treated as an "obviously legitimate" duplicate and is not
    flagged at all.

    A duplicate is treated as genuinely suspicious only if at least one
    other row sharing the batch also shares this row's medicine name, or
    also shares this row's expiry date - either of those makes the
    duplication look more like a copy/misread than a coincidence.
    """
    this_name = str(row.get("name", "")).strip().lower()
    this_expiry = str(row.get("expiry_date", "")).strip()

    for other in rows_sharing_batch:
        if other is row:
            continue
        other_name = str(other.get("name", "")).strip().lower()
        other_expiry = str(other.get("expiry_date", "")).strip()
        if this_name and this_name == other_name:
            return True
        if this_expiry and this_expiry == other_expiry:
            return True

    return False


def validate_medicines(medicines: list) -> list:
    """Attach advisory validation flags to a list of medicine rows.

    Deterministic and read-only with respect to every existing field:
    no name/batch_number/expiry_date/quantity/mrp/rate/gst_percent value
    is ever changed, inferred, or guessed. The only mutation is adding
    (or overwriting) a "_validation" key on each row dict.

    Args:
        medicines: List of medicine dicts (MEDICINE_FIELDS keys plus
            whatever session bookkeeping keys like "_row_id" already
            exist). Rows are updated in place; the same list object is
            also returned for convenient chaining.

    Returns:
        The same list, in the same order, same length, with every row
        dict now also containing:
            "_validation": {
                "status": "ok" | "warning",
                "flags": [...],
                "flag_confidence": {flag_code: "low" | "normal", ...},
            }
    """
    if not medicines:
        return medicines

    gst_pattern = _gst_pattern(medicines)
    duplicate_batch_groups = _duplicate_batch_groups(medicines)

    for row in medicines:
        flags = []

        # Rule 1: MRP_LESS_THAN_RATE
        mrp = _to_float(row.get("mrp", ""))
        rate = _to_float(row.get("rate", ""))
        if mrp is not None and rate is not None and rate > mrp:
            flags.append("MRP_LESS_THAN_RATE")

        # Rule 2: GST_OUTLIER (Sprint 2: see _gst_pattern)
        gst = str(row.get("gst_percent", "")).strip()
        dominant_gst = gst_pattern["dominant"]
        if (
            dominant_gst is not None
            and gst
            and gst != dominant_gst
            and gst_pattern["counts"].get(gst, 0) == 1
        ):
            flags.append("GST_OUTLIER")

        # Rule 3: EMPTY_BATCH
        if not str(row.get("batch_number", "")).strip():
            flags.append("EMPTY_BATCH")

        # Rule 4: EMPTY_EXPIRY
        if not str(row.get("expiry_date", "")).strip():
            flags.append("EMPTY_EXPIRY")

        # Rule 5: EMPTY_MRP
        if not str(row.get("mrp", "")).strip():
            flags.append("EMPTY_MRP")

        # Rule 6: EMPTY_RATE
        if not str(row.get("rate", "")).strip():
            flags.append("EMPTY_RATE")

        # Rule 7: DUPLICATE_BATCH (Sprint 2: see _is_suspicious_duplicate)
        batch = str(row.get("batch_number", "")).strip()
        if batch and batch in duplicate_batch_groups:
            if _is_suspicious_duplicate(row, duplicate_batch_groups[batch]):
                flags.append("DUPLICATE_BATCH")

        # Rule 8: INVALID_EXPIRY_FORMAT (Phase 6) - only checked when
        # non-blank; blank is already covered by Rule 4 (EMPTY_EXPIRY).
        # Reuses the project's existing single canonical expiry
        # validator (utils.validators.is_valid_expiry) - no new date
        # parsing logic here.
        expiry = str(row.get("expiry_date", "")).strip()
        if expiry and not is_valid_expiry(expiry):
            flags.append("INVALID_EXPIRY_FORMAT")

        row["_validation"] = {
            "status": "warning" if flags else "ok",
            "flags": flags,
            "flag_confidence": {
                flag: ("low" if flag in _LOW_CONFIDENCE_FLAGS else "normal")
                for flag in flags
            },
        }

    return medicines
