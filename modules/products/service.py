"""
Product Management business logic.

Owns validation and orchestration for creating, editing, and deleting
products - the rules for what makes a product's data valid, separate
from how it's stored (repository.py) or displayed (ui.py).

Validation here is driven by config/product_schema.py rather than
hardcoding "name is required" style checks per field, so a future change
to which fields are required for a different business type changes one
config file, not this service.
"""

from datetime import date, datetime

from modules.products import repository as products_repository
from config.product_schema import PRODUCT_FIELDS, FieldType
from core.exceptions import ValidationError
from utils.validators import is_valid_expiry, parse_expiry_month_year


def _validate_and_clean_product_data(form_data: dict, enforce_future_expiry: bool) -> dict:
    """Validate raw form input against product_schema rules and return
    a cleaned dict ready for the repository.

    Iterates config.product_schema.PRODUCT_FIELDS rather than checking
    each field by name, so adding, removing, or changing a field's
    required/type status in product_schema.py automatically changes
    what this function enforces - no parallel validation logic to keep
    in sync.

    Args:
        form_data: Raw values keyed by product_schema field keys, as
            collected from the UI form.
        enforce_future_expiry: If True, rejects an expiry date in the
            past. True for new products (catches a typo'd date before
            it enters the system), False for edits to an existing
            product (a product can legitimately already be expired -
            that's exactly what the Expired Products metric is for, and
            a store owner must still be able to open and re-save/correct
            an expired product's other fields without being blocked by
            its own expiry date).

    Returns:
        A cleaned dict with the same keys, with type coercion applied
        (e.g. quantity/mrp as numbers, dates as ISO strings) and
        whitespace trimmed from text fields.

    Raises:
        ValidationError: If a required field is missing, or any field's
            value fails its type-specific validation rule.
    """
    cleaned = {}

    # minimum_stock_threshold is validated separately, before the
    # generic field loop, because its rule depends on a UI-only signal
    # (was the "custom threshold" checkbox on?) that has no equivalent
    # in product_schema.py - it's not a property of the field itself,
    # it's a property of how this specific form chose to expose it.
    # Handling it here keeps that rule visible and testable in one
    # place, rather than smuggled into the generic NUMBER branch below
    # as a special case for one field key.
    custom_threshold_enabled = form_data.get("_minimum_stock_threshold_enabled", False)

    if custom_threshold_enabled:
        raw_threshold = form_data.get("minimum_stock_threshold")
        if raw_threshold is None or (isinstance(raw_threshold, str) and not raw_threshold.strip()):
            raise ValidationError("Please enter a custom minimum stock level.")
        try:
            threshold_value = int(float(raw_threshold))
        except (TypeError, ValueError):
            raise ValidationError("Please enter a custom minimum stock level.")
        if threshold_value < 1:
            raise ValidationError("Minimum stock must be at least 1.")
        cleaned["minimum_stock_threshold"] = threshold_value
    else:
        # Checkbox off (or this call came from a non-UI caller that
        # never set the sentinel, e.g. a future OCR pipeline) means
        # "use the store-wide default" - stored as NULL, exactly as
        # before this fix.
        cleaned["minimum_stock_threshold"] = None

    for field in PRODUCT_FIELDS:
        if field.key == "minimum_stock_threshold":
            continue  # already handled above

        raw_value = form_data.get(field.key)

        is_empty = raw_value is None or (
            isinstance(raw_value, str) and not raw_value.strip()
        )

        if is_empty:
            if field.required:
                raise ValidationError(f"{field.label} is required.")
            cleaned[field.key] = None
            continue

        if field.field_type == FieldType.TEXT:
            cleaned[field.key] = str(raw_value).strip()

        elif field.field_type == FieldType.DATE:
            # expiry_date stores Month/Year strings (e.g. "03/28", "Jun-2028")
            # from both manual entry (Product Management) and OCR-sourced saves.
            # Other DATE fields (purchase_date) remain ISO-format.
            if field.key == "expiry_date":
                from utils.validators import is_valid_expiry
                str_value = str(raw_value).strip() if not isinstance(raw_value, date) else raw_value.isoformat()
                if not is_valid_expiry(str_value) and not isinstance(raw_value, date):
                    raise ValidationError(
                        "Expiry must be in Month/Year format "
                        "(e.g. 3/28, 03/28, 03/2028 or Jun-2028)."
                    )
                # Store as-is for Month/Year strings; ISO for date objects
                cleaned[field.key] = raw_value.isoformat() if isinstance(raw_value, date) else str_value
            else:
                # Streamlit's date_input returns a datetime.date object
                # directly; this also accepts an ISO string for callers
                # outside the UI.
                if isinstance(raw_value, date):
                    cleaned[field.key] = raw_value.isoformat()
                else:
                    try:
                        cleaned[field.key] = date.fromisoformat(str(raw_value)).isoformat()
                    except ValueError:
                        raise ValidationError(f"{field.label} is not a valid date.")

        elif field.field_type in (FieldType.NUMBER, FieldType.PERCENT):
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                raise ValidationError(f"{field.label} must be a number.")

            if numeric_value < 0:
                raise ValidationError(f"{field.label} cannot be negative.")

            if field.field_type == FieldType.PERCENT and numeric_value > 100:
                raise ValidationError(f"{field.label} cannot exceed 100%.")

            # Quantity is stored as whole units (you can't have half a
            # tablet strip in this MVP's model); monetary/percent fields
            # keep decimal precision.
            if field.key == "quantity":
                cleaned[field.key] = int(numeric_value)
            else:
                cleaned[field.key] = numeric_value

    # Future-expiry check: only for add_product (enforce_future_expiry=True).
    # Uses parse_expiry_month_year so both ISO dates (from the date picker,
    # which become real date objects converted to ISO above) and MM/YY strings
    # are handled by the same canonical path.
    if enforce_future_expiry and cleaned.get("expiry_date"):
        from utils.validators import parse_expiry_month_year
        expiry_str = cleaned["expiry_date"]
        try:
            exp_month, exp_year = parse_expiry_month_year(expiry_str)
            today = date.today()
            if (exp_year, exp_month) < (today.year, today.month):
                raise ValidationError(
                    "Expiry must be in the current month or a future month. "
                    f"'{expiry_str}' appears to be in the past."
                )
        except ValueError:
            # parse_expiry_month_year could not parse this value; the format
            # check above already validated it, so just skip the future check.
            pass

    return cleaned


def add_product(store_id: int, form_data: dict) -> int:
    """Validate and create a new product for a store.

    Args:
        store_id: The currently logged-in store's ID.
        form_data: Raw field values from the Add Product form.

    Returns:
        The newly created product_id.

    Raises:
        ValidationError: If validation fails, or if a product with the
            same name and batch number already exists for this store
            (the same medicine batch should be edited/restocked, not
            duplicated as a second row).
    """
    cleaned_data = _validate_and_clean_product_data(form_data, enforce_future_expiry=True)

    existing = products_repository.get_all_products(store_id, search_term=cleaned_data["name"])
    for product in existing:
        if (
            product["name"].lower() == cleaned_data["name"].lower()
            and product["batch_number"].lower() == cleaned_data["batch_number"].lower()
        ):
            raise ValidationError(
                f"A product named '{cleaned_data['name']}' with batch "
                f"number '{cleaned_data['batch_number']}' already exists. "
                "Please edit the existing entry instead, or use a "
                "different batch number."
            )

    return products_repository.create_product(store_id, cleaned_data)


def edit_product(store_id: int, product_id: int, form_data: dict) -> None:
    """Validate and update an existing product.

    Past expiry dates are allowed here (unlike add_product) since a
    product already in the system may have genuinely expired - that's
    the normal, expected lifecycle this app tracks, not an input error.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product being edited.
        form_data: Raw field values from the Edit Product form.

    Raises:
        ValidationError: If validation fails, or if the product does not
            belong to this store (propagated from the repository).
    """
    cleaned_data = _validate_and_clean_product_data(form_data, enforce_future_expiry=False)
    products_repository.update_product(store_id, product_id, cleaned_data)


def remove_product(store_id: int, product_id: int) -> None:
    """Delete a product.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product to delete.

    Raises:
        ValidationError: If the product does not belong to this store
            (propagated from the repository).
    """
    products_repository.delete_product(store_id, product_id)


def search_products(store_id: int, search_term: str = None) -> list:
    """List all products for a store, optionally filtered by search term.

    Args:
        store_id: The currently logged-in store's ID.
        search_term: Optional text to filter by name or batch number.

    Returns:
        A list of product dicts.
    """
    return products_repository.get_all_products(store_id, search_term)

def search_products_page(store_id: int, search_term: str = None, limit: int = 50) -> dict:
    """First `limit` products (optionally filtered by search term) plus
    the total number of matches. Search always runs on ALL products."""
    return products_repository.get_products_page(store_id, search_term, limit)

def get_product(store_id: int, product_id: int) -> dict:
    """Get a single product by ID for editing.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product to fetch.

    Returns:
        The product dict.

    Raises:
        ValidationError: If no product with this ID exists for this
            store.
    """
    product = products_repository.get_product_by_id(store_id, product_id)
    if product is None:
        raise ValidationError("Product not found.")
    return product


def return_medicine(store_id: int, product_id: int) -> None:
    """Mark a medicine as returned to the supplier by setting its
    current stock quantity to 0.

    Every other stored field (name, batch, expiry, MRP, rate, GST,
    purchase date, minimum stock threshold) is preserved exactly as-is -
    this is not a delete, and not a second stock-tracking system: it
    reuses the existing edit_product() validate-and-update path (the
    same one Product Management's own Edit form uses) with quantity
    forced to 0 and every other field carried over unchanged from the
    current record.

    Args:
        store_id: The currently logged-in store's ID.
        product_id: The product being returned to the supplier.

    Raises:
        ValidationError: If the product does not belong to this store
            (propagated from get_product/edit_product).
    """
    product = get_product(store_id, product_id)

    form_data = {
        field.key: product.get(field.key)
        for field in PRODUCT_FIELDS
        if field.key != "minimum_stock_threshold"
    }
    form_data["quantity"] = 0

    existing_threshold = product.get("minimum_stock_threshold")
    form_data["_minimum_stock_threshold_enabled"] = existing_threshold is not None
    if existing_threshold is not None:
        form_data["minimum_stock_threshold"] = existing_threshold

    edit_product(store_id, product_id, form_data)


# =====================================================================
# Stock Lot identity & merge rules (Phase 13)
#
# Centralizes the "what counts as the same stock lot" decision in one
# place, per the project's stock-rule requirement: a future change to
# this rule should mean editing this section, not hunting through the
# invoice Save flow, Sales, or any other UI file.
#
#     stock lot identity = medicine_name + batch_no + expiry
#
#     same lot                          -> merge (add quantities)
#     different batch or expiry         -> separate lot
#     missing batch on the incoming row -> ask the user (see
#                                           find_possible_batch_match)
#     existing lot already at qty 0     -> reuse that lot (still an
#                                           exact identity match, so it
#                                           is covered by the same merge
#                                           path - "adding" to zero is
#                                           just the new quantity)
#     lot reduced to qty 0 by a sale    -> no separate mechanism: it
#                                           stays in the database (so it
#                                           can still be matched/reused
#                                           by the rule above) and is
#                                           simply excluded from "active"
#                                           listings by the existing
#                                           quantity > 0 convention
#                                           already used by Sales'
#                                           search/Frequently Sold (see
#                                           modules/sales/service.py)
#
# Used by modules/invoice_scan/review_service.py's
# save_invoice_medicines() (the invoice Save flow) and by
# modules/sales/service.py for FIFO consumption across lots of the
# same medicine name. It does NOT change add_product/edit_product or
# their validation rules - product_schema.py's batch_number stays
# required=True for manual Product Management entry, unchanged.
# Invoice-sourced rows get their own, narrower validation below
# (_clean_invoice_lot_data), because an incoming invoice row may
# legitimately have a blank batch number (see
# find_possible_batch_match), which manual entry does not allow.
# =====================================================================


def _normalize_lot_key(value) -> str:
    """Lowercase/strip a name or batch value for case-insensitive lot
    identity comparison. None/blank becomes "" (its own valid value -
    two blank batches are still an exact match on that field).
    """
    return str(value or "").strip().lower()


def _lots_match(name_a, batch_a, expiry_a, name_b, batch_b, expiry_b) -> bool:
    """The single stock-lot identity comparison, used everywhere a lot
    match must be decided. Name and batch compare case-insensitively
    (matching add_product's existing duplicate check); expiry compares
    as a stripped string (expiry is stored as a Month/Year string, not
    a date - the same string-level comparison already used by
    validation.py's DUPLICATE_BATCH rule).
    """
    return (
        _normalize_lot_key(name_a) == _normalize_lot_key(name_b)
        and _normalize_lot_key(batch_a) == _normalize_lot_key(batch_b)
        and str(expiry_a or "").strip() == str(expiry_b or "").strip()
    )


def find_exact_lot_match(store_id: int, name: str, batch_number: str, expiry_date: str) -> dict:
    """Find an existing product row that is the exact same stock lot
    (same name + same batch + same expiry - batch may be blank on both
    sides and still count as an exact match on that field).

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name.
        batch_number: Batch number, possibly blank.
        expiry_date: Expiry (Month/Year string).

    Returns:
        The matching product dict, or None if no exact match exists.
    """
    candidates = products_repository.get_all_products(store_id, search_term=name)
    for product in candidates:
        if _lots_match(
            name, batch_number, expiry_date,
            product["name"], product["batch_number"], product["expiry_date"],
        ):
            return product
    return None


def find_possible_batch_match(store_id: int, name: str, expiry_date: str) -> dict:
    """When an incoming row has no batch number, look for an existing
    lot that might be the same medicine restocked - same name and same
    expiry, but a real (non-blank) batch number already on file. This
    is deliberately NOT auto-merged (see save_or_merge_invoice_lot) -
    it only surfaces a candidate for the store owner to confirm.

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name from the incoming row.
        expiry_date: Expiry (Month/Year string) from the incoming row.

    Returns:
        The first matching existing product dict (non-blank batch,
        same name + expiry), or None if there is no such candidate.
    """
    candidates = products_repository.get_all_products(store_id, search_term=name)
    for product in candidates:
        if not product["batch_number"].strip():
            continue
        if (
            _normalize_lot_key(product["name"]) == _normalize_lot_key(name)
            and str(product["expiry_date"] or "").strip() == str(expiry_date or "").strip()
        ):
            return product
    return None


def find_zero_quantity_lot_by_name(store_id: int, name: str) -> dict:
    """Find an existing product row for the same medicine name whose
    quantity is currently 0 (e.g. previously sold out, or Returned via
    modules.products.service.return_medicine), regardless of its batch
    number or expiry date.

    This is the one exception to the stock-lot identity rule ("same
    name + same batch + same expiry") documented at the top of this
    section: a zero-quantity record represents no real, on-shelf stock
    of any specific batch, so a newly scanned invoice for the same
    medicine - even with a different batch/expiry - is understood as
    restocking that same medicine, not as a genuinely different lot
    that happens to share a name. A non-zero-quantity record is never
    matched here; that would blindly merge different batches while
    real stock still exists, which save_or_merge_invoice_lot's normal
    exact-match/possible-match rules already handle deliberately and
    conservatively.

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name from the incoming invoice row.

    Returns:
        The first matching existing product dict (same name,
        quantity == 0), or None if there is no such record.
    """
    candidates = products_repository.get_all_products(store_id, search_term=name)
    for product in candidates:
        if product["quantity"] == 0 and _normalize_lot_key(product["name"]) == _normalize_lot_key(name):
            return product
    return None

def find_quick_setup_placeholder_by_name(store_id: int, name: str) -> dict:
    """Find this store's Quick Setup placeholder row for a medicine
    name - the one product row (see modules.quick_setup.repository)
    created with just a name + quantity, no batch number yet, because
    the owner used Quick Setup to seed starting stock before any real
    invoice for it was ever scanned.

    Matched purely by (same name, blank batch_number) - deliberately
    separate from find_zero_quantity_lot_by_name above, which only
    matches quantity == 0: a Quick Setup placeholder typically HAS a
    real quantity (the owner's actual current stock count), so the
    zero-quantity check would never find it. If a placeholder row has
    separately been sold down to 0, find_zero_quantity_lot_by_name
    already matches and replaces it first (it runs first in
    save_or_merge_invoice_lot) - this function is never even reached
    for that row, so there is no overlap/conflict between the two.

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name from the incoming invoice row.

    Returns:
        The matching product dict, or None if there is no such record.
    """
    candidates = products_repository.get_all_products(store_id, search_term=name)
    for product in candidates:
        if (
            not str(product["batch_number"] or "").strip()
            and _normalize_lot_key(product["name"]) == _normalize_lot_key(name)
        ):
            return product
    return None

def _replace_zero_quantity_lot(store_id: int, existing: dict, cleaned: dict) -> None:
    """Reuse an existing zero-quantity product row for a newly scanned
    invoice medicine of the same name, replacing its batch, expiry,
    quantity, MRP, rate, GST%, and purchase date with the incoming
    row's own values - unlike _add_quantity_to_existing_lot (which
    preserves every existing field and only adds to quantity, for a
    genuine same-lot merge), here the existing record's per-lot details
    are stale (there is no real stock left of that specific batch/
    expiry) and are fully replaced by the new invoice data. The
    product_id itself, and every other product in the store, are
    untouched.

    Reuses products_repository.update_product (the same write path
    edit_product and _add_quantity_to_existing_lot already use) rather
    than a new SQL statement.
    """
    updated_data = {
        "name": cleaned["name"],
        "batch_number": cleaned["batch_number"],
        "expiry_date": cleaned["expiry_date"],
        "quantity": cleaned["quantity"],
        "mrp": cleaned["mrp"],
        "rate": cleaned["rate"],
        "gst_percent": cleaned["gst_percent"],
        "purchase_date": cleaned["purchase_date"],
        "minimum_stock_threshold": existing.get("minimum_stock_threshold"),
    }
    products_repository.update_product(store_id, existing["product_id"], updated_data)


def _clean_invoice_lot_data(raw: dict) -> dict:
    """Validate and clean one invoice-sourced medicine row for the
    stock-lot save path.

    Deliberately narrower than _validate_and_clean_product_data: batch
    number is NOT required here (a blank batch on an incoming invoice
    row is a legitimate case - see find_possible_batch_match - not a
    data error). Every other required field (name, expiry, quantity,
    mrp) keeps the same requirement as manual entry.
    minimum_stock_threshold is not part of invoice data and is always
    stored as NULL (store-wide default), matching the invoice Save
    flow's existing behavior from before this phase.

    Args:
        raw: Dict with name, batch_number, expiry_date, quantity, mrp,
            rate, gst_percent, purchase_date - raw string values as
            they arrive from the Review & Edit table.

    Returns:
        A cleaned dict ready for products_repository.create_product/
        update_product.

    Raises:
        ValidationError: If a required field is missing or invalid.
    """
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValidationError("Medicine Name is required.")

    batch_number = str(raw.get("batch_number", "")).strip()

    expiry_date = str(raw.get("expiry_date", "")).strip()
    if not expiry_date:
        raise ValidationError("Expiry is required.")
    if not is_valid_expiry(expiry_date):
        raise ValidationError(
            "Expiry must be in Month/Year format (e.g. 3/28, 03/28, 03/2028 or Jun-2028)."
        )

    try:
        # Requirement 6 fix: was int(float(...)), which silently
        # truncated any real decimal precision (e.g. qty 1.5 + free 0.5
        # = TQT 2.0 was fine, but qty 1.25 + free 0.50 = TQT 1.75 was
        # being truncated to 1 here at save time - the extraction-time
        # formula in ocr_service.py::_apply_quantity_formula() already
        # preserved "1.75" correctly as a string; this was the actual
        # point of data loss). quantity is stored as a plain float now;
        # SQLite's own type affinity on the products.quantity column
        # (declared INTEGER, per core/database.py) already stores a
        # whole-number float like 2.0 as an integer 2 and a fractional
        # float like 1.75 as REAL 1.75 - no database schema change
        # needed for this fix.
        quantity = float(raw.get("quantity"))
    except (TypeError, ValueError):
        raise ValidationError("Quantity must be a number.")
    if quantity < 0:
        raise ValidationError("Quantity cannot be negative.")

    try:
        mrp = float(raw.get("mrp"))
    except (TypeError, ValueError):
        raise ValidationError("MRP must be a number.")
    if mrp < 0:
        raise ValidationError("MRP cannot be negative.")

    rate_raw = raw.get("rate")
    rate = None
    if rate_raw is not None and str(rate_raw).strip():
        try:
            rate = float(rate_raw)
        except (TypeError, ValueError):
            raise ValidationError("Rate must be a number.")

    gst_raw = raw.get("gst_percent")
    gst_percent = None
    if gst_raw is not None and str(gst_raw).strip():
        try:
            gst_percent = float(gst_raw)
        except (TypeError, ValueError):
            raise ValidationError("GST % must be a number.")

    return {
        "name": name,
        "batch_number": batch_number,
        "expiry_date": expiry_date,
        "quantity": quantity,
        "mrp": mrp,
        "rate": rate,
        "gst_percent": gst_percent,
        "purchase_date": raw.get("purchase_date") or None,
        "minimum_stock_threshold": None,
    }


def _add_quantity_to_existing_lot(store_id: int, existing: dict, additional_quantity: int) -> None:
    """Add additional_quantity to an existing product row's quantity,
    leaving every other field (name, batch_number, expiry_date, mrp,
    rate, gst_percent, purchase_date, minimum_stock_threshold) exactly
    as it already was - the merge rule only ever specifies
    quantity = existing + new.

    Reuses products_repository.update_product (the same write path
    edit_product uses) rather than a new SQL statement.
    """
    updated_data = {
        key: existing.get(key)
        for key in (
            "name", "batch_number", "expiry_date", "mrp", "rate",
            "gst_percent", "purchase_date", "minimum_stock_threshold",
        )
    }
    updated_data["quantity"] = existing["quantity"] + additional_quantity
    products_repository.update_product(store_id, existing["product_id"], updated_data)


def save_or_merge_invoice_lot(
    store_id: int,
    lot_data: dict,
    merge_into_product_id: int = None,
    force_new: bool = False,
) -> dict:
    """Save one invoice-sourced medicine row using the stock-lot
    identity/merge rules (see this section's module docstring).

    Args:
        store_id: The currently logged-in store's ID.
        lot_data: Raw row dict (name, batch_number, expiry_date,
            quantity, mrp, rate, gst_percent, purchase_date) as it
            arrives from the invoice Review & Edit table.
        merge_into_product_id: If set, the store owner has already
            confirmed ("Yes") a possible-match prompt - merge the
            incoming quantity into this existing product_id directly,
            skipping the match search entirely.
        force_new: If True, the store owner has already chosen "Create
            New" from a possible-match prompt - skip the missing-batch
            possible-match search (an exact 3-field match, e.g. an
            existing zero-quantity lot with the same blank batch, is
            still checked and still merges - that is not the ambiguous
            case the prompt was about).

    Returns:
        A dict describing the outcome:
          {"status": "merged", "product_id": int} - added to an
              existing lot (covers the merge_into_product_id case, the
              same-3-fields case, and the zero-quantity-reuse case -
              all three are "merge", they just differ in how the
              matching row was found).
          {"status": "created", "product_id": int} - a new lot row was
              created.
          {"status": "needs_confirmation", "match": dict} - the row was
              NOT saved; `match` is the existing product dict the
              store owner must confirm merge/create-new against.

    Raises:
        ValidationError: If the row's data fails validation.
    """
    cleaned = _clean_invoice_lot_data(lot_data)

    if merge_into_product_id is not None:
        existing = products_repository.get_product_by_id(store_id, merge_into_product_id)
        if existing is None:
            raise ValidationError("The medicine to merge into could not be found.")
        _add_quantity_to_existing_lot(store_id, existing, cleaned["quantity"])
        return {"status": "merged", "product_id": existing["product_id"]}

    exact_match = find_exact_lot_match(
        store_id, cleaned["name"], cleaned["batch_number"], cleaned["expiry_date"]
    )
    if exact_match is not None:
        _add_quantity_to_existing_lot(store_id, exact_match, cleaned["quantity"])
        return {"status": "merged", "product_id": exact_match["product_id"]}

    # Zero-quantity reuse (Requirement 1): checked after an exact lot
    # match and before the blank-batch possible-match prompt below, and
    # regardless of whether the incoming batch/expiry differs from the
    # existing zero-quantity record's own - see
    # find_zero_quantity_lot_by_name's docstring for why this is the
    # one deliberate exception to the "same name + same batch + same
    # expiry" stock-lot identity rule. A non-zero-quantity record is
    # never matched here (find_zero_quantity_lot_by_name only ever
    # returns a quantity == 0 row), so this cannot affect the existing,
    # unmodified behavior for any lot that still has real stock.
    zero_qty_match = find_zero_quantity_lot_by_name(store_id, cleaned["name"])
    if zero_qty_match is not None:
        _replace_zero_quantity_lot(store_id, zero_qty_match, cleaned)
        return {"status": "merged", "product_id": zero_qty_match["product_id"]}

    # Quick Setup integration: a placeholder row (blank batch, real
    # quantity) for this exact name gets FILLED IN by the first real
    # invoice for it, rather than the invoice creating a second,
    # separate row. Reuses the same proven replace-helper as the
    # zero-quantity path above - only WHICH existing row qualifies
    # differs.
    placeholder_match = find_quick_setup_placeholder_by_name(store_id, cleaned["name"])
    if placeholder_match is not None:
        _replace_zero_quantity_lot(store_id, placeholder_match, cleaned)
        return {"status": "merged", "product_id": placeholder_match["product_id"]}

    if not cleaned["batch_number"] and not force_new:
        possible_match = find_possible_batch_match(
            store_id, cleaned["name"], cleaned["expiry_date"]
        )
        if possible_match is not None:
            return {"status": "needs_confirmation", "match": possible_match}

    new_product_id = products_repository.create_product(store_id, cleaned)
    return {"status": "created", "product_id": new_product_id}


def get_lots_by_name_sorted_by_expiry(store_id: int, name: str) -> list:
    """Get every in-stock lot (quantity > 0) of a given medicine name,
    sorted oldest-arrival-first - the single source of truth for FIFO
    consumption order, used by modules/sales/service.py so Sales never
    has to re-derive arrival ordering itself.

    Sort order (Requirement 1 fix): strict arrival-order FIFO, using
    product_id ascending as the arrival-order proxy - NOT expiry_date.
    product_id is SQLite's AUTOINCREMENT primary key, so it is already
    a stable, unique, monotonically-increasing stand-in for "which lot
    was created first," with no date parsing and no ties. This also
    deliberately sidesteps the zero-quantity-reuse edge case
    (save_or_merge_invoice_lot's zero-quantity-replacement step, above)
    cleanly: repurposing an existing zero-quantity row for brand new
    stock (_replace_zero_quantity_lot) does NOT change that row's
    product_id, so it correctly keeps its original arrival slot in this
    ordering rather than being mistaken for the newest arrival - no
    change to created_at/updated_at handling was needed to achieve
    this. (This function's name is kept unchanged, despite no longer
    sorting by expiry, to avoid touching its two call sites purely for
    a rename - see this section's module docstring/CHANGELOG for the
    behavior change.)

    A lot that sales has reduced to quantity 0 is naturally excluded
    here (see this section's module docstring) rather than deleted -
    it remains available for the merge rules above to find and reuse
    if the same lot is ever restocked.

    Args:
        store_id: The currently logged-in store's ID.
        name: Medicine name to match (case-insensitive, exact match).

    Returns:
        A list of product dicts, oldest arrival (lowest product_id)
        first.
    """
    candidates = products_repository.get_all_products(store_id, search_term=name)
    lots = [
        product for product in candidates
        if _normalize_lot_key(product["name"]) == _normalize_lot_key(name)
        and product["quantity"] > 0
    ]

    lots.sort(key=lambda product: product["product_id"])
    return lots
