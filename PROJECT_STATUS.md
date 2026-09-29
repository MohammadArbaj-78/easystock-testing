# PROJECT_STATUS.md

## Current Version

2.21.0 (per the latest `CHANGELOG.md` entry, "Strict Arrival-Order FIFO + Supabase Session Persistence + Startup Race Fix + Emergent Preprocessing + Low Stock Global Minimum + Decimal TQT Precision").

## Configuration

Required Streamlit secrets (`.streamlit/secrets.toml` locally, or the deployment platform's secrets settings - never committed to source control):

- `SUPABASE_URL` - the Supabase project's API URL.
- `SUPABASE_ANON_KEY` - the Supabase project's public/anon key (never the service-role key - used client-side for Auth only).

`core/supabase_client.py` (the separate, pre-existing business-data client used only when `ACTIVE_DB_BACKEND == "supabase"`) has its own, unrelated `SUPABASE_URL`/`SUPABASE_KEY` secrets - `SUPABASE_ANON_KEY` above is specific to `core/supabase_auth.py` and Authentication.

One-time Supabase dashboard configuration required before Sign Up/Login work against a real project:
1. In the Supabase dashboard, under Authentication -> Providers, ensure Email is enabled (it is Supabase's default provider - no other provider should be enabled for this app).
2. Under Authentication -> URL Configuration, set the Site URL to `http://localhost:8501` for local development (add the deployed app's own URL there too if/when deployed elsewhere) - required for Supabase's auth flow to recognize this Streamlit app's origin.
3. Copy the project's URL and anon/public key (Project Settings -> API) into the two secrets above.

## Project Stage

MVP. Phase 17 delivered six independent, surgical changes against the v2.20.0 baseline: (1) Sales lot ordering changed from expiry-based (FEFO) to true arrival-order FIFO (`product_id` ascending); (2) the Supabase-authenticated session now survives a full browser close/reopen via a localStorage-backed restoration bridge, not just in-app reruns; (3) a startup-time race in the Phase 16 `supabase_user_id` migration, which could surface as a brief red error under Login/Signup, is fixed; (4) invoice preprocessing before Gemini now uses the requested Emergent preprocessing function in place of the old geometry/quality/enhance pipeline (left on disk, simply no longer called); (5) the Low Stock page gained a session-scoped global minimum-stock dropdown (1-10), with a per-medicine custom minimum still always taking priority; (6) a decimal-truncation bug in the invoice Save path (`int(float(...))` on quantity) that silently rounded fractional TQT values down to whole numbers is fixed. Gemini's model, prompt (aside from Phase 16's positional-integrity rule), call count (still exactly one per invoice), parsing, validation, Review UI, Save/Clear, `sales_history`, Dashboard, Expiry Alerts, and Product Management are all untouched.

## Phase 17 Summary

- **Strict arrival-order FIFO**: `modules/products/service.py::get_lots_by_name_sorted_by_expiry()` now sorts by `product_id` ascending instead of `expiry_date` - this was previously FEFO, not true FIFO. `product_id` was chosen over `created_at`/`updated_at` specifically because it needs no schema change and stays correct across a zero-quantity-lot reuse (Phase 16), which would otherwise make a repurposed row look like the newest arrival. `save_or_merge_invoice_lot()`'s merge rules are unchanged - only consumption/search order changed.
- **Supabase session persistence across browser close/reopen**: new `core.supabase_auth.restore_session()` exchanges a saved refresh token for a fresh session via Supabase's own `refresh_session()` call. `core/login_ui.py` now persists the refresh token to the browser's `localStorage` after login/signup (via the same JS-bridge pattern `app.py`'s mobile-sidebar-autoclose already established). `app.py` gained a startup-restoration step using a short-lived `?rt=` query-parameter bridge (cleared immediately after use, on both success and failure) to read that stored token back into Python on a fresh connection. Logout now also clears the stored token. Verified only via mocked tests in this offline sandbox (no `supabase` package, no network) - a live browser/Supabase smoke-test is still required.
- **Startup migration race fix**: `core/database.py::initialize_database()`'s `ALTER TABLE ... ADD COLUMN supabase_user_id` call is now wrapped in a narrow `try/except sqlite3.OperationalError` that swallows only an exact "duplicate column name" race; any other error still raises unchanged.
- **Emergent preprocessing**: `modules/invoice_scan/ocr_service.py` gained `_emergent_preprocess()` (used verbatim as supplied), replacing the old `preprocess/` pipeline at its one call site. `_file_to_pil_image()` is unchanged; the only adapter needed was re-encoding the already-loaded PIL image to bytes before calling the new function. The existing preprocessing-failure fallback (original image, extraction still proceeds) and the single Gemini call are both preserved.
- **Low Stock global minimum dropdown**: `products_repository.get_low_stock_products()`/`_filter_low_stock_rows()`, `low_stock_service.py`, and `low_stock_ui.py` gained an optional `global_minimum` parameter (1-10, session-scoped via `st.session_state`, defaulting to the existing `DEFAULT_LOW_STOCK_THRESHOLD`). Dashboard's call site does not pass it and is unaffected. A medicine's own custom minimum always wins - unchanged, pre-existing `COALESCE` logic.
- **Decimal TQT precision**: `modules/products/service.py::_clean_invoice_lot_data()` no longer truncates quantity via `int(float(...))` at save time - the actual point of data loss, since the extraction-time formula was already correct. `ocr_service.py::_apply_quantity_formula()` also gained a `round(total, 2)` guard against floating-point addition artifacts. SQLite's own type affinity naturally stores whole numbers as integers and fractional values as REAL - no schema change needed.
- **Testing**: `tests/test_six_requirements.py` added (27 tests, all passing) covering Requirements 1, 3, 4, 5, 6. `tests/test_supabase_auth.py` extended with a new `TestRestoreSession` class (5 tests, all passing, mocked). Existing suite re-run via the offline harness: `test_ocr_service.py` (26/2), `test_review_service.py` (60/3), `test_preprocess_geometry_regression.py` (3/2), `test_extraction_iq200_focused.py` (13/0), `test_four_fixes.py` (18/0), `test_requirement1_zero_qty_replacement.py` (5/0) - identical to the v2.20.0 baseline; all failures pre-existing/environment-only.
- Full-project diff against the v2.20.0 baseline confirms exactly the expected file set changed (see `CHANGELOG.md`'s `[2.21.0]` entry) - no drift into the Gemini prompt (beyond Phase 16's prior line), Review UI/session, validation, sales_history, database schema files, Dashboard, Expiry Alerts, or Product Management.

## Phase 16 Summary

- **Zero-quantity medicine replacement**: `modules/products/service.py::save_or_merge_invoice_lot()` now checks, right after the existing exact-lot-match check, whether any existing product row for the same medicine name currently has `quantity == 0` (`find_zero_quantity_lot_by_name()`) regardless of that row's own batch/expiry - if found, the incoming invoice row's batch/expiry/quantity/MRP/rate/GST%/purchase date replace that record in place (`_replace_zero_quantity_lot()`). A record with real stock (`quantity > 0`) is never matched, so the existing rule - different batch or expiry stays separate while stock remains - is completely unchanged; this is a narrow exception, not a broader merge rule. `tests/test_requirement1_zero_qty_replacement.py` adds 5 tests covering same/different batch+expiry replacement, the unchanged non-zero-stock case, an unrelated medicine's own zero-quantity record staying untouched, and the pre-existing exact-match path still taking priority.
- **Supabase Authentication**: `core/auth.py` (the old custom system) deleted outright; `core/login_ui.py` rewritten for Email + Password (same file, same public function `app.py` calls, so `app.py`'s routing gate needed no change beyond its logout handler); new `core/supabase_auth.py` is the sole place Supabase Auth is called (`sign_up_and_create_store()`, `sign_in_and_resolve_store()`, `sign_out()`), using its own `SUPABASE_ANON_KEY`-configured client, separate from the existing business-data client. `stores` gained exactly one new, additive column (`supabase_user_id`, via an idempotent startup migration) to link a Supabase-authenticated user to their business row - no other schema change, and `products`/`sales_history`/every other business table is untouched. `core.session.start_session()` now also stores the Supabase access/refresh tokens in the same `st.session_state` dict it already used, so a normal rerun/navigation still doesn't force re-login; `get_current_store_id()` and every other pre-existing session accessor are byte-unchanged. Logout now calls Supabase's `sign_out()` before the pre-existing `end_session()`. See `CHANGELOG.md`'s `[2.20.0]` entry for full detail, including the explicit note that this was verified only via mocked tests (`tests/test_supabase_auth.py`, 15 tests) - the `supabase` package is not installed and there is no network access in this offline sandbox, so a live Supabase project smoke-test is still required before production use.
- **Gemini positional integrity**: `_EXTRACTION_PROMPT` gained one new rule (rule 5) appended to the existing 4-item `CRITICAL RULES` list, with no other text in the prompt touched. `MEDICINE_FIELDS`, parsing, the quantity formula, the model, and the single-call-per-invoice structure are unchanged.
- **Testing**: `tests/test_requirement1_zero_qty_replacement.py` (5/5), `tests/test_supabase_auth.py` (15/15) added. `tests/test_expiry_alerts.py`/`test_low_stock_alerts.py`/`test_products_ui_threshold_checkbox.py` updated (a local direct-SQL `signup()` helper replaces their now-broken `from core.auth import signup` import - same 4-argument signature, so no other line in those files changed). Existing suite re-run via the offline harness: `test_ocr_service.py` (26/2), `test_review_service.py` (60/3), `test_preprocess_geometry_regression.py` (3/2), `test_extraction_iq200_focused.py` (13/0), `test_four_fixes.py` (18/0) - identical to the v2.19.0 baseline; all failures pre-existing/environment-only.
- Full-project diff against the v2.19.0 baseline confirms exactly the expected file set changed (see `CHANGELOG.md`'s `[2.20.0]` entry) - no drift into Low Stock, Expiry Alerts, Dashboard, Sales FIFO/UI, Product Management UI, Database, Validation, Review UI/session, or preprocessing.

## Phase 15 Summary

- **Dashboard Expiry Alert after Return**: `modules/dashboard/service.py::get_dashboard_metrics()` now filters `expired_items`/`expiring_soon_items` to `quantity != 0`, mirroring `modules/alerts/service.py`'s already-correct exclusion. `low_stock_items`/`low_stock_count` and `return_medicine()`'s own quantity-to-0 behavior are unchanged.
- **Invoice duplicate-row merge**: investigated, found already correct - `save_or_merge_invoice_lot()`'s `find_exact_lot_match()` re-queries the database fresh before every row within a single Save, so two rows sharing name+batch+expiry already merge (combined quantity), and a different batch or expiry already stays separate. No production code changed; `tests/test_four_fixes.py` adds 5 tests locking this behavior in.
- **Sales search FIFO**: `modules/sales/service.py::search_products()` now returns at most one result per distinct medicine name - that name's FIFO-first lot via the existing, unmodified `products_service.get_lots_by_name_sorted_by_expiry()`. A newer batch is hidden from search while an older batch of the same medicine still has stock > 0; `sell_product()`'s own consumption order and every other Sales calculation are unchanged.
- **Product Management form data preservation**: `modules/products/ui.py`'s Add Product form no longer uses `st.form(..., clear_on_submit=True)`. A new `_clear_add_product_form_fields()` helper, gated by a `_reset_add_product_form` session-state sentinel set only after a successful `add_product()` call, resets the form's fields only on that success path - a validation failure now leaves every already-entered field exactly as typed. Validation rules, field names, and successful-save behavior are unchanged.
- **Testing**: `tests/test_four_fixes.py` added (18 new tests, all passing) directly covering all four items above. Existing suite re-run via the offline harness: `test_ocr_service.py` (26/2), `test_review_service.py` (60/3), `test_preprocess_geometry_regression.py` (3/2), `test_extraction_iq200_focused.py` (13/0) - identical to the v2.18.0 baseline; all failures pre-existing/environment-only.
- Full-project diff against the v2.18.0 baseline confirms exactly the expected file set changed (see `CHANGELOG.md`'s `[2.19.0]` entry) - no drift into `modules/products/service.py` (stock-lot rules, FIFO lot lookup), `modules/sales/ui.py`, Database, `app.py`, or Validation.

## Phase 14 Summary

- **OCR hint removed**: `modules/invoice_scan/row_ocr.py` and `modules/invoice_scan/field_evidence.py` deleted (confirmed zero references elsewhere before deletion). `ocr_service.py`'s `_get_ocr_evidence()`/`_hint_text_from_evidence()` helpers, their imports, the "SECONDARY OCR HINT" block, and the `field_evidence.build_field_evidence(...)` call all removed. Gemini's `contents` is now `[image, prompt]` only - single call, unchanged call count. `easyocr` dropped from `requirements.txt`; `opencv-python-headless`/`numpy` kept (still used by `preprocess/geometry.py`/`quality.py`, untouched). Preprocessing itself (geometry/quality/enhancement, the Phase 9.1 area-ratio guard) was not touched.
- **Confidence/risk-color layer removed**: `review_ui.py`'s `_render_field_risk_css()`, `_RISK_BACKGROUND_COLORS`, `_RISK_TEXT_COLOR`, and its call site deleted. The separate, pre-existing validation-driven row highlighting (`_render_row_highlight_css()` - red for a blocking error, amber for an advisory warning) is untouched and still fully functional.
- **New extraction prompt**: `ocr_service._EXTRACTION_PROMPT` replaced with the project owner's supplied structure-first, column-aware prompt, mapped onto the existing internal field names (`name`, `batch_number`, `expiry_date`, `qty`, `free`, `mrp`, `rate`, `gst_percent`) and kept as a JSON array so the existing `_parse_and_validate_response()` parser needed no change. `MEDICINE_FIELDS` (still 9 fields, including `tqt`) and `_apply_quantity_formula()` (the `qty+free=TQT` formula) are completely unchanged - the new prompt simply no longer asks for a separate `tqt` value, which the existing normalization already defaults to `""` for any field Gemini's JSON omits.
- **Testing**: existing offline harness run against `test_ocr_service.py` (26/2), `test_review_service.py` (60/3), `test_preprocess_geometry_regression.py` (3/2) - identical to a pristine v2.17.0 baseline run through the same harness; all failures pre-existing/environment-only. 13 new focused tests added (`tests/test_extraction_iq200_focused.py`), all passing, directly verifying the three changes above plus TQT-formula and `MEDICINE_FIELDS` non-regression.
- Full-project diff against the v2.17.0 baseline confirms exactly the expected file set changed (see `CHANGELOG.md`'s `[2.18.0]` entry for the complete list) - no drift into Products, Sales, Database, Validation, unrelated preprocessing, or `app.py`.

## Phase 13 Summary

- **Expiry Alerts expand/Return Medicine**: `modules/alerts/ui.py`'s `_render_alert_product_row` now wraps each row in `st.expander` (collapsed by default), matching `modules/products/ui.py`'s existing per-row expander pattern. "Return Medicine" is rendered only inside the opened expander. `modules/alerts/service.py`'s `get_categorized_alerts` now skips quantity-0 products when building both the expired and expiring-soon buckets, so a returned medicine (quantity forced to 0 by the pre-existing `return_medicine()`) disappears from Expiry Alerts on the next render - the database row is never touched by this filter, only bucket membership.
- **MRP/Rate display**: added to `modules/products/repository.py`'s SQLite and Supabase queries for `get_expired_products`, `get_expiring_soon_products`, and `get_low_stock_products` (both `mrp` and `rate` now selected/returned), then surfaced in `modules/alerts/ui.py`, `modules/alerts/low_stock_ui.py`, `modules/dashboard/ui.py` (`_render_item_table` and the Low Stock expander), and `modules/sales/ui.py` (`_render_sale_row`'s summary line). Display-only in every case - no calculation, stock, or schema change; both fields already existed in the `products` table.
- **Stock-lot identity & merge (new centralized section in `modules/products/service.py`)**: identity = `medicine_name + batch_number + expiry_date` (name/batch compared case-insensitively, expiry compared as the stored Month/Year string). `find_exact_lot_match` / `find_possible_batch_match` / `_clean_invoice_lot_data` / `_add_quantity_to_existing_lot` / `save_or_merge_invoice_lot` / `get_lots_by_name_sorted_by_expiry` are the single, centralized home for every stock-lot rule - a future rule change means editing this one section, not the invoice Save flow or Sales.
  - Same name + batch + expiry -> quantity merges into the existing row (only `quantity` changes; every other field, including an existing zero quantity, is preserved/added-to exactly as specified).
  - Different batch, or different expiry -> a new, separate product row (no merge, no prompt).
  - Missing batch number on an incoming row -> `find_possible_batch_match` looks for an existing lot with the same name + expiry and a real batch number; if found, `save_or_merge_invoice_lot` returns `{"status": "needs_confirmation", ...}` instead of saving, and `modules/invoice_scan/review_ui.py`'s new `_render_pending_matches()` renders a "Possible Match Found" Yes/Create-New prompt, wired to `review_service.resolve_pending_match`.
  - `modules/invoice_scan/review_service.py`'s `save_invoice_medicines` now calls `products_service.save_or_merge_invoice_lot` per row (instead of `add_product`) and tracks any `needs_confirmation` rows in a new `pending_matches` session list.
- **FIFO sale consumption**: `modules/sales/service.py`'s `sell_product` now resolves the medicine name from the clicked product_id, fetches every in-stock lot of that name via `get_lots_by_name_sorted_by_expiry` (earliest expiry first), and consumes across lots in order - a sale spanning more than one lot writes one `sales_history` row per lot actually consumed (each with its own real `batch_number`), reusing the existing `record_sale`/`reduce_stock` functions unmodified. A new `get_sellable_stock(store_id, name)` sums quantity across all lots of a name; `modules/sales/ui.py`'s `_render_sale_row` now caps/displays the quantity stepper against this aggregate instead of the single clicked row's own quantity, since a sale can now draw from more than one batch.
- **Known limitation (by design, not a defect)**: the missing-batch confirmation machinery above is fully implemented and unit-verified at the service layer, but is **not reachable through the invoice Scan "Save Medicines" button** in this release, because `modules/invoice_scan/review_service.py`'s existing blocking `validate_medicine()` still requires Batch Number to be non-blank (a deliberate "RED-validation sprint" v2.13.5 decision, explicitly protected by `tests/test_review_service.py::TestValidateMedicine::test_empty_batch_number_is_blocking`). Phase 13 was explicitly instructed not to modify blocking validation, so this rule was left untouched; a row with a blank batch number cannot currently reach `save_invoice_medicines()` via the UI. If missing-batch confirmation should become reachable, relaxing that one blocking check is the smallest change needed - flagged here for a future, explicitly-scoped task rather than done unilaterally.
- Invoice preprocessing, OCR, Gemini extraction/prompt, field evidence, validation (`validation.py`, `review_service.py`'s blocking `validate_medicine`), Review UI risk coloring, database schema, and existing APIs are all confirmed unchanged by this release (see `CHANGELOG.md`'s `[2.17.0]` entry and its file-level diff audit).

## Overall Progress

Eight modules remain implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. Release history for the OCR Accuracy / Review program:
- **Sprint 1 (v2.13.0)**: the Validation Layer.
- **Sprint 2 (v2.13.1)**: refined two of that layer's rules.
- **Sprint 2.1 (v2.13.2)**: session-reset bug fix + Review UI two-tier completion.
- **Stabilization sprint (v2.13.3)**: fixed logout not clearing review state, an invalid upload attempt able to wipe a valid existing review, and required numeric fields silently passing validation when blank.
- **Isolation fix (v2.13.4)**: review session strictly scoped to "currently on Invoice Scan" - reversed in v2.13.6.
- **Review Screen stabilization (v2.13.5)**: Review Summary relabeled with a live "Ready to Save" metric; Batch Number and Expiry made required; advisory warnings made live-recomputed; RED-suppresses-duplicate-YELLOW priority; owner-friendly message rewrite.
- **Final stabilization (v2.13.6)**: navigation persistence restored, validation refresh timing fixed, single-upload lock. Explicitly declared the final update for that stabilization phase.
- **TQT Support (v2.14.0)**: Gemini extracts `qty`/`free`/`tqt` instead of a single `quantity` field; internal formula computes final `quantity`.
- **EasyOCR isolated (v2.14.1)** / **OpenCV row detection isolated (v2.14.2), then removed (v2.14.3)** after failing real-invoice testing.
- **Full-invoice EasyOCR hint integration + Field Evidence/Risk Engine + Review UI risk coloring (v2.15.0)**: the previously-isolated EasyOCR capability wired into the single Gemini call as a full-invoice, non-authoritative hint; `field_evidence.py` classifies each reviewable field's risk from Gemini's reading, EasyOCR evidence, and validation results; the Review Screen shows this as a background color per field.
- **Preprocessing perspective-correction fix (v2.15.1)**: fixed a real defect found during v2.15.0's own regression testing.
- **Search Bar Isolation + MRP/Rate + Return Medicine (v2.16.0 / Phase 12)**: independent search-bar widget keys for Products/Expiry Alerts/Low Stock; MRP/Rate added to Product Management's product list; "Return Medicine" action added to Expiry Alerts (quantity forced to 0, record preserved).
- **Expiry Alerts Expand/Return + MRP/Rate Everywhere + Stock-Lot Merge/FIFO (v2.17.0 / Phase 13)**: see "Phase 13 Summary" above.
- **Extraction-Only Change: OCR-Hint Removal + Confidence-Color Removal + New Vision Prompt (v2.18.0 / Phase 14)**: see "Phase 14 Summary" above.
- **Four Surgical Bug Fixes: Dashboard Stale Expiry Alert, Invoice Duplicate-Row Save Merge, Sales Search FIFO Exposure, Product Form Data Loss on Validation Failure (v2.19.0 / Phase 15)**: see "Phase 15 Summary" above.
- **Zero-Quantity Medicine Replacement + Supabase Authentication Migration + Gemini Positional-Integrity Rule (v2.20.0 / Phase 16)**: see "Phase 16 Summary" above.
- **Strict Arrival-Order FIFO + Supabase Session Persistence + Startup Race Fix + Emergent Preprocessing + Low Stock Global Minimum + Decimal TQT Precision (v2.21.0 / Phase 17, current)**: see "Phase 17 Summary" above.

Three modules remain unbuilt placeholder packages.

## v2.15.0 / v2.15.1 - Phase-by-Phase Summary

- **Phase 1 - Full-invoice EasyOCR hint**: wired the isolated `row_ocr.py` into `ocr_service.py`'s single `generate_content()` call as a secondary, explicitly non-authoritative text hint alongside the full invoice image. EasyOCR failure/absence falls back to the original Gemini-only 2-part call.
- **Phase 2 - Structured OCR evidence**: `row_ocr.extract_evidence()` added (text + bbox + confidence per detection, `detail=1`); `extract_text()`'s existing interface/output rebuilt on top of it, unchanged for existing callers, EasyOCR now runs once per invoice instead of twice.
- **Phase 3 - EasyOCR failure fallback audit**: confirmed (no code change needed) that every failure mode - package missing, import failure, model-load failure, runtime exception, malformed/empty result - already safely degrades to Gemini-only extraction via the one existing try/except boundary.
- **Phase 4 - Gemini input enhancement audit**: confirmed (no code change needed) that Phase 1 already satisfied this phase's full requirements - image as source of truth, OCR as labeled non-authoritative hint, single call, all four required test cases passing.
- **Phase 5 - Field Evidence / Risk engine**: new `field_evidence.py`, `build_field_evidence()` attaches `_field_evidence` metadata per row/field (`gemini_value`, `ocr_evidence`, `ocr_confidence`, `evidence_type`, `validation_result`, `risk_level`) - purely additive, reuses the same OCR evidence already fetched, reads (never mutates) the existing validation rules via a deep copy.
- **Phase 6 - Validation integration**: added `INVALID_EXPIRY_FORMAT` as validation.py's 8th advisory rule, reusing `utils.validators.is_valid_expiry()` (the project's existing single canonical expiry validator) - no new date logic. `field_evidence.py`'s flag mapping updated to include it.
- **Phase 7 - Review UI risk coloring**: `_render_field_risk_css()` added to `review_ui.py`, reusing the existing scoped-CSS pattern; green/yellow/red backgrounds read directly from `_field_evidence[field]["risk_level"]`, text forced dark; friendly label + RED/YELLOW overlap suppression added for `INVALID_EXPIRY_FORMAT`.
- **Phase 8 - Save/Clear/session audit**: confirmed (no code change needed) that every requirement - no DB write before Save, partial-save safety with per-row error reporting, Clear Review's full reset, navigation persistence, SHA-256-only identity - was already correctly implemented by the existing, previously-stabilized (v2.13.2-v2.13.6) architecture.
- **Phase 9 - Complete testing**: ran the full available test suite via a local harness (real pytest unavailable, no network); found and corrected 20 pre-existing stale test assertions in `tests/test_review_service.py` (message-wording/required-field drift predating this release); found one real defect (preprocessing).
- **Phase 9.1 - Preprocessing fix**: see below.
- **Phase 10 (this entry)**: final regression, documentation update, packaging.

## Preprocessing Fix (v2.15.1, Phase 9.1)

**Defect**: `geometry._find_largest_quadrilateral()` accepted a small/spurious 4-point contour as the invoice's document boundary (prior check was only `contourArea < 1`) and passed it to `correct_perspective()`. On a real photographed invoice (`IMG20260616160324.jpg`, 3072x4096), the accepted quadrilateral measured 0.52% of the frame, and the resulting warp destroyed the image to an unusable 86x786 sliver.

**Fix**: added `_MIN_QUADRILATERAL_AREA_RATIO = 0.20` - a candidate quadrilateral covering less than 20% of the full image area is rejected before warping, falling through to the existing safe fallback (original image preserved). Verified: the proven-failing image now stays 3072x4096; a previously-successful image (`IMG20260728170635.jpg`) is unaffected; a legitimate large synthetic quadrilateral (70.4% of frame) is still detected and correctly warped.

**Files modified**: `modules/invoice_scan/preprocess/geometry.py` only. New test: `tests/test_preprocess_geometry_regression.py`.

**Note on "old stable version" comparison**: the project owner supplied a previous preprocessing version for comparison; it was found byte-for-byte identical to the then-current files, so the fix is based on direct root-cause tracing against the real failing image, not on restoring old behavior.

## Stable Modules (unchanged this release)

- Login, Dashboard, Product Management, Expiry Alerts, Low Stock Alerts, Sales.
- Upload flow, Save/Clear/session lifecycle, database schema, APIs, Gemini prompt/model/call-count, TQT formula, all 7 pre-existing validation rules.

## OCR Accuracy Status

Full-invoice EasyOCR hint now reaches Gemini in the single existing call, labeled non-authoritative. No row detection, no row cropping, no row-wise OCR anywhere in the project. Real-world extraction-accuracy impact of the hint (does it measurably help Gemini on genuinely difficult invoices?) remains unverified beyond structural/simulated testing - no live Gemini call could be made in this working environment (no network/API key).

## Known Limitations

- `pytest`, real `streamlit` (and therefore `streamlit.testing.v1.AppTest`), `supabase`, `google.genai`, `bcrypt`, and `PyMuPDF` remain uninstallable in this working environment (no network access) - same limitation as every release since v2.13.0. Verification continues via a local harness that executes the project's actual, unmodified test code (real assertions, real source) against real `sqlite3`, plus direct logic simulation for anything needing `streamlit`/`google.genai`/`easyocr` themselves.
- `test_expiry_alerts.py`, `test_low_stock_alerts.py`, `test_products_ui_threshold_checkbox.py` cannot execute at all in this environment (require real `streamlit.testing.v1.AppTest`) - confirmed unrelated to this release (the modules they test were never touched).
- Two `test_ocr_service.py` PDF-rasterization tests remain blocked by PyMuPDF's absence (unrelated to this release, known since v2.13.0).
- EasyOCR's actual model has never been downloaded/run in this working environment (no network) - its integration into the Gemini call is verified structurally and via simulation, not via a live OCR pass on a real invoice.
- No live Gemini call has been made against a real invoice image in this working environment (no API key/network) - `qty`/`free`/`tqt`/OCR-hint extraction accuracy on real invoices remains unverified beyond prompt inspection and simulation, a limitation carried forward from v2.14.0.
- No change to database, repository, or API contracts was made in any phase of this release.

## Current Architecture State

```
Invoice -> Frozen Preprocessing (now with Phase 9.1's quadrilateral-area guard)
        -> Full invoice image --+-------------+
                                 |             |
                            EasyOCR       (same image)
                                 |             |
                          OCR evidence         |
                       (text/bbox/conf)        |
                                 +------+------+
                                        v
                                ONE Gemini call
                        (image = source of truth,
                         OCR hint = non-authoritative)
                                        v
                                Structured JSON
                                        v
                      TQT Formula (quantity = tqt, else qty+free, else qty)
                                        v
                    Field Evidence / Risk (_field_evidence, per field)
                                        v
                           Review Session -> Review UI
                      (risk backgrounds: green/yellow/red)
                                        v
                            Validation (7 + INVALID_EXPIRY_FORMAT)
                                        v
                Save -> Stock-Lot identity/merge (products/service.py,
                new this phase - everything above this line is unchanged)
                                        v
                                    Database
```

## Current Test Status

- **Real `pytest` + real `streamlit` (including `streamlit.testing.v1.AppTest`) ARE installable in this working environment** (unlike every prior documented release since v2.13.0, which had no network access and relied on a local harness/simulation). Full suite run directly: **130 passed, 5 failed, 6 errors, 2 skipped.**
- Confirmed byte-for-byte identical failure/error/skip set on a pristine, unmodified Phase 12 baseline copy run in this same environment before any Phase 13 change was made: same 5 failures, same 6 errors, same 2 skips, same 130 passes. **Zero new failures introduced by Phase 13.**
- The 5 failures + 6 errors are a pre-existing environment/test-harness artifact unrelated to any application code: `streamlit.testing.v1.AppTest.from_file("app.py")` resolves the given path relative to the *calling test file's directory* (`tests/`), producing `tests/app.py`, which does not exist (the real `app.py` is at the project root) - this affects every test in `test_expiry_alerts.py::TestExpiryAlertsUIRendersCorrectly`, `test_low_stock_alerts.py::TestLowStockUIRendersCorrectly`, and all of `test_products_ui_threshold_checkbox.py`, identically on both the baseline and Phase 13 code. Not modified, per this phase's explicit scope (no test-file changes).
- The 2 skips are `test_preprocess_geometry_regression.py` tests requiring real invoice image fixtures not present in this environment (pre-existing, unrelated to this phase).
- 23 additional focused checks were run directly against the new Phase 13 service-layer functions (exact-lot merge, different-batch/different-expiry separation, zero-quantity-lot reuse with no duplicate row, FIFO consumption across two lots including a sale that spans both lots, zero-quantity lot excluded from `get_lots_by_name_sorted_by_expiry` while remaining in the database, `get_sellable_stock` aggregation, overselling-beyond-total-stock rejection, missing-batch possible-match detection, MRP/Rate present in repository query output, and Return Medicine's disappearance from Expiry Alerts without deletion) - **all 23 passed.**
- One real code defect was found and fixed in v2.15.1 (preprocessing) - zero known real code defects remain as of v2.17.0 (the missing-batch-confirmation gap is a documented, deliberate scope limitation, not a defect).
- Full regression re-confirmed after Phase 13's changes: single Gemini call, `MEDICINE_FIELDS` schema, TQT formula, field evidence/risk classification, expiry validation, Review UI risk coloring (RED/YELLOW/GREEN only, no 4th state), Save/Clear/session/SHA-256 behavior, and Phase 12's `return_medicine()` behavior (quantity to 0, record preserved) - all confirmed intact.

## Current Known Issue

**By-design limitation** (not a defect): missing-batch confirmation is implemented but unreachable via the invoice Scan Save button because the existing, protected blocking Batch Number requirement in `review_service.validate_medicine()` was intentionally left untouched this phase. See "Phase 13 Summary" above.

## Last Stable Release

**Version**: 2.17.0

**Summary**: Expiry Alerts rows now expand like Product Management's (Return Medicine hidden until expanded, medicine disappears from Expiry Alerts once quantity is 0 without being deleted); MRP/Rate now shown in Expiry Alerts, Low Stock, Sales, and Dashboard (Product Management already had it); new centralized stock-lot identity/merge system in `products/service.py` (exact match merges quantity, different batch/expiry stays separate, a zero-quantity lot is reused rather than duplicated, a missing-batch possible match asks for confirmation); Sales now consumes stock FIFO (earliest expiry first) across all lots of a medicine, splitting into multiple `sales_history` rows when a sale spans lots. No change to invoice preprocessing, OCR, Gemini extraction/prompt, field evidence, validation, Review UI risk coloring, database schema, or APIs.

## Next Planned Release

**Version**: Not formally committed. See `NEXT_TASK.md` for candidate future work, including the missing-batch-confirmation reachability question above.

## Current Priority

- **High**: None currently blocking.
- **Medium**: A real `streamlit run` / live Gemini API / real EasyOCR model manual verification in a networked environment for the invoice-scan pipeline (unchanged this phase, still only simulation-verified per prior releases' notes). Decide whether to relax the blocking Batch Number rule so missing-batch confirmation becomes reachable (see Known Limitation).
- **Low**: The `AppTest.from_file("app.py")` relative-path test-harness issue described in "Current Test Status" (pre-existing, affects 3 test files, unrelated to any release's application code); real invoice extraction-accuracy measurement for the EasyOCR hint's actual benefit to Gemini.

## Project Health

- **Architecture**: Preserved throughout. Phase 13's stock-lot rules live in exactly one new, clearly-bounded section of `modules/products/service.py`, per the requirement that future stock-rule changes should mean editing one place, not hunting across UI files.
- **Code Quality**: Surgical - full-project diff after Phase 13 shows exactly 10 modified files (see `CHANGELOG.md`'s `[2.17.0]` entry for the list) and zero unexpected changes; every protected file (`preprocess/geometry.py`, `validation.py`, `ocr_service.py`, `row_ocr.py`, `field_evidence.py`, `utils/validators.py`, `config/alert_theme.py`, `config/product_schema.py`, `core/database.py`, `database/supabase_schema.sql`, `app.py`, and `review_service.py`'s `validate_medicine` function specifically) was confirmed byte-identical to the Phase 12 baseline.
- **Testing**: 130 passed / 5 failed / 6 errors / 2 skipped, byte-identical failure set to the Phase 12 baseline in this same environment - zero new failures. 23/23 new focused Phase 13 checks passed.
- **Documentation**: `CHANGELOG.md`, `PROJECT_MEMORY.md`, `NEXT_TASK.md`, and this file all updated for v2.17.0.
- **Overall Stability**: Stable. One by-design, explicitly-flagged limitation (missing-batch confirmation unreachable pending a future decision on the blocking Batch Number rule) - no other known issues.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
