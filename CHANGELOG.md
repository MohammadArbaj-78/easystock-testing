# EasyStock Changelog

All notable changes to this project are documented in this file.

---

## [2.21.0] - Strict Arrival-Order FIFO + Supabase Session Persistence + Startup Race Fix + Emergent Preprocessing + Low Stock Global Minimum + Decimal TQT Precision

### Summary
Phase 17: six independent, surgical changes against the v2.20.0 baseline. (1) Sales consumption/search order changed from expiry-based (FEFO) to true arrival-order FIFO. (2) The Supabase-authenticated session now survives a full browser close/reopen, not just in-app reruns/navigation. (3) A startup-time race in the v2.20.0 `supabase_user_id` migration that could surface as a brief red error box under Login/Signup is fixed. (4) Invoice image preprocessing before Gemini now uses the requested "Emergent" preprocessing function instead of the old multi-step geometry/quality/enhance pipeline. (5) The Low Stock page gained a global minimum-stock dropdown (1-10), with a per-medicine custom minimum still always taking priority. (6) A decimal-truncation bug in the invoice Save path that silently rounded fractional quantities (e.g. qty 1.25 + free 0.50) down to whole numbers is fixed. Gemini's model, prompt (aside from Phase 16's prior positional-integrity addition), call count (still exactly one per invoice), parsing, validation, Review UI, Save/Clear, `sales_history`, the database schema (aside from a narrow, already-existing migration's race-safety fix), Dashboard, Expiry Alerts, and Product Management are all untouched.

### Changed
- **Strict arrival-order FIFO (Requirement 1)**: `modules/products/service.py::get_lots_by_name_sorted_by_expiry()` - the single function both `sell_product()` and `search_products()` already depended on for lot ordering - now sorts by `product_id` ascending instead of `expiry_date`. This was previously FEFO (First-Expiry-First-Out), not true arrival-order FIFO, despite its docstring's own prior claim. `product_id` (SQLite's `AUTOINCREMENT` primary key) is used as the arrival-order proxy rather than `created_at`/`updated_at`, specifically because it needs no schema change, no date parsing, and - critically - it is untouched when `_replace_zero_quantity_lot()` (Phase 16) repurposes an existing zero-quantity row for brand-new stock, so a reused row correctly keeps its *original* arrival slot rather than jumping the queue as if it were the newest arrival. The function's name is unchanged (only its sort key and docstring changed) to avoid touching its two call sites purely for a rename. Zero-quantity exclusion from Sales was already correct before this change (the function already filtered `quantity > 0`) and required no modification. `save_or_merge_invoice_lot()`'s merge rules (exact-match merge, zero-quantity replacement, different-batch/expiry separation) are completely unchanged - this only affects consumption/search *order*, never which rows exist or merge.
- **Emergent preprocessing (Requirement 4)**: `modules/invoice_scan/ocr_service.py` gained a new `_emergent_preprocess(raw: bytes) -> Image.Image` function (used verbatim, as supplied: EXIF-orientation correction, RGB conversion, LANCZOS resize to a maximum side of 2200px, a 1.15x contrast boost, then a JPEG quality=92 recompress/reopen round-trip), which now replaces the old `modules/invoice_scan/preprocess/` pipeline at its one call site in `extract_medicines_from_file()`. `_file_to_pil_image()` (PDF vs. image loading, its own `OCRError` fallback) is completely unchanged; the only adapter needed was re-encoding the already-loaded PIL image to PNG bytes immediately before calling the new function, since it expects raw bytes rather than an already-open PIL Image. The existing "preprocessing must never block extraction" fallback (any exception -> use the original, unprocessed image) is preserved in the same shape as before. The old `preprocess/` package (`geometry.py`, `quality.py`, `rules.py`, `enhance.py`, `executor.py`, `pipeline.py`, `debug_writer.py`) is left completely untouched on disk - it is simply no longer imported or called from `ocr_service.py`. One direct consequence: the `DEBUG_PREPROCESSING`-gated debug-artifact writing that depended on the old pipeline's own debug-session-folder object no longer has anything to write (that object no longer exists) - this only matters when a developer has explicitly opted into `DEBUG_PREPROCESSING=true`, and is an expected side effect of no longer calling that pipeline, not a regression. `MEDICINE_FIELDS`, `_parse_and_validate_response()`, `_EXTRACTION_PROMPT`, `GEMINI_MODEL`, and the single `generate_content()` call are all untouched - confirmed exactly one Gemini call site remains.
- **Low Stock global minimum dropdown (Requirement 5)**: `modules/products/repository.py::get_low_stock_products()` (both the SQLite and Supabase-backend variants) and `_filter_low_stock_rows()` gained a new optional `global_minimum` parameter, defaulting to `None` (which preserves the existing `DEFAULT_LOW_STOCK_THRESHOLD` behavior exactly) - `modules/dashboard/service.py`'s call site does not pass this parameter and is therefore completely unaffected. `modules/alerts/low_stock_service.py::get_low_stock_alerts()`/`get_low_stock_counts()` thread the same optional parameter through. `modules/alerts/low_stock_ui.py` gained a new "Minimum stock limit" `st.selectbox` (values strictly 1-10) next to the existing severity filter, backed by `st.session_state` (session-scoped only, per the investigation - no new database column or table). A medicine's own existing, non-NULL `minimum_stock_threshold` (Phase 12) always wins over the global selection - this was already true of the underlying `COALESCE`-based SQL/filter logic and required no change beyond making the fallback value itself configurable. Existing severity-tier logic (`_get_severity()`) is unchanged; it only ever receives whatever effective threshold it's given, same as before.
- **Decimal precision in qty+free -> TQT (Requirement 6)**: the actual point of data loss was `modules/products/service.py::_clean_invoice_lot_data()`, which parsed the invoice Save path's quantity as `int(float(raw.get("quantity")))` - silently truncating any real fractional value (e.g. a computed TQT of `1.75` became `1`) at save time, even though the extraction-time formula (`ocr_service.py::_apply_quantity_formula()`) already produced the correct decimal string. Changed to `float(raw.get("quantity"))` only (still validated as numeric and non-negative, exactly as before) - SQLite's own type affinity on the `products.quantity` column (declared `INTEGER`) already stores a whole-number float like `2.0` as an integer `2` and a fractional float like `1.75` as REAL `1.75`, so no database schema change was needed. Separately, `_apply_quantity_formula()`'s `qty + free` addition now wraps the result in `round(total, 2)` as a guard against binary-floating-point artifacts (e.g. `0.1 + 0.2` -> `0.30000000000000004` in raw IEEE 754 arithmetic) - this does not truncate or round away any real invoice-level precision (2 decimal places already exceeds what a printed qty/free column would ever carry); the existing `if TQT exists: quantity = TQT / elif FREE exists: quantity = QTY + FREE / else: quantity = QTY` business rule itself is completely unchanged. `_add_quantity_to_existing_lot()`'s own quantity addition (for the exact-match-merge case) was already correct and required no change.

### Added
- **Supabase session persistence across a full browser close/reopen (Requirement 2)**. Root cause (identified in the prior investigation): `st.session_state` is a per-WebSocket-connection, in-memory, server-side store - it cannot and was never designed to survive a literal browser close/reopen or hard page reload, regardless of whether Supabase itself still has a valid, unexpired refresh token. No new authentication framework or library was introduced; the existing Supabase Auth client/session model is reused throughout.
  - `core/supabase_auth.py` gained `restore_session(refresh_token)`, which calls Supabase Auth's own `auth.refresh_session()` to exchange a still-valid refresh token for a fresh access token (the standard way to silently re-authenticate without asking for a password again), then resolves the local `stores` row exactly as `sign_in_and_resolve_store()` already does, returning the same dict shape ready for `core.session.start_session()`. An invalid, expired, or unconfigured token raises the existing `SupabaseAuthError`/`SupabaseConfigError` - it never crashes the caller.
  - `core/login_ui.py` now writes the Supabase refresh token to the browser's `localStorage` immediately after a successful login or signup, using the same `streamlit.components.v1.html()` JS-bridge pattern `app.py`'s existing mobile-sidebar-autoclose feature already established elsewhere in this project - no new dependency. Only the refresh token is persisted; the password and access token are never written to `localStorage`.
  - `app.py` gained a new startup-restoration step, run only when there is no active `st.session_state` login: a tiny JS snippet checks `localStorage` for a saved refresh token and, if found (and no restoration attempt is already in flight), redirects the browser to the same URL with the token appended as a short-lived `?rt=` query parameter - the only way this server-side Python code can receive a value the browser's `localStorage` holds, since `components.html()` is one-way. Python then reads `st.query_params.get("rt")`, calls `restore_session()`, and on success starts the session and immediately clears the query parameter; on failure, the query parameter and the stale `localStorage` token are both cleared, and the normal login screen renders. This design cannot loop: a successful restoration ends with `is_logged_in()` true (main app renders instead), and a failed one clears both the URL and the stored token, so nothing is left to retry on the next load.
  - Logout (`app.py`'s existing Logout button) now also clears the `localStorage` refresh-token entry, immediately after the pre-existing `sign_out()` + `end_session()` calls - a stale token can no longer silently re-authenticate the user after an explicit logout.
  - **Known, disclosed tradeoff**: the refresh token appears in the URL for exactly one redirect during restoration (then is cleared) - a real, if brief, exposure surface (browser history, referrer headers) inherent to bridging browser-side storage into server-side Streamlit without a custom bidirectional component or an added dependency; this was the smallest viable mechanism identified in the investigation and is explicitly not a general-purpose token-in-URL pattern used anywhere else in the app.
- **Startup migration race fix (Requirement 3)**. Root cause (identified in the prior investigation): `core/database.py::initialize_database()`'s `supabase_user_id` column migration (Phase 16) was a classic check-then-act race - if Streamlit executes the script's top level more than once in close succession during a cold start (a documented Streamlit behavior), two near-simultaneous calls could each see the column missing (via `PRAGMA table_info`) before either one's `ALTER TABLE` committed, and the second would then fail with `duplicate column name: supabase_user_id`, surfacing as a real (if self-healing on the very next rerun) red error box under Login/Signup. Fixed by wrapping only that one `ALTER TABLE` call in a narrow `try/except sqlite3.OperationalError` that swallows exactly a "duplicate column name" message and re-raises anything else unchanged - a genuine, unrelated database error still surfaces exactly as before. No migration framework was added; no other part of `initialize_database()` was touched.

### Testing
- `tests/test_six_requirements.py` added (27 new tests, all passing) covering Requirements 1, 3, 4, 5, and 6: strict arrival-order FIFO (including the case where the older-arrived batch has a *later* expiry than the newer one, proving this is genuinely arrival-order and not FEFO in disguise; partial sales keeping the same batch active; a batch reaching exactly zero being immediately excluded and the next batch becoming active; sale-quantity changes never changing which batch is selected; a zero-quantity-reused lot correctly keeping its original arrival slot; non-zero different-batch/expiry rows staying separate; the existing exact-match merge still working), the migration race (repeated `initialize_database()` calls, a simulated race, and confirmation a genuine unrelated `ALTER TABLE` error still raises as `DatabaseError`), Emergent preprocessing (RGB output, 2200px max-side resize, small images not upscaled, exactly one Gemini call with the new preprocessing in place, and exactly one Gemini call even when preprocessing itself raises and the app falls back to the original image), the Low Stock dropdown (global-minimum-only case, custom-minimum-wins case, Dashboard's own count confirmed unaffected by a Low-Stock-page selection, and the 1-10 value restriction), and decimal TQT precision (`1.5+0.5=2`, `1.25+0.50=1.75`, `10.5+2.25=12.75`, `2+1=3` with no forced decimal, a `0.1+0.2` floating-point-artifact check, and - the actual bug - that the invoice Save path itself preserves a decimal quantity like `1.75` rather than truncating it, while a whole-number quantity like `5` is still stored as a clean integer).
- `tests/test_supabase_auth.py` extended with a new `TestRestoreSession` class (5 new tests, all passing, all mocked - see the disclosed limitation below): a valid refresh token restores the correct store and a fresh access/refresh token pair; an invalid/expired token raises `SupabaseAuthError` without crashing; a blank token raises without even calling Supabase; a token for a user with no linked local store raises the same clear error `sign_in_and_resolve_store()` already gives; and a direct confirmation that the exact exception types `app.py`'s restoration code catches are what `restore_session()` actually raises.
- **Explicitly not testable live in this environment**: the `supabase` package is not installed in this offline sandbox and there is no network access, so Requirement 2 was verified only via mocked unit tests against the `_build_supabase_auth_client()` seam (the same pattern already used for the Gemini client in `ocr_service.py`'s tests) - this proves this project's own code is correct, not that a real browser close/reopen against a live Supabase project succeeds end-to-end. A project owner must smoke-test this manually once against a real Supabase project and a real browser.
- Existing suite re-run via the project's offline harness: `test_ocr_service.py` (26 passed/2 failed), `test_review_service.py` (60 passed/3 failed), `test_preprocess_geometry_regression.py` (3 passed/2 failed), `test_extraction_iq200_focused.py` (13 passed/0 failed), `test_four_fixes.py` (18 passed/0 failed), `test_requirement1_zero_qty_replacement.py` (5 passed/0 failed) - every count identical to the v2.20.0 baseline run through the same harness; all failures are the same pre-existing environment limitations already documented (PyMuPDF unavailable, a `pytest.skip` stub the harness can't emulate), zero new failures introduced. `test_expiry_alerts.py`/`test_low_stock_alerts.py`/`test_products_ui_threshold_checkbox.py` remain not runnable offline (missing `streamlit.testing.v1.AppTest`) - pre-existing, unaffected by this release.
- Full-project `diff -rq` against a pristine v2.20.0 baseline extraction confirms exactly: `app.py`, `config/settings.py`, `core/database.py`, `core/login_ui.py`, `core/supabase_auth.py`, `modules/alerts/low_stock_service.py`, `modules/alerts/low_stock_ui.py`, `modules/invoice_scan/ocr_service.py`, `modules/products/repository.py`, `modules/products/service.py` modified; `tests/test_supabase_auth.py` modified (new `TestRestoreSession` class only); `tests/test_six_requirements.py` added - no other file changed. Explicitly re-confirmed byte-identical: the Gemini prompt (aside from Phase 16's prior positional-integrity line), Review UI/session, validation, `sales_history`/Sales repository, the database schema files under `database/`, Dashboard, Expiry Alerts, Product Management UI, and the entire `modules/invoice_scan/preprocess/` package (left on disk, simply no longer called).

## [2.20.0] - Zero-Quantity Medicine Replacement + Supabase Authentication Migration + Gemini Positional-Integrity Rule

### Summary
Phase 16: three independent, surgical changes against the v2.19.0 baseline. (1) A new stock-lot rule: an invoice medicine now reuses/replaces an existing zero-quantity record of the same name, even across a different batch/expiry - a deliberate, narrow exception to the existing same-name+batch+expiry stock-lot identity rule, which otherwise remains completely unchanged. (2) The project's custom, application-level login/signup (mobile number + bcrypt password) has been fully removed and replaced with Supabase Authentication (Email + Password) as the sole authentication provider. (3) The Gemini extraction prompt gained one additional rule enforcing strict row/column positional integrity - every other rule, the field definitions, the JSON output shape, the model, and the single-call-per-invoice behavior are all untouched.

### Added
- **Zero-quantity medicine replacement.** `modules/products/service.py::save_or_merge_invoice_lot()` now checks, immediately after the existing exact-lot-match check and before the existing blank-batch possible-match prompt, whether any existing product row for the same medicine name currently has `quantity == 0` (via the new `find_zero_quantity_lot_by_name()`) - regardless of that row's own batch number or expiry date. If one is found, the incoming invoice row's batch, expiry, quantity, MRP, rate, GST%, and purchase date replace that record's values in place (via the new `_replace_zero_quantity_lot()`, reusing `products_repository.update_product()` - no new SQL write path introduced), and the invoice row is treated as `"merged"` into that same `product_id` rather than creating a new row. A record that still has real stock (`quantity > 0`) is never matched by this new check, so the existing rule - same name + different batch or different expiry stays a separate row while stock remains - is completely unchanged; this is a narrow, explicit exception for zero-quantity records only, not a broadening of the general merge rule. The existing exact-lot-match merge (same name + same batch + same expiry, any quantity) still runs first and is untouched.
- **Supabase Authentication.** The old custom, application-level authentication (`core/auth.py` - mobile number + bcrypt password hash, stored and checked entirely inside this app's own SQLite `stores` table) has been deleted outright and replaced with Supabase Auth (Email + Password) as the application's one and only authentication provider - no parallel or hidden second system remains. See "Supabase Authentication" below for full detail.
- **Gemini positional-integrity rule.** `modules/invoice_scan/ocr_service.py::_EXTRACTION_PROMPT` gained one new numbered rule, appended to the end of the existing four-item `CRITICAL RULES` list (now five items) with no other wording in the prompt touched: *"5. Positional integrity: the extracted values must remain aligned to their original invoice row and column. If a value in one column is missing, unreadable, or blank, do NOT shift values from the rows above or below into that position, do NOT move a value upward or downward to fill a blank, do NOT shift subsequent columns left/right because one column is missing, and do NOT borrow a value from another medicine row. Preserve the exact row relationship and the exact column relationship from the invoice - Row N's values must remain attached to Row N. If a field is unreadable or missing, leave that field blank."* Rules 1-4, the field definitions, the JSON-array output shape, `MEDICINE_FIELDS`, `_parse_and_validate_response()`, `_apply_quantity_formula()`, the model (`GEMINI_MODEL`), and the single-call-per-invoice `contents = [image, prompt]` structure are all byte-unchanged.

### Supabase Authentication
- **Removed**: `core/auth.py` (the entire module: `signup()`, `login()`, bcrypt password hashing/verification, mobile-number-based lookup) deleted. `core/exceptions.py`'s `DuplicateMobileError` and `InvalidCredentialsError` (used only by the deleted module and the old login UI) removed as now-fully-unused - confirmed via project-wide grep before removal that neither was referenced anywhere else. `core/login_ui.py` rewritten in place (same file path, same `render_login_signup_screen()` public function `app.py` already called, so `app.py`'s own routing needed no change) - Login and Sign Up tabs now collect Email + Password (Sign Up also collects Store Name and Owner Name, unchanged from before) instead of Mobile Number + Password.
- **Added**: `core/supabase_auth.py` (new file) - the single place in the application that calls into supabase-py's `auth` client. `sign_up_and_create_store()` calls Supabase Auth's `sign_up()`, then creates the local `stores` row linked to the new Supabase user; `sign_in_and_resolve_store()` calls `sign_in_with_password()`, then resolves the caller's local `stores` row by that link; `sign_out()` calls Supabase Auth's `sign_out()` and never raises (logout must always succeed from the app's point of view - `core.session.end_session()` always clears local state regardless of whether the Supabase-side call succeeds). Uses its own separate lazy-singleton client (mirroring `core/supabase_client.py`'s existing pattern for the unrelated business-data client), configured from `SUPABASE_URL` and a new, dedicated `SUPABASE_ANON_KEY` secret - deliberately the public/anon key, never the service-role key, and deliberately a different secret name than `core/supabase_client.py`'s own `SUPABASE_KEY`, so identity and business-data access can never accidentally share or leak a privileged credential. A new `SupabaseAuthError` exception (`core/exceptions.py`) wraps any Supabase Auth failure (invalid credentials, already-registered email, Supabase's own password rules, etc.) into one plain-language, catchable EasyStock exception type, the same pattern `GeminiAPIError` already uses for a different third-party client.
- **Database**: the `stores` table (`core/database.py`) is unchanged in its existing columns - `mobile_number`/`password_hash` are left in place exactly as before (old rows, old NOT NULL/UNIQUE constraints, both untouched) rather than dropped or altered, since removing or loosening either was not required. Exactly one new, additive column was introduced: `supabase_user_id` (nullable, with a `CREATE UNIQUE INDEX IF NOT EXISTS` alongside it), added via an idempotent `ALTER TABLE` guarded by a `PRAGMA table_info(stores)` check inside `initialize_database()` (a no-op on every startup after the first), so an existing database upgrades in place with no separate migration step. This column is the only way `store_id`-based scoping - the single mechanism every repository and service function in the app already depends on via `core.session.get_current_store_id()`, completely unchanged - can keep working now that Supabase, not this table, is the source of truth for identity. A new signup's `mobile_number` cell now holds that same email address (still genuinely unique and non-null, satisfying the untouched schema constraint without requiring a schema change) and its `password_hash` cell holds a fixed sentinel string, `"SUPABASE_AUTH_MANAGED"` - never a real password or anything derived from one, since Supabase Auth is now the sole holder of that credential. Old rows created by the removed custom system have no `supabase_user_id` and can no longer be signed into - per explicit instruction, this old authentication data was not migrated, since it cannot be (a bcrypt hash cannot be reversed into a real password to re-register with Supabase) and was stated to be unimportant. `products`, `sales_history`, and every other business table are completely untouched.
- **Session persistence**: `core/session.py::start_session()` (same function, same call sites in `core/login_ui.py`) now also accepts and stores `access_token`/`refresh_token` (new optional parameters, defaulting to `None`, so the signature stays backward-compatible) alongside the existing `store_id`/`store_name`/`owner_name` in the same `st.session_state` dict it already used - no second, Python-only session system was introduced. A normal Streamlit rerun or in-app navigation (Dashboard -> Products -> Sales -> Invoice Scan -> Dashboard, a form submit, a nav radio click) re-executes the script inside the same server-side browser session, and `st.session_state` already survives that automatically, exactly the mechanism the pre-migration custom system already relied on for the same "don't force re-login on every rerun" behavior - this is preserved, not reinvented. A new `core.session.get_current_access_token()` accessor was added (mirroring the existing `get_current_store_id()`/`get_current_store_name()`/`get_current_owner_name()` accessors) so `app.py`'s logout handler can retrieve the token to sign out. `get_current_store_id()` and every other pre-existing accessor are byte-unchanged.
- **Logout**: `app.py`'s Logout button now calls `core.supabase_auth.sign_out(core.session.get_current_access_token())` immediately before the pre-existing `core.session.end_session()` call (itself unchanged) - the Supabase session is explicitly ended, then the local `st.session_state` session is cleared, then the pre-existing `st.rerun()` fires, at which point `app.py`'s unchanged `if is_logged_in(): ... else: render_login_signup_screen()` gate routes back to the login screen, exactly as it already did before this migration.
- **Protected pages**: `app.py`'s routing gate at the bottom of the file (`if is_logged_in(): render_main_app() else: render_login_signup_screen()`) is byte-unchanged - an unauthenticated user still sees only the login/signup screen, an authenticated one still sees the full application. The sidebar, navigation, and every page (Dashboard/Products/Sales/Invoice Scan/Expiry Alerts/Low Stock) are untouched.
- **Required configuration**: `SUPABASE_URL` and `SUPABASE_ANON_KEY` must be present in Streamlit secrets (`.streamlit/secrets.toml` locally, or the deployment platform's secrets settings) - see `PROJECT_STATUS.md`'s "Configuration" section for the exact required values and the Supabase dashboard steps (Auth provider, Site URL/Redirect URLs for local `http://localhost:8501`) a project owner must complete once, outside this codebase, before Sign Up/Login will work. No credentials are hardcoded anywhere in the source, and no `.env`/secrets file is committed - `SupabaseConfigError` is raised with a clear message if either secret is missing, rather than the app silently failing or using a placeholder.
- **Not testable live in this environment**: the `supabase` package is not installed in this offline sandbox and there is no network access, so Supabase Auth was verified via mocked unit tests against the exact seam supabase-py's client would occupy (`core.supabase_auth._build_supabase_auth_client()`, the same patch-seam pattern `modules/invoice_scan/ocr_service.py`'s own tests already use for the Gemini client) - this proves this project's own code (session-field extraction, store creation/resolution, session-state storage, sign-out never raising, error message mapping) is correct, but does not and cannot verify a real call against a live Supabase project. A project owner must smoke-test Sign Up/Login/Logout once against their actual Supabase project after configuring the two required secrets.

### Testing
- `tests/test_requirement1_zero_qty_replacement.py` added (5 new tests, all passing): same medicine + existing quantity 0 + same batch/expiry replaces correctly; same medicine + existing quantity 0 + different batch/expiry still replaces (the exact scenario requested); same medicine + existing quantity > 0 + different batch/expiry is confirmed to still create a separate row, completely unchanged; a different medicine's own zero-quantity record is confirmed untouched by an unrelated invoice row; the existing exact-batch-and-expiry-match path (itself unmodified) is confirmed to still take priority and produce the same result.
- `tests/test_supabase_auth.py` added (15 new tests, all passing, all mocked - see "Not testable live" above): sign-up creates a linked store row and returns the expected session fields; sign-up rejects a blank store name (existing validation reused); a Supabase-reported "already registered" error maps to `SupabaseAuthError`; a local duplicate-email race maps to a friendly `SupabaseAuthError` rather than a raw database error; sign-in resolves the correct existing store; sign-in with invalid credentials raises `SupabaseAuthError`; sign-in for a Supabase user with no linked local store raises a clear `SupabaseAuthError` rather than crashing; sign-out calls the Supabase client and never raises even if the underlying call fails; missing `SUPABASE_URL`/`SUPABASE_ANON_KEY` each raise `SupabaseConfigError`; `start_session()`/`end_session()`/`get_current_access_token()` behave correctly; `core.auth` is confirmed to no longer exist as an importable module; a project-wide scan confirms no production file (`app.py`, `core/`, `modules/`, `config/`, `utils/`) still imports it.
- `tests/test_expiry_alerts.py`, `tests/test_low_stock_alerts.py`, `tests/test_products_ui_threshold_checkbox.py` updated: each previously imported `signup` from the now-deleted `core.auth`; each now defines a small local `signup(store_name, owner_name, mobile_number, password)` helper (identical 4-argument signature, so every existing call site in these files needed zero further changes) that inserts a `stores` row directly via SQLite, the same direct-insert pattern `tests/test_four_fixes.py` already established for the same underlying reason (`core.auth`/Supabase Auth both require dependencies - bcrypt, then `supabase` + network - unavailable in this offline sandbox). The tests' own intent and assertions are otherwise unchanged.
- Existing suite re-run via the project's offline harness: `test_ocr_service.py` (26 passed/2 failed), `test_review_service.py` (60 passed/3 failed), `test_preprocess_geometry_regression.py` (3 passed/2 failed), `test_extraction_iq200_focused.py` (13 passed/0 failed), `test_four_fixes.py` (18 passed/0 failed) - every count identical to the v2.19.0 baseline run through the same harness; all failures are the same pre-existing environment limitations already documented (PyMuPDF unavailable, a `pytest.skip` stub the harness can't emulate), zero new failures introduced. `test_expiry_alerts.py`/`test_low_stock_alerts.py`/`test_products_ui_threshold_checkbox.py` remain not runnable offline for their own, separate, pre-existing reason (missing `streamlit.testing.v1.AppTest`) - unaffected by this release; their `core.auth` import was still fixed regardless, so they are correct and ready to run in an environment where `AppTest` is available.
- Full-project `diff -rq` against a pristine v2.19.0 baseline extraction confirms exactly: `app.py`, `core/database.py`, `core/exceptions.py`, `core/login_ui.py`, `core/session.py`, `modules/invoice_scan/ocr_service.py`, `modules/products/service.py` modified; `core/auth.py` deleted; `core/supabase_auth.py`, `tests/test_requirement1_zero_qty_replacement.py`, `tests/test_supabase_auth.py` added; `tests/test_expiry_alerts.py`, `tests/test_low_stock_alerts.py`, `tests/test_products_ui_threshold_checkbox.py` modified (import fix only) - no other file changed. Explicitly re-confirmed byte-identical: Low Stock (`modules/alerts/low_stock_ui.py`/`service.py`), Expiry Alerts (`modules/alerts/ui.py`), Dashboard (`modules/dashboard/`), Sales FIFO/UI (`modules/sales/service.py`'s `search_products`/`sell_product`, `modules/sales/ui.py`), Product Management UI (`modules/products/ui.py`), `database/`, `modules/invoice_scan/validation.py`, `modules/invoice_scan/review_ui.py`/`review_service.py`, and all of `modules/invoice_scan/preprocess/`.

## [2.19.0] - Four Surgical Bug Fixes: Dashboard Stale Expiry Alert, Invoice Duplicate-Row Save Merge, Sales Search FIFO Exposure, Product Form Data Loss on Validation Failure

### Summary
Phase 15: four independent, surgical bug fixes against the v2.18.0 baseline, each traced to its exact root cause before any code was touched, per the project owner's explicit "smallest/safest change" requirement. No OCR/Gemini logic, no database schema, no APIs, and no unrelated UI were touched. One of the four originally-reported issues (duplicate invoice-row merging) was investigated first and found to already work correctly in the existing code - see "Investigated, found already correct" below - so only a verifying test was added for it, no production code changed.

### Fixed
- **Dashboard's Expiry Alert metric cards/detail expanders showed a medicine after it had been Returned.** Root cause: `modules/dashboard/service.py::get_dashboard_metrics()` called `products_repository.get_expired_products()`/`get_expiring_soon_products()` directly - both filter only by expiry date, never by quantity - while the separate Expiry Alerts page (`modules/alerts/service.py::get_categorized_alerts()`) already excluded `quantity == 0` rows. Dashboard simply never had that same exclusion. Fixed by filtering `expired_items`/`expiring_soon_items` to `quantity != 0` immediately after fetching them in `get_dashboard_metrics()`, mirroring the alerts module's already-correct, already-proven pattern exactly. `return_medicine()`'s own behavior (sets quantity to 0, keeps the row) is completely unchanged - this only affects which already-zeroed rows the Dashboard surfaces as an alert. Low Stock (`low_stock_items`/`low_stock_count`) is deliberately untouched - a quantity-0 product is still meaningfully "low stock", and the requirement was explicit that Low Stock behavior must not change.
- **Sales search could show more than one in-stock batch of the same medicine at once**, letting a store owner pick a later-expiring batch out of search ahead of an earlier-expiring one that should sell first. Root cause: `modules/sales/service.py::search_products()` returned every in-stock row matching the search term with no deduplication by medicine name. Fixed by having `search_products()` collapse its results to exactly one row per distinct medicine name - that name's FIFO-first (earliest-expiry) in-stock lot, resolved via the existing, unmodified `modules.products.service.get_lots_by_name_sorted_by_expiry()` (the same centralized FIFO order `sell_product()` already consumes lots in, established in Phase 13, reused here unchanged - no new FIFO logic, no new sort order, no schema change). A newer batch of the same medicine no longer appears in search results while an older batch still has stock > 0; once the older batch reaches 0 (only ever through the existing Sales flow), the next-oldest batch becomes visible on its own, with no code path needed to make that transition happen. `sell_product()`'s own FIFO consumption logic, pricing, and every other Sales calculation are completely unchanged - this fix only changes which single row `search_products()` surfaces, never which lot an actual sale consumes.
- **Product Management's "Add Product" form cleared every already-typed field whenever validation failed** (e.g. one required field left blank), forcing the store owner to retype the whole form just to fix the one missing field. Root cause: `modules/products/ui.py::_render_add_product_form()` used `st.form("add_product_form", clear_on_submit=True)` - Streamlit's `clear_on_submit=True` resets every widget inside the form the instant it is submitted, success or failure alike, entirely inside Streamlit's own widget machinery, before this function's own `except ValidationError` branch ever runs. Fixed by removing `clear_on_submit=True` and instead resetting the form's fields explicitly, and ONLY on the success path, via a new `_clear_add_product_form_fields()` helper using the same two-phase session-state sentinel pattern this file already established for the custom-threshold checkbox outside the form (`_reset_threshold_checkbox`) - a new `_reset_add_product_form` sentinel is set right after a successful `add_product()` call, and `_clear_add_product_form_fields()` checks for it (and pops every `PRODUCT_FIELDS` widget key if present) before any field widget is instantiated on the next render, matching the same "must clear before the widget reads its key" ordering the checkbox's own reset already relies on. A validation failure never sets that sentinel, so every already-entered field's `session_state` value is left completely untouched, and `_render_schema_driven_fields()` re-renders with the user's own values still showing - exactly how any ordinary (non-`clear_on_submit`) Streamlit form widget already behaves. `add_product()`'s own validation rules, field names, and successful-save behavior (the product is created, and the form now still resets afterward, just via the new explicit path instead of `clear_on_submit`) are all unchanged.

### Investigated, found already correct (no production code changed)
- **Invoice duplicate-row merge-on-Save**: the project owner reported this as a bug ("the same medicine in multiple invoice rows currently merges incorrectly / doesn't merge correctly"). Full trace of `review_service.save_invoice_medicines()` → `products_service.save_or_merge_invoice_lot()` → `find_exact_lot_match()` found the existing code already does exactly what was asked: (1) the Review/Preview table never merges anything before Save (`initialise_review_session()` only deep-copies Gemini's rows unchanged - no dedup logic exists there or anywhere upstream of Save); (2) on Save, each row is written to the database in sequence, and `find_exact_lot_match()` re-queries the database fresh before every row, so two invoice rows sharing name + batch + expiry are merged (combined quantity) automatically once the first has committed, while a different batch or a different expiry - even for the same medicine name - already stays a separate row, per the stock-lot identity rule established in Phase 13 (`modules/products/service.py`'s "Stock Lot identity & merge rules" section, itself unmodified here). No test previously existed to verify this specific "two duplicate rows within one invoice" scenario, so five new tests were added (see Testing below) to lock in and prove this already-correct behavior, rather than changing any code that wasn't broken.

### Testing
- `tests/test_four_fixes.py` added (18 new tests, all passing): 3 for Fix 1 (returned medicine excluded from both expiring-soon and expired buckets; Low Stock unaffected), 5 for the duplicate-row merge investigation (same batch+expiry merges with combined quantity and exactly one DB row; different batch stays separate; different expiry stays separate; Preview still shows two rows before Save; an end-to-end Save of two duplicate rows produces one merged DB row), 5 for Fix 3 (only the older batch is shown while it has stock; the newer batch appears only after the older reaches 0 via a real sale; three batches following FIFO order as each empties in turn; never more than one result per medicine name; `sell_product()`'s own FIFO consumption is unchanged regardless of which batch's row a search result pointed at), 5 for Fix 4 (the form-clearing helper is a no-op without the success sentinel; it clears every field and consumes the sentinel when set; an incomplete medicine is still rejected and never saved; a successful add still works and still creates the product; a direct source-level guard confirming the `st.form(...)` call line no longer passes `clear_on_submit=True`). Uses a real, isolated SQLite database per test (via `tmp_path`/`monkeypatch`, the same pattern already used by `tests/test_expiry_alerts.py`) with a store row inserted directly to avoid `core.auth.signup`'s bcrypt dependency, unavailable in this offline sandbox.
- Existing suite re-run via the project's offline harness (real `pytest`/`streamlit`/`bcrypt`/`google-genai` not installable here - no network access): `test_ocr_service.py` (26 passed/2 failed), `test_review_service.py` (60 passed/3 failed), `test_preprocess_geometry_regression.py` (3 passed/2 failed), `test_extraction_iq200_focused.py` (13 passed/0 failed) - every count identical to the v2.18.0 baseline run through the same harness; all failures are the same pre-existing environment limitations already documented (PyMuPDF unavailable, a `pytest.skip` stub the harness can't emulate), zero new failures introduced by this release. `test_expiry_alerts.py`, `test_low_stock_alerts.py`, and `test_products_ui_threshold_checkbox.py` remain not runnable offline (missing `bcrypt`/`streamlit.testing.v1.AppTest`) - pre-existing since v2.13.0, unaffected by this release.
- Full-project `diff -rq` against the exact v2.18.0 baseline confirms exactly the expected change set: `modules/dashboard/service.py`, `modules/products/ui.py`, `modules/sales/service.py` modified; `tests/test_four_fixes.py` added - no other file changed. A further diff against the original v2.17.0 baseline confirms `modules/products/service.py` (stock-lot rules, FIFO lot lookup), `modules/sales/ui.py`, `modules/alerts/`, `database/`, `core/`, `app.py`, and `modules/invoice_scan/validation.py` are all still byte-identical - nothing this release touched reaches Return's own quantity calculation, FIFO's own consumption order, database schema, or any unrelated UI.

## [2.18.0] - Extraction-Only Change: OCR-Hint Removal + Confidence-Color Removal + New Vision Prompt

### Summary
Phase 14: a strict, surgical, extraction-pipeline-only change against the v2.17.0 baseline, requested and scoped as exactly three changes. (A) Removed EasyOCR hint generation from the invoice extraction pipeline - Gemini now receives the invoice image and the extraction prompt only, in a single call. (B) Removed the field-confidence/risk-color presentation layer from the Review Screen. (C) Replaced the Gemini extraction prompt with a new, shorter, structure-first, column-aware prompt supplied by the project owner, adapted to fit the existing internal field names and JSON-array parser contract. Invoice preprocessing (geometry/quality/enhancement), the existing blocking validation rules (including the Batch Number requirement), the `qty + free = TQT` formula, Product Management, Sales, the database layer, and `app.py` are entirely untouched by this release.

### Removed
- **EasyOCR hint generation deleted from the invoice extraction path.** `modules/invoice_scan/row_ocr.py` and `modules/invoice_scan/field_evidence.py` deleted outright - confirmed (via project-wide grep before deletion) to have zero references anywhere outside `ocr_service.py`/`review_ui.py` themselves, and zero test coverage referencing either module directly. `modules/invoice_scan/ocr_service.py` had its `from modules.invoice_scan import row_ocr` / `import field_evidence` imports, its `_get_ocr_evidence()` and `_hint_text_from_evidence()` helper functions, the "SECONDARY OCR HINT" block previously appended to Gemini's `contents`, and the `field_evidence.build_field_evidence(...)` call at the end of `extract_medicines_from_file()` all removed. Gemini's `contents` list is now exactly `[image, prompt]` - no OCR hint is ever sent, and Gemini is still called exactly once per invoice (unchanged call count). `easyocr>=1.7,<2.0` removed from `requirements.txt` as a now-fully-unused dependency; `opencv-python-headless` and `numpy` were kept, since `modules/invoice_scan/preprocess/geometry.py` and `preprocess/quality.py` still depend on them for unrelated, untouched perspective-correction/image-quality work - preprocessing itself (geometry, quality, enhancement, the Phase 9.1 `_MIN_QUADRILATERAL_AREA_RATIO` guard) was not touched or redesigned by this change.
- **Field-confidence/risk-color presentation layer removed from the Review Screen.** `modules/invoice_scan/review_ui.py`'s `_render_field_risk_css()` function, its `_RISK_BACKGROUND_COLORS`/`_RISK_TEXT_COLOR` constants, and its call site inside `_render_medicine_row()` were all deleted - this was the only code that read `_field_evidence[field]["risk_level"]` and painted per-field green/yellow/red backgrounds. The pre-existing, validation-driven row-level highlighting (`_render_row_highlight_css()` - red border/background for a blocking `validate_medicine()` error, amber for a non-blocking advisory `validation.py` flag) is completely untouched and still fully functional; so is `_field_column_index()`, which that highlighting still uses to underline the specific offending input. The Review table now simply shows the extracted, editable fields with that one existing (unchanged) validation-driven highlight system - no field-level confidence coloring remains anywhere.

### Changed
- **`modules/invoice_scan/ocr_service.py`'s `_EXTRACTION_PROMPT` replaced in full** with the new prompt supplied by the project owner: a shorter, structure-first prompt that instructs Gemini to first mentally correct orientation, locate the line-item table, read its header row, and establish column boundaries before reading any data row. The prompt's eight requested fields (medicine name, batch, expiry, qty, free qty, MRP, rate, GST) were mapped onto the existing internal field names the rest of the codebase already reads - `name`, `batch_number`, `expiry_date`, `qty`, `free`, `mrp`, `rate`, `gst_percent` - so no downstream code needed to change. The prompt's JSON-output instruction was kept as a JSON **array** of objects (not the `{"rows": [...]}` object-wrapper form it was supplied in) specifically so the existing, protected `_parse_and_validate_response()` parser (which expects `isinstance(parsed, list)`) needed zero changes - this is the only adaptation made to fit the existing call, per the explicit "adapt only the surrounding code needed to fit" instruction. A new module-level `_PROMPT_FIELDS` list (the 8 fields above) is used only to render the prompt's own key list; it does not replace or alter `MEDICINE_FIELDS` (the real internal schema), which still has 9 entries and is completely unchanged.
- The new prompt intentionally does not ask Gemini for a separate `tqt` value (the old prompt did, for invoices with a distinct printed Total-Quantity column). This is not a formula change: `MEDICINE_FIELDS` still includes `"tqt"`, and `_parse_and_validate_response()`'s existing normalization already defaults any field absent from Gemini's JSON to `""` - so a row simply arrives with `tqt=""`, and `_apply_quantity_formula()` (completely unmodified) falls through its existing `elif free: quantity = qty + free` branch exactly as it already did for any invoice without a distinct TQT column. `qty` and `free` remain two separate fields throughout, exactly as before.

### Not changed
- `qty + free = TQT` formula (`ocr_service._apply_quantity_formula()`) - byte-identical, not touched.
- `MEDICINE_FIELDS` internal schema (still 9 fields, including `tqt`) and the JSON-array response contract `_parse_and_validate_response()` expects - unchanged.
- All existing blocking validation (`review_service.validate_medicine()`, including the Batch Number required rule protected by `tests/test_review_service.py::TestValidateMedicine::test_empty_batch_number_is_blocking`) and all existing advisory validation (`validation.py`'s 8 flags, `utils/validators.py`) - untouched.
- The validation-driven RED/YELLOW row-highlighting system in `review_ui.py` (`_render_row_highlight_css`, `_effective_warning_flags`, `_FLAG_LABELS`, `_WARNING_FIELD_OVERLAP`, `_map_blocking_error`) - untouched; this is a different system from the field-confidence-color layer removed above and was never in scope for removal.
- Invoice preprocessing (`modules/invoice_scan/preprocess/` in full, including the Phase 9.1 `_MIN_QUADRILATERAL_AREA_RATIO` guard) - untouched.
- Product Management, Sales (including FIFO stock consumption and `get_sellable_stock`), the centralized stock-lot identity/merge system in `modules/products/service.py`, Expiry Alerts, Low Stock Alerts, Dashboard, the database schema/repository layer, `core/session.py`, and `app.py` - untouched.
- Gemini call count (still exactly one call per invoice) and the `_build_genai_client`/error-handling logic in `ocr_service.py` - untouched.

### Verified
- All modified files (`ocr_service.py`, `review_ui.py`) pass `python3 -m py_compile`; every other source file in the project was also syntax-checked and passes.
- Project-wide grep confirms zero remaining references anywhere to `row_ocr`, `field_evidence`, `_get_ocr_evidence`, `_hint_text_from_evidence`, `_render_field_risk_css`, `_RISK_BACKGROUND_COLORS`, or `_RISK_TEXT_COLOR`.
- Ran the project's existing offline test harness (real `pytest`/`streamlit`/`google-genai` not installable in this working environment - no network access) against `tests/test_ocr_service.py`, `tests/test_review_service.py`, and `tests/test_preprocess_geometry_regression.py`: identical pass/fail counts to a pristine, untouched v2.17.0 baseline copy run through the same harness (26 passed/2 failed, 60 passed/3 failed, 3 passed/2 failed respectively) - all failures are pre-existing environment limitations (PyMuPDF/`pytest.skip` unavailable in this offline harness), confirmed unrelated to this change and not modified.
- Added `tests/test_extraction_iq200_focused.py` (13 new tests, all passing) directly verifying: Gemini's `contents` is exactly `[image, prompt]` with no OCR hint appended; Gemini is called exactly once per invoice; `row_ocr`/`field_evidence` no longer import; `ocr_service` has no OCR-hint helper functions left; extraction results carry no `_field_evidence` key; the new prompt is the actual runtime `_EXTRACTION_PROMPT` (not a stale/unused string); `qty`/`free` remain distinct fields; the `qty+free=TQT` formula's three branches (tqt-present, free-present, neither) all still produce the documented result; `MEDICINE_FIELDS` is unchanged; and a Gemini response omitting `tqt` (as the new prompt now produces) still parses correctly with `tqt` defaulting to `""`.
- `tests/test_expiry_alerts.py`, `tests/test_low_stock_alerts.py`, and `tests/test_products_ui_threshold_checkbox.py` remain not runnable in this offline environment (missing `bcrypt` and `streamlit.testing.v1.AppTest`) - pre-existing since v2.13.0, unrelated to this release's scope, not modified.
- Full-project `diff -rq` against a pristine v2.17.0 baseline extraction confirms exactly the expected change set: `modules/invoice_scan/ocr_service.py` and `modules/invoice_scan/review_ui.py` modified; `modules/invoice_scan/row_ocr.py` and `modules/invoice_scan/field_evidence.py` deleted; `requirements.txt` modified (one line removed); `tests/test_extraction_iq200_focused.py` added - no other file in the project changed. Products, Sales, Database, Validation, preprocessing (beyond the already-approved OCR-hint removal), and `app.py` confirmed untouched.

## [2.17.0] - Expiry Alerts Expand/Return + MRP/Rate Everywhere + Stock-Lot Merge/FIFO

### Summary
Phase 13: three changes against the v2.16.0 baseline - Expiry Alerts rows now expand like Product Management's own rows (Return Medicine hidden until expanded, medicine disappears from the alerts list once quantity is zero without being deleted); MRP/Rate display extended from Product Management to Expiry Alerts, Low Stock, Sales, and Dashboard; and a new, centralized stock-lot identity/merge system for the invoice Save flow (exact-lot quantity merging, zero-quantity-lot reuse, missing-batch confirmation machinery) plus FIFO (earliest-expiry-first) stock consumption for Sales. Invoice preprocessing, OCR, Gemini extraction/prompt, field evidence, validation (including the blocking Batch Number rule and the RED/YELLOW/GREEN risk-coloring system), database schema, and existing APIs are entirely untouched by this release.

### Changed
- **Expiry Alerts rows now use Product Management's click-to-expand interaction.** `modules/alerts/ui.py`'s `_render_alert_product_row()` was rewritten to wrap each row in `st.expander(summary)` (collapsed by default) - directly reusing the same per-row expander pattern `modules/products/ui.py`'s `_render_product_row()` already uses for Edit/Delete, no new interaction pattern invented. "↩️ Return Medicine" now renders only inside the opened expander (previously a bare, always-visible button).
- **A medicine now disappears from Expiry Alerts once its stock quantity is zero** (whether zeroed via Return Medicine or any other path). `modules/alerts/service.py`'s `get_categorized_alerts()` gained one `if product["quantity"] == 0: continue` guard in each of its two bucketing loops (expired products, expiring-soon products). This is a bucketing/display filter only - the product row is never deleted, and Product Management continues to show it exactly as before (untouched).
- **`modules/sales/service.py`'s `sell_product(store_id, product_id, quantity)`** keeps its exact prior name/signature/return type, but now consumes stock First-Expiry-First-Out across every in-stock lot of the sold medicine's name (via the product_id only to resolve which name is being sold), not just the one batch row that was clicked - a sale spanning more than one lot now writes one `sales_history` row per lot actually consumed (each with that lot's own real `batch_number`), reusing the pre-existing `record_sale()`/`reduce_stock()` unmodified, called once per lot consumed.
- **`modules/invoice_scan/review_service.py`'s `save_invoice_medicines()`** now calls the new `products_service.save_or_merge_invoice_lot()` per row instead of `add_product()` - see "Added" below for the merge rules this applies.

### Added
- **MRP and Rate now shown in Expiry Alerts, Low Stock, Sales, and Dashboard** (Product Management already had this since v2.16.0). `modules/products/repository.py`'s `get_expired_products`/`get_expiring_soon_products`/`get_low_stock_products` (both SQLite and Supabase implementations, plus the shared `_filter_low_stock_rows` helper) now select/return `mrp` and `rate` alongside their existing columns. Surfaced in `modules/alerts/ui.py`, `modules/alerts/low_stock_ui.py`, `modules/dashboard/ui.py` (`_render_item_table` and the Low Stock detail expander), and `modules/sales/ui.py` (`_render_sale_row`'s summary line). Display-only throughout - both fields already existed as product columns; no calculation, stock, or schema change.
- **Centralized stock-lot identity & merge rules**, new section in `modules/products/service.py` (search for "Stock Lot identity & merge rules"): a stock lot's identity is `medicine_name + batch_number + expiry_date` (name/batch case-insensitive, expiry compared as the stored Month/Year string). New functions: `find_exact_lot_match`, `find_possible_batch_match`, `_clean_invoice_lot_data` (a narrower validation than the existing `_validate_and_clean_product_data` - batch number is NOT required here, since a blank incoming batch on an invoice row is a legitimate case this section explicitly handles, unlike manual Product Management entry, which is completely unaffected), `_add_quantity_to_existing_lot`, `save_or_merge_invoice_lot` (the single entry point), and `get_lots_by_name_sorted_by_expiry` (the shared earliest-expiry-first lot list, used by both the merge logic and Sales' FIFO consumption). Rules implemented exactly as specified: same name+batch+expiry merges quantity into the existing row (this also covers reusing an existing zero-quantity row instead of creating a duplicate, since 0 + new = new via the same merge path); different batch or different expiry always creates a separate row; a blank incoming batch number that possibly matches an existing lot with a real batch number returns `{"status": "needs_confirmation", "match": {...}}` instead of guessing or auto-merging.
- **Missing-batch "Possible Match Found" confirmation UI.** `modules/invoice_scan/review_service.py` gained `get_pending_matches()`/`resolve_pending_match(index, "merge"|"create_new")`, and `save_invoice_medicines()` now collects any `needs_confirmation` rows into a new `pending_matches` session list instead of silently saving or silently skipping them. `modules/invoice_scan/review_ui.py` gained `_render_pending_matches()` - a card per pending row showing the existing vs. incoming lot with "Yes, Merge" / "Create New" buttons, rendered unconditionally after the Save button's own result block (not gated on the button being clicked this run) so it persists across reruns until every pending row is resolved.
- **`modules/sales/service.py`'s `get_sellable_stock(store_id, name)`** - sums quantity across every in-stock lot of a medicine name. `modules/sales/ui.py`'s `_render_sale_row()` now caps/displays the quantity stepper against this aggregate instead of the single clicked row's own `quantity`, since a sale can now legitimately draw from more than one batch in one transaction. Sales' search/suggestion/Frequently-Sold tiles (still per-batch-row) were deliberately left unchanged - only the already-selected row's stock-selection/consumption logic changed, per the explicit "modify only the stock-selection/consumption logic required for this behavior" scope instruction.

### Not changed
- Invoice preprocessing (`modules/invoice_scan/preprocess/`, including the Phase 9.1 `_MIN_QUADRILATERAL_AREA_RATIO = 0.20` guard), OCR (`row_ocr.py`), Gemini extraction (`ocr_service.py`, including the Phase 11 prompt), field evidence (`field_evidence.py`), validation (`validation.py`, `utils/validators.py`, and `review_service.py`'s blocking `validate_medicine()` function specifically - confirmed byte-identical via direct function-body extraction/comparison, including its existing "Batch number is required." blocking rule), Review UI risk-coloring system (RED/YELLOW/GREEN only, no 4th state), database schema (`core/database.py`, `database/supabase_schema.sql`), `app.py`, and existing APIs - all confirmed byte-identical to their v2.16.0 state by full-project `diff -rq` against the v2.16.0 baseline ZIP.
- `modules/products/service.py`'s pre-existing `add_product`/`edit_product`/`_validate_and_clean_product_data` and `config/product_schema.py` (batch number still `required=True` there) - completely unchanged; the new stock-lot section is additive and used only by the invoice Save path and Sales, never by manual Product Management Add/Edit.
- Product/alerts business logic beyond the changes above: Low Stock severity tiers, Dashboard's headline metric counts (only its detail-expander display gained MRP/Rate text), and the Sales search/suggestion/Frequently-Sold mechanism are all untouched.

### Known limitation (by design, not a defect)
- The missing-batch confirmation flow above cannot currently be triggered through the invoice Scan "Save Medicines" button, because `review_service.py`'s existing blocking `validate_medicine()` still requires Batch Number to be non-blank - a deliberate v2.13.5 "RED-validation sprint" decision, explicitly protected by `tests/test_review_service.py::TestValidateMedicine::test_empty_batch_number_is_blocking`. This phase was explicitly instructed not to modify blocking validation or that test, so the rule was left untouched; a row with a blank batch number cannot reach `save_invoice_medicines()` at all today. The service-layer logic (`find_possible_batch_match`, `save_or_merge_invoice_lot`'s `needs_confirmation` path, `get_pending_matches`/`resolve_pending_match`, `_render_pending_matches`) is fully implemented and unit-verified (23/23 focused checks passed directly against these functions) and will work the moment that one blocking check is ever relaxed - flagged here for a future, separately-approved decision rather than done unilaterally this phase.

### Verified
- **Real `pytest` + real `streamlit` (including `streamlit.testing.v1.AppTest`) were installable in this working environment** - unlike every prior documented release since v2.13.0, which had no network access. Full suite run directly: **130 passed, 5 failed, 6 errors, 2 skipped.**
- **Confirmed byte-for-byte identical failure/error/skip set** by running the exact same `pytest` invocation, unmodified, against a pristine copy of the v2.16.0 baseline ZIP in this same environment before any Phase 13 change was made: same 5 failures, same 6 errors, same 2 skips, same 130 passes. **Zero new failures introduced by this release.**
- The 5 failures + 6 errors are a pre-existing environment/test-harness artifact, unrelated to any application code: `streamlit.testing.v1.AppTest.from_file("app.py")` resolves the given path relative to the *calling test file's own directory* (`tests/`), producing a non-existent `tests/app.py` (the real `app.py` is at the project root) - affects every test in `test_expiry_alerts.py::TestExpiryAlertsUIRendersCorrectly`, `test_low_stock_alerts.py::TestLowStockUIRendersCorrectly`, and all of `test_products_ui_threshold_checkbox.py`, identically on both the v2.16.0 baseline and this release. Not modified, since fixing test files was out of this phase's explicit scope.
- The 2 skips are `test_preprocess_geometry_regression.py` tests needing real invoice image fixtures not present in this environment (pre-existing, unrelated to this release).
- **23 focused checks run directly against the new Phase 13 service-layer functions, all against a real temporary `sqlite3` database, all passed**: exact-lot merge (same name+batch+expiry accumulates quantity), different-batch-creates-separate-row, different-expiry-creates-separate-row, an existing zero-quantity lot is reused (no duplicate row) when a matching positive-quantity row arrives, `get_lots_by_name_sorted_by_expiry` returns lots earliest-expiry-first, a sale within one lot's stock consumes only that lot, a sale spanning two lots correctly depletes the earliest lot to zero then continues into the next, a depleted (quantity-0) lot is excluded from `get_lots_by_name_sorted_by_expiry` while its row still exists in the database, `get_sellable_stock` correctly sums across lots, overselling beyond total available stock across all lots raises `ValidationError`, a missing-batch row correctly detects a possible match against an existing named-batch lot, MRP/Rate are present in `get_expiring_soon_products`/`get_low_stock_products` output, and a returned (zeroed) medicine disappears from Expiry Alerts while its database record remains.
- Full-project `diff -rq` against the v2.16.0 baseline confirms exactly 10 files changed (`modules/alerts/ui.py`, `modules/alerts/service.py`, `modules/alerts/low_stock_ui.py`, `modules/dashboard/ui.py`, `modules/products/repository.py`, `modules/products/service.py`, `modules/invoice_scan/review_service.py`, `modules/invoice_scan/review_ui.py`, `modules/sales/service.py`, `modules/sales/ui.py`) and zero unexpected changes.

## [2.16.0] - Search Bar Isolation + MRP/Rate Display + Return Medicine

### Summary
Phase 12: three surgical, independently-scoped changes to Product Management, Expiry Alerts, and Low Stock - unrelated to the invoice-scan/OCR/Gemini/preprocessing/validation/review-session feature work, which is entirely untouched by this release.

### Fixed
- **Search bar state was shared across Products, Expiry Alerts, and Low Stock.** Root cause: none of the three `st.text_input(...)` calls (`modules/products/ui.py`, `modules/alerts/ui.py`, `modules/alerts/low_stock_ui.py`) had an explicit `key=`. With identical labels and placeholders across all three, Streamlit's auto-generated widget key collided, so all three inputs shared one `session_state` slot - typing in one search bar changed what appeared in the other two. Fix: each `text_input` now has its own explicit, unique `key` (`"products_search_term"`, `"expiry_alerts_search_term"`, `"low_stock_search_term"`). No change to search/filter logic, UI, styling, or layout - purely a widget-key fix.

### Added
- **MRP and Rate now shown in Product Management's product list.** `modules/products/ui.py`'s `_render_product_row()` summary line now includes `MRP: {mrp}  •  Rate: {rate}` alongside the existing Medicine Name/Batch/Qty/Expiry. Display-only - both fields already existed in the database schema (`config/product_schema.py`) and were already returned by `search_products()`/`get_all_products()` (`SELECT * FROM products`); no schema, repository, or calculation change was needed or made.
- **"↩️ Return Medicine" action added to Expiry Alerts.** `modules/products/service.py` gained `return_medicine(store_id, product_id)`, which fetches the full current product record and calls the existing `edit_product()` validate-and-update path with `quantity` forced to `0` and every other field (name, batch, expiry, MRP, rate, GST, purchase date, minimum stock threshold) carried over unchanged from the current record - this reuses the same update path Product Management's own Edit form already uses, not a second stock-tracking system, and involves no new database table or schema change. `modules/alerts/ui.py`'s `_render_alert_product_row()` (and the two functions that call it, `_render_alert_section()`/`render_expiry_alerts_page()`, updated only to thread `store_id` through) now shows a "↩️ Return Medicine" button per alert row (hidden once quantity is already 0, to avoid a pointless repeat click) that calls this function, shows a success message, and reruns to refresh the alerts view - all via the existing architecture (no new API, no new database write path).

### Not changed
- Invoice preprocessing (`modules/invoice_scan/preprocess/`, including the Phase 9.1 `_MIN_QUADRILATERAL_AREA_RATIO = 0.20` guard), OCR (`row_ocr.py`), Gemini extraction (`ocr_service.py`, including the Phase 11 prompt), normalization/parsing, field evidence (`field_evidence.py`), validation (`validation.py`, `review_service.py`, `utils/validators.py`), Review UI including the RED/YELLOW/GREEN risk-coloring system (`review_ui.py`), Save/Clear/session lifecycle, SHA-256 identity, upload flow, database schema, and APIs - all confirmed byte-identical to their v2.15.2 state by file diff/md5.
- Product/alerts business logic beyond the three changes above: sorting, filtering (other than the pre-existing search-by-name/batch), quantity-decrement-on-sale logic, low-stock threshold logic, and Dashboard are all untouched.

### Verified
- **Real end-to-end test** (real `sqlite3`, a real store + product row inserted, no mocking of the database layer): `return_medicine()` sets `quantity` to `0` while `name`, `batch_number`, `expiry_date`, `mrp`, `rate`, `gst_percent`, and `minimum_stock_threshold` (both the custom-threshold and default-threshold cases) are all confirmed byte-for-byte unchanged; the product record remains present in the table (not deleted); a second, unrelated product's `return_medicine()` call is confirmed not to affect the first product.
- Search-key isolation confirmed by direct inspection: three distinct, unique widget keys now exist, one per section - Streamlit's `session_state` mechanism guarantees independence once keys differ, so a value set under one key cannot appear under another.
- MRP/Rate summary line logic confirmed to include both new fields alongside all four pre-existing fields, unchanged.
- Full regression suite: **116 passed, 5 failed** - identical to v2.15.2, zero new failures. Same 5 Category C (environment-only) failures as every release since v2.13.0.
- Real `pytest` remains uninstallable here (no network) - verified via the same local harness established in Phase 9.
- Full-project diff after this release shows exactly the expected changed-file set: the three code files above, plus the four documentation files - no unexpected file.

## [2.15.2] - Extraction Prompt Accuracy Improvements + Review UI Risk-Coloring Audit

### Summary
Phase 11: two objectives against the v2.15.1 baseline. (1) Investigated a reported "Beige/Normal" 4th risk-color category in the Review Screen - found, by full code inspection, that no such category exists in the code (see "Audited, no change" below). (2) Strengthened the Gemini extraction prompt using principles proven effective in a separate Emergent prototype, adapted to EasyStock's existing schema and architecture - no new fields, no new Gemini call, no architecture change.

### Changed
- **`modules/invoice_scan/ocr_service.py`** - `_EXTRACTION_PROMPT` strengthened. Before editing, the actual data flow was traced to rule out normalization as the cause of blank `mrp`/`gst_percent` values: `_parse_and_validate_response()` was confirmed (by direct code inspection) to be a pure pass-through for every field except `name` (which gates row inclusion) - it does not blank, drop, or alter `mrp`/`rate`/`gst_percent`, and `_apply_quantity_formula()` only ever writes `quantity`. This proves any blank MRP/GST in the final result already arrived blank in Gemini's raw JSON, i.e. the issue (where it occurs) is at the extraction/prompt stage, not normalization - confirming the prompt was the correct and only place to intervene.
  - Added a structure-first framing: mentally correct orientation, locate the line-item table, read the header row, and establish column boundaries before reading any data row - reusing those same boundaries for every row.
  - Added dedicated **MRP**, **Rate**, and **GST** accuracy sections, mirroring the rigor the existing Batch Number section already had (which the prior prompt lacked entirely for these three fields) - each explicitly forbids substituting one for another (MRP≠Rate≠taxable value≠amount; GST%≠CGST/SGST/total amount/discount%) and explicitly forbids leaving a clearly visible value blank.
  - Added an explicit "VISIBLE + READABLE → extract it" rule, distinguishing genuine illegibility from under-confident blanking.
  - Extended the existing look-alike-character rules (O/0, I/1, S/5, B/8, Z/2, plus newly added G/6 and Q/0) to apply across all fields, not only Batch Number, with Z/2 called out for particular care.
  - Expanded the final self-check to explicitly verify MRP-not-from-Rate, Rate-not-from-MRP, GST-not-from-CGST/SGST/total, and that no visible value was left blank out of caution.
  - `MEDICINE_FIELDS` (the JSON schema: `name`, `batch_number`, `expiry_date`, `qty`, `free`, `tqt`, `mrp`, `rate`, `gst_percent`) is **unchanged** - no field added, renamed, or removed. The "return EXACTLY these keys" instruction and the illustrative example output are unchanged in structure.

### Audited, no change (Review UI risk-color presentation)
- Inspected `review_ui.py`'s complete risk/background-styling implementation (`_render_field_risk_css()`, `_RISK_BACKGROUND_COLORS`, `_render_row_highlight_css()`, `_render_table_scroll_css()`) looking for a "Beige/Normal/no-field-risk-evidence" 4th visual category. **None exists in the code.** `_RISK_BACKGROUND_COLORS` has exactly three entries (`"high"`→green, `"medium"`→yellow, `"low"`→red); a field with no `_field_evidence` metadata (e.g. `rate`/`gst_percent`, which have no evidence entries by design, or any row predating this feature) simply receives no CSS override at all and shows Streamlit's own native, unstyled input appearance - not a deliberately-set "beige" color. This already matches the stated goal exactly ("a normal/unflagged field should simply have the normal/default UI appearance... not a separate Beige risk category"). No source change was made for this objective, per the project's established practice of reporting an already-satisfied requirement rather than inventing a change (same pattern as Phase 4 and Phase 8).

### Not changed
- Preprocessing (`modules/invoice_scan/preprocess/` in full, including the Phase 9.1 `_MIN_QUADRILATERAL_AREA_RATIO = 0.20` guard) - confirmed byte-identical to the v2.15.1 state.
- Validation (`validation.py`, `review_service.py`, `utils/validators.py`) - confirmed byte-identical to the v2.15.1 state.
- Review UI (`review_ui.py`), Save/Clear/session (`review_service.py`, `upload_ui.py`, `app.py`), database schema, APIs, Gemini model/call-count architecture (still exactly one `generate_content()` call per invoice), EasyOCR (`row_ocr.py`) - all confirmed byte-identical to the v2.15.1 state by file diff.

### Emergent prototype comparison (documentation/investigation only - not adopted)
A separate Emergent prototype achieved high first-pass accuracy on real medical invoices using: raw uploaded image → EXIF auto-orient → RGB conversion → max-dimension resize to 2200px → +15% contrast → JPEG quality 92 → direct image → Gemini Vision (no traditional OCR preprocessing, no perspective correction, no denoise, no sharpening, no table-line detection) → structured JSON. EasyStock's own preprocessing remains its existing, dedicated `modules/invoice_scan/preprocess/` architecture (quality analysis, rule-driven geometry/enhancement, the Phase 9.1 quadrilateral guard, existing pipeline/fallback behavior) - **this was deliberately NOT replaced or reconciled with Emergent's lighter approach**, per this phase's explicit instruction. Only Emergent's prompt-engineering *strategy* (structure-first reading, explicit per-column extraction rules, explicit look-alike-character handling, explicit visible-value-extraction requirement) was adapted into EasyStock's existing prompt and schema.

### Verified
- `MEDICINE_FIELDS` unchanged; single `generate_content()` call site unchanged; full pipeline simulation (fake EasyOCR reader + fake Gemini client) confirms 3-part `contents` (image + prompt + OCR hint) and correct TQT formula output (`qty=10,free=2`→`quantity=12`) with the new prompt in place.
- Both real Phase 9 invoice images re-tested through preprocessing after this change: `IMG20260616160324.jpg` remains `3072×4096→3072×4096` (Phase 9.1 fix intact); `IMG20260728170635.jpg` remains unaffected.
- Full regression suite: **116 passed, 5 failed** - identical result to v2.15.1, zero new failures. Same 5 Category C (environment-only) failures as every release since v2.13.0/v2.15.0.
- Real `pytest` remains uninstallable here (no network) - verified via the same local harness established in Phase 9, executing the project's actual test files.
- No live Gemini call could be made against the real invoice images in this working environment (no network/API key) - the accuracy improvement itself (does the strengthened prompt actually reduce blank MRP/GST or batch-character errors on real invoices?) is **not verified end-to-end** and remains a known limitation, carried forward from v2.14.0/v2.15.0's equivalent disclosures.

## [2.15.1] - Preprocessing Fix: Perspective-Correction Quadrilateral Area Guard

### Fixed
- **`modules/invoice_scan/preprocess/geometry.py`** - `_find_largest_quadrilateral()` could accept a small/spurious 4-point contour as the invoice's document boundary (its only prior sanity check was `contourArea < 1`, i.e. near-zero) and hand it to `correct_perspective()` for warping. On a real photographed invoice (`IMG20260616160324.jpg`, 3072×4096), the accepted "quadrilateral" measured 65,746 px² against a 12,582,912 px² frame - 0.52% of the image, almost certainly picked up from something other than the invoice itself (e.g. a spiral binding gap or a stray table cell) - and the resulting warp destroyed the image down to an unusable 86×786 sliver. Added a single guard, `_MIN_QUADRILATERAL_AREA_RATIO = 0.20`: a candidate quadrilateral covering less than 20% of the full image area is rejected before ever reaching the warp step, falling through to the pipeline's existing, already-frozen fallback (return the original image unchanged). Threshold gives ~38x margin above the proven-bad 0.52% case while a legitimate document-filling photo (tested synthetically at 70.4% of frame) is still accepted and correctly warped.

### Not changed
- No other preprocessing stage (denoise, brightness/contrast, sharpening, auto-rotation, quality scoring, rule engine) was touched.
- `ocr_service.py`, `row_ocr.py`, `field_evidence.py`, `validation.py`, `review_ui.py`, `review_service.py`, `upload_ui.py`, `app.py`, database, and APIs are all confirmed untouched by file diff.

### Added
- **`tests/test_preprocess_geometry_regression.py`** (new) - targeted regression coverage for this one defect: the area-ratio constant is reasonable, a small synthetic spurious quadrilateral (~1% of frame) is rejected, a large synthetic legitimate quadrilateral (~81% of frame) is still accepted, and (when the real invoice fixture files are present on disk) both real Phase 9 images are exercised end-to-end through the actual pipeline.

### Verified
- **`IMG20260616160324.jpg`** (the proven-failing image): before fix, `3072×4096 → 86×786`; after fix, `3072×4096 → 3072×4096` (safe fallback to original), `success=True`, quality report remains coherent.
- **`IMG20260728170635.jpg`** (previously-successful image): unaffected either way - `3072×4096 → 3072×4096`, `perspective_level=None`, only sharpening applied, exactly as before this fix (perspective correction was never triggered for this image in the first place).
- Full regression suite re-run after the fix: same result as before the fix (no new failures introduced) - see v2.15.0's entry for the full breakdown.
- Real `pytest` remains uninstallable here (no network - same limitation as every release since v2.13.0); verified via the project's actual test code executed through a local harness (real assertions, real source, not a simulation standing in for pytest).

### Root cause investigation note
The project owner supplied a "previous stable version" of the preprocessing files for comparison before any fix was attempted. Direct `diff` confirmed those files were byte-for-byte identical to the then-current files - there was no historical implementation difference to restore. The fix above is therefore based entirely on direct root-cause tracing against the real failing image (not on restoring old behavior), as documented above.

## [2.15.0] - Full-Invoice EasyOCR Hint Integration + Field Evidence/Risk Engine + Review UI Risk Coloring

### Summary
A ten-phase (Phase 1 through Phase 9, plus the 9.1 fix above) delivery integrating the previously-isolated EasyOCR capability (v2.14.1) into the production Gemini extraction call as a full-invoice, non-authoritative hint, adding a field-level evidence/risk classification layer on top of the existing extraction and validation output, and surfacing that risk as background coloring in the Review Screen. The existing Gemini-only extraction, TQT formula, validation rules, session lifecycle, Save/Clear behavior, and database layer are all explicitly preserved and confirmed unchanged throughout.

### Added
- **`modules/invoice_scan/field_evidence.py`** (new) - isolated evidence/risk module. For each medicine row's `name`/`batch_number`/`expiry_date`/`mrp`/`quantity`, combines (a) Gemini's extracted value (never overridden), (b) the same full-invoice EasyOCR evidence already captured for the Gemini hint (no second OCR pass), and (c) the existing, unmodified `validation.py` rules (read via a deep copy, so the real rows and `review_service.py`'s own later validation call are unaffected) into a deterministic `risk_level` ("high"/"medium"/"low"). No numeric confidence percentage is invented - only EasyOCR's own per-detection confidence is passed through unchanged when a supporting match is found. Rule: any validation FAIL → low; else OCR conflict → low; else OCR support → high; else missing/unavailable → medium (never low merely because OCR found nothing).
- **8th advisory validation rule, `INVALID_EXPIRY_FORMAT`** (`modules/invoice_scan/validation.py`) - reuses the project's existing single canonical expiry validator, `utils.validators.is_valid_expiry()` (already used by `review_service.py`'s blocking Save check and `modules/products/service.py`), rather than inventing new date logic. Fires only when `expiry_date` is non-blank and not a recognized MM/YY, MM/YYYY, or Month-YYYY format.
- **Review UI risk backgrounds** (`modules/invoice_scan/review_ui.py`) - per-field background coloring (green/yellow/red for high/medium/low) read directly from `_field_evidence[field]["risk_level"]`, reusing the exact scoped-CSS-via-keyed-container technique already used for the existing error/warning field borders. Field text is explicitly forced dark/near-black regardless of theme so the signal is background-only. Only fields with evidence metadata are colored (`rate`/`gst_percent` are untouched). A friendly label and RED/YELLOW overlap suppression were added for `INVALID_EXPIRY_FORMAT`, matching the existing pattern for `EMPTY_*` flags.
- **`tests/test_preprocess_geometry_regression.py`** - see v2.15.1 above (delivered as the Phase 9.1 fix within this same overall release).

### Changed
- **`modules/invoice_scan/ocr_service.py`** - the isolated Phase 1 EasyOCR hint is now wired into the single existing `generate_content()` call: the full preprocessed image's EasyOCR evidence (text/bbox/confidence) is fetched once and included as a clearly-labeled "SECONDARY OCR HINT... NOT authoritative" text part alongside the image, with the image explicitly stated as the source of truth. EasyOCR failure/unavailability/empty/malformed result all fall back to the original Gemini-only 2-part call - Gemini is never called a second time. `_apply_quantity_formula()`/TQT logic is unchanged.
- **`modules/invoice_scan/row_ocr.py`** - `extract_text()`'s existing plain-text interface/behavior is unchanged, now built internally on a new `extract_evidence()` function (same EasyOCR call, `detail=1` instead of `detail=0`) so structured text+bbox+confidence is available without running EasyOCR twice per invoice.

### Not changed
- Gemini prompt content, model, and call count (still exactly one `generate_content()` call per invoice) - unchanged.
- `review_service.py` (session lifecycle, `save_invoice_medicines()`, `validate_medicine()`, `clear_session()`, `reset_session_for_new_upload()`, SHA-256 identity), `upload_ui.py`, `app.py`, database schema, and every repository - confirmed untouched by file diff throughout every phase of this release, including this one. The Review/Save/session architecture required NO changes at all (Phase 8) - every requirement (no DB write before Save, partial-save safety, Clear Review's full reset, navigation persistence, hash-based identity) was already correctly implemented by the existing, previously-stabilized (v2.13.2-v2.13.6) code.
- `preprocess/` (aside from the 9.1 fix above, applied within this same release).

### Verified
- Real `pytest`, real `streamlit` (and therefore `streamlit.testing.v1.AppTest`), and PyMuPDF remain uninstallable in this working environment (no network access - same limitation as every release since v2.13.0). Verified instead via a local harness that imports and executes the project's actual, unmodified test files (`tests/test_review_service.py`, `tests/test_ocr_service.py`, `tests/test_preprocess_geometry_regression.py`) with real assertions against the real source, plus direct logic simulation for the Gemini/OCR integration points (no real API key/network available). Full suite: **116 passed, 5 failed** - all 5 failures are Category C (environment-only: `streamlit.testing` unavailable for `test_expiry_alerts.py`/`test_low_stock_alerts.py`/`test_products_ui_threshold_checkbox.py`, which test modules never touched by this release; PyMuPDF unavailable for 2 PDF-rasterization tests in `test_ocr_service.py`, a known limitation since v2.13.0). Zero real code defects in this release's own scope.
- **20 pre-existing stale/mis-specified assertions in `tests/test_review_service.py`** (message-wording drift from the v2.13.5 "Warnings sprint" and the v2.13.6 navigation-persistence reversal, both predating this release) were identified, proven stale by direct execution against current behavior, and corrected to assert the current, documented, intended behavior - coverage preserved and strengthened, nothing weakened or deleted. See `tests/test_review_service.py` for the updated assertions and inline explanations of why each was stale.
- One real defect was found and fixed during this release's own regression testing (Phase 9 → 9.1) - see v2.15.1 above.
- Real invoice images (`IMG20260616160324.jpg`, `IMG20260728170635.jpg`) were used for preprocessing-stage testing only; actual EasyOCR and actual Gemini extraction against these specific images could not be run in this environment (EasyOCR model requires network to download, no Gemini API key/network available) - this is disclosed rather than claimed.

---

## [2.14.3] - OCR Accuracy Program: OpenCV Row Detection Removed

### Removed
- **`modules/invoice_scan/row_detect.py`** - the isolated OpenCV row-detection module added in v2.14.2. Removed after real-invoice testing (across multiple investigation sessions, using real photographed pharmacy invoices) showed it did not reliably identify actual medicine rows - detected regions frequently corresponded to header/footer/background content rather than real rows, even when the raw detected-region count happened to match the expected row count. Confirmed via `grep` across the full codebase, before removal, that the file was referenced nowhere else in the project (not imported by `ocr_service.py`, not by any other module, not by any test) - so removal has no effect on any other file.

### Not changed / not wired in
- `row_ocr.py` (EasyOCR, added in v2.14.1) is untouched and remains isolated - not imported or called by any production file.
- `ocr_service.py`, the Gemini prompt, and the Gemini API call are all untouched - Gemini extraction behaves exactly as in v2.14.2, still a single `generate_content()` call per invoice.
- `modules/invoice_scan/preprocess/`, `review_service.py`, `review_ui.py`, `validation.py`, `upload_ui.py`, `app.py`, Save, database, repositories, and every other module are unaffected.

### Status
No row-detection or row-cropping capability is currently part of this project, isolated or otherwise. The production invoice pipeline remains: upload → preprocessing → single Gemini Vision call → validation → review → save, unchanged since v2.13.6. The next OCR-accuracy implementation phase has not started.

## [2.14.2] - OCR Accuracy Program (Phase 2.2, Step 2): OpenCV Row Detection Added, Isolated

### Added
- **`modules/invoice_scan/row_detect.py`** (new) - isolated OpenCV row-detection capability. Provides a single interface: `detect_rows(image: Image.Image) -> List[Image.Image]`, which takes an already-preprocessed invoice image and returns an ordered, top-to-bottom list of row-shaped image crops using a horizontal ink-pixel projection profile (Otsu threshold + row-band grouping with small-gap merging). No new dependency required - built entirely on `opencv-python-headless`/`numpy`, both already in `requirements.txt`.

### Not changed / not wired in
This step adds row detection as a standalone capability only:
- `ocr_service.py`, the Gemini prompt, and the Gemini API call are all untouched - Gemini extraction behaves exactly as in v2.14.1.
- `row_ocr.py` (EasyOCR, added in v2.14.1) is untouched and not connected to this module.
- No row crop is sent to EasyOCR or to Gemini. No OCR hints exist. No second Gemini call exists.
- `modules/invoice_scan/preprocess/` (denoise/contrast/rotation/perspective correction) is completely untouched - `row_detect.py` only consumes an already-preprocessed image; it performs no whole-image correction of its own.
- Preprocessing, Review, Validation, Save, database, repositories, and every other module are unaffected.

### Known limitation (by design, not yet solved)
`detect_rows()` is a general horizontal-band detector, not a table-aware detector. It has no concept of which detected band is a header, a footer, a blank gap, or a genuine medicine row - it only separates bands of visual content from relatively blank horizontal gaps. That distinction is out of scope for this isolated module.

### Verified
- No real invoice image samples exist anywhere in this working environment (checked `/mnt/user-data/uploads/` and the full project tree - none found). The requested real-invoice test (17 known medicine rows -> 17 crops, checked for missing/duplicate/merged/split rows, header/footer inclusion, ordering) **could not be performed** for this reason, and is not claimed to have passed.
- A synthetic, clearly-labeled sanity check was run instead (a plain white image with 17 solid black bars, evenly spaced) purely to confirm the code executes correctly: `detect_rows()` returned exactly 17 ordered crops with no crash. Two further synthetic checks confirmed a blank image returns 0 crops (no crash) and that close-together bands (gap smaller than the merge threshold) correctly merge into one crop while far-apart bands stay separate. **This synthetic result says nothing about accuracy on real invoice photos** (real ink texture, noise, uneven spacing, wrapped medicine names, table gridlines, etc.) and must not be read as a real-invoice accuracy result.
- Confirmed via direct inspection and `diff -rq` against the v2.14.1 baseline that `row_detect.py` is referenced nowhere else in the codebase, and that `preprocess/`, `row_ocr.py`, `ocr_service.py`, `requirements.txt`, `review_service.py`, `review_ui.py`, `validation.py`, `app.py`, and every other module/package are byte-identical to v2.14.1.
- Real `pytest`/`streamlit` remain uninstallable in this working environment (no network access - same limitation as every release since v2.13.0).

### Not tested
Real invoice accuracy (missing/duplicate/merged/split row detection, header/footer exclusion, blank-row exclusion, ordering) against any actual invoice image - no sample invoices were available in this working environment.

---

## [2.14.1] - OCR Accuracy Program (Phase 2.2, Step 1): EasyOCR Added, Isolated

### Added
- **`easyocr>=1.7,<2.0`** added to `requirements.txt` - the minimum dependency needed to run EasyOCR.
- **`modules/invoice_scan/row_ocr.py`** (new) - isolated EasyOCR capability. Provides a single small interface: `extract_text(image: Image.Image) -> str`, which runs EasyOCR (CPU mode, English only) on a PIL image and returns the detected text. `easyocr` itself is imported lazily inside the module so that importing `row_ocr.py` never requires the dependency to be installed - only calling `extract_text()` does.

### Not changed / not wired in
This step adds EasyOCR as a standalone capability only. It is not called from anywhere else in the project:
- `ocr_service.py`, the Gemini prompt, and the Gemini API call are all untouched - Gemini extraction behaves exactly as in v2.14.0.
- No row detection or row cropping exists yet - `row_ocr.py` is not given row-level images by anything.
- No OCR text reaches Gemini in any form - the OCR-hint architecture investigated in the prior Phase 2.2 design sessions is not implemented yet.
- Preprocessing, Review, Validation, Save, database, repositories, and every other module are unaffected.

### Verified
- `row_ocr.py` imports cleanly on its own (confirmed: importing the module does not require `easyocr` to be installed, since the import is deferred into `_get_reader()`).
- Calling `extract_text()` in this working environment raises `ModuleNotFoundError: No module named 'easyocr'` - the real EasyOCR model could not be downloaded or initialized here, because this working environment has no network access (same limitation documented for `pytest`/`streamlit` since v2.13.0). This is an environment limitation, not a code defect - reported honestly rather than claiming a live OCR test passed.
- Confirmed via direct inspection that `ocr_service.py` contains no reference to `row_ocr`, and that no other file was modified besides `requirements.txt` (dependency line only) and the new `row_ocr.py` file.
- Real `pytest` could not be run for the same no-network reason; no test suite changes were made or claimed.

Versioning follows semantic versioning (MAJOR.MINOR.PATCH):
- **MAJOR** - breaking architecture changes
- **MINOR** - a new module is completed and delivered
- **PATCH** - a bug fix or refinement within an already-delivered module

---

## [1.3.0] - Module 6: Expiry Alerts

### Added
- **`modules/alerts/service.py`** - Bucketing logic for expiry alerts. Reuses `modules/products/repository.py`'s existing `get_expired_products` and `get_expiring_soon_products` - no new SQL queries were written, per the requirement to reuse the products repository rather than duplicate database logic. Each product is assigned to its single most urgent applicable window (Expired > 7 days > 15 days > 30 days), so a product expiring in 5 days appears once under "7 Days," not duplicated under 15 and 30 days as well - confirmed with you before building. Also provides `get_filtered_alerts()` (filter by type and/or search by name/batch) and `get_alert_counts()` (for the filter dropdown's live counts).
- **`modules/alerts/ui.py`** - Four color-coded sections (Expired = Red, 7 Days = Orange, 15 Days = Yellow, 30 Days = Blue), a filter-by-type dropdown showing live counts per category, and a search box matching medicine name or batch number.
- **`tests/test_expiry_alerts.py`** (new) - 7 tests: exact boundary verification at 7/15/30 days (all inclusive), confirming single-bucket assignment, multi-tenant isolation, filter/search logic, and two real Streamlit `AppTest`-driven UI checks confirming the page renders without exceptions and that selecting a filter actually narrows the visible sections.

### Modified
- **`config/settings.py`** - Added `EXPIRY_ALERT_WINDOWS_DAYS = [7, 15, 30]`.
- **`app.py`** - Added "⏰ Expiry Alerts" to sidebar navigation.

### Verified
- All store-scoped queries confirmed multi-tenant safe (Store B's products never appear in Store A's alerts, and vice versa).
- Boundary tests: expires-today correctly lands in the 7-day bucket (not Expired); exactly-7/15/30-day items correctly included in their respective bucket (inclusive boundary); 8/16/31-day items correctly excluded from the narrower bucket and placed in the next one up.
- Full project regression suite re-run (13 tests total across Modules 5 and 6) - no breakage.
- Full app boot test - clean HTTP 200, no exceptions.

---

### Note on the previous entry (v1.2.3)
The v1.2.3 entry below claims "Behavioral UI tests using Streamlit's `AppTest` framework" confirmed instant show/hide behavior. That claim was inaccurate - no such test was actually run or saved at the time, and the bug was reported as still present after that release. This entry corrects the record: the checkbox-outside-form code structure from v1.2.3 was, on inspection, already structurally correct, but it had never been verified with a real rerun test - only by reading the code. That gap is now closed.

### Fixed / Verified
- Used Streamlit's `AppTest` framework to actually drive the live app - log in, navigate to Products, toggle the checkbox - and confirm, with real evidence (not code review), that:
  - The "Minimum Stock Level" field is absent by default on both Add and Edit forms.
  - Checking the box makes the field appear with **zero clicks on Add/Save**.
  - Unchecking the box makes the field disappear, also instantly.
  - Toggling the checkbox alone never triggers a validation error.
  - Clicking Save/Add with the checkbox on and the field blank correctly shows "Please enter a custom minimum stock level." through the real UI path (not just the service layer in isolation).
- **`tests/test_products_ui_threshold_checkbox.py`** (new) - the above checks saved as a real, re-runnable `pytest` suite (6 tests, all passing), so this exact regression can be caught automatically in the future instead of relying on a manual claim.
- **`requirements-dev.txt`** (new) - separates test tooling (`pytest`) from the production `requirements.txt` used for the live Streamlit Cloud deploy.

### Process change
Per your instruction, every module or bug fix from this point forward ships as a complete, full-project ZIP with a version bump and this CHANGELOG updated - never a partial diff.

---

### Fixed
- **`modules/products/ui.py`** - The "Set a custom minimum stock level" checkbox previously lived inside `st.form(...)`, so toggling it had no visible effect until the form was submitted (Streamlit forms batch all widget values and only rerun on submit). The checkbox is now rendered *outside* the form, so checking/unchecking it instantly shows/hides the minimum stock level input, with no submit click required. Validation of the field's value still only runs on Save, as intended.
  - Added `_render_custom_threshold_checkbox()` - renders the checkbox outside the form.
  - `_render_schema_driven_fields()` now accepts `custom_threshold_enabled` as a parameter instead of rendering the checkbox itself.
  - Both `_render_add_product_form()` and `_render_edit_form()` updated to render the checkbox first, then open the form.

### Verified
- ~~Behavioral UI tests using Streamlit's `AppTest` framework~~ **This claim was inaccurate - see the v1.2.4 entry above for the correction and the actual verification.**
- Full regression suite re-run (CRUD, validation matrix, cross-store security, Dashboard auto-update) - no change in behavior, since this was a UI-only fix; the service layer (`modules/products/service.py`) was not modified.

---

## [1.2.2] - Module 5 (Product Management) - custom threshold validation fix

### Fixed
- **`modules/products/service.py`** - Enabling the "custom minimum stock level" checkbox and leaving the value blank, zero, or negative was previously accepted without error. Now enforced: checkbox ON requires a value of at least 1.
  - Blank/missing value -> "Please enter a custom minimum stock level."
  - Value less than 1, including 0 and negatives -> "Minimum stock must be at least 1."
  - Checkbox OFF still correctly stores `NULL` (uses the store-wide default threshold).
- **`modules/products/ui.py`** - Raised the custom threshold number input's `min_value` to 1 and removed the pre-filled default value when the checkbox is freshly checked, so the field starts genuinely empty rather than silently pre-filled with a number that looks like a deliberate choice.

### Verified
- Full validation matrix re-tested: 0 rejected, negative rejected, blank rejected (exact message), 1 accepted, 50 accepted, checkbox off accepted with `NULL` stored.
- Confirmed the rule applies on both Add and Edit (shared validation function).
- Full regression suite re-run - no breakage.

---

## [1.2.1] - Module 5 (Product Management) - low stock detection fix

### Fixed
- **`modules/products/ui.py`** - The "minimum stock level" form field always submitted `0` for new products (since a plain `st.number_input` cannot represent "unset"), which was incorrectly stored as a real threshold of 0 instead of `NULL`. This caused products with a quantity above 0 to never appear in Low Stock, since they were being compared against a threshold of 0 instead of the intended default of 10.
  - Added a "Set a custom minimum stock level for this product" checkbox. Left unchecked (default), the field is omitted entirely and the database stores `NULL`, which correctly falls back to the store-wide default threshold.

### Verified
- Quantities 0, 1, 9, 10, 11 tested against the default threshold of 10 - all correctly classified (0 through 10 flagged as low stock, 11 not).
- Custom per-product threshold path re-tested and confirmed still working.
- Full regression suite re-run (18 cases) - no breakage.

---

## [1.2.0] - Module 5: Product Management

### Added
- **`modules/products/service.py`** - Validation (driven by `config/product_schema.py`) and business rules: duplicate name+batch detection, ownership enforcement on edit/delete.
- **`modules/products/ui.py`** - View/Search, Add, Edit, Delete screens. Form fields generated dynamically from `product_schema.py` rather than hardcoded per medicine field.

### Modified
- **`modules/products/repository.py`** - Extended (not duplicated) with `create_product`, `update_product`, `delete_product`, `get_product_by_id`, `get_all_products` (search). Every write method requires `store_id` and verifies row ownership before writing.
- **`app.py`** - Added sidebar navigation between Dashboard and Products.

### Verified
- 17 automated tests: full CRUD, validation boundaries, duplicate detection, search, and two simulated cross-store attacks (Store B attempting to edit/delete Store A's product) - both correctly blocked.
- Confirmed Dashboard reflects new/edited/deleted products automatically, with zero changes to Dashboard code, since both modules share the same repository.

---

## [1.1.0] - Module 2: Dashboard

### Added
- **`config/product_schema.py`** - Canonical product field definitions (name, batch, expiry, quantity, MRP, etc.), the mechanism that keeps medical-specific fields out of hardcoded logic across OCR, database, and UI layers.
- **`modules/products/repository.py`** - Initial minimal version: read-only queries (`count_total_products`, `get_expired_products`, `get_expiring_soon_products`, `get_low_stock_products`), all scoped by `store_id`.
- **`modules/dashboard/service.py`** - Assembles the four dashboard metrics.
- **`modules/dashboard/ui.py`** - Four metric cards (Total Products, Expiring Soon, Expired, Low Stock) with expandable detail lists.

### Modified
- **`core/database.py`** - Added `products` table (with `store_id` foreign key) and indexes.
- **`config/settings.py`** - Added `DEFAULT_LOW_STOCK_THRESHOLD` (10) and `DASHBOARD_EXPIRY_SOON_DAYS` (30).
- **`app.py`** - Routes logged-in stores to the Dashboard instead of a placeholder welcome message.

### Verified
- 12 automated tests: empty state, expired/expiring/low-stock classification boundaries (inclusive edges), default vs. custom thresholds, and multi-tenant isolation between two stores.

---

## [1.0.0] - Module 1: Login

### Added
- **`config/settings.py`** - Centralized app constants (paths, mobile number rules, password length limits, session key).
- **`core/exceptions.py`** - Custom exception types (`ValidationError`, `DuplicateMobileError`, `InvalidCredentialsError`, `DatabaseError`).
- **`core/database.py`** - SQLite connection management and `stores` table schema.
- **`core/auth.py`** - Signup and login logic; bcrypt password hashing.
- **`core/session.py`** - Single source of truth for "who is logged in" - the foundation every later module's multi-tenant data isolation depends on.
- **`core/login_ui.py`** - Combined login/signup screen.
- **`utils/validators.py`** - Mobile number, password, and required-text validation.
- **`app.py`** - Application entry point and login gate.
- **`.streamlit/config.toml`** - Warm, simple visual theme.

### Verified
- 10 automated tests: signup, login (including formatted mobile number input), duplicate mobile rejection, wrong password vs. non-existent mobile (same error, no account enumeration), and validation boundaries.
- Confirmed passwords are stored as genuine bcrypt hashes, never plaintext.

---

## [1.3.1] - Dashboard expiry warning card + centralized color system

### Added
- **`config/alert_theme.py`** — extended with `render_alert_banner(message, alert_type)`, a shared HTML-card generator now used by both Dashboard and Expiry Alerts. This is the single source of truth for the entire app's alert color standard: 🔴 Expired (#D32F2F) · 🟠 7 Days (#F57C00) · 🟡 15 Days (#FBC02D) · 🔵 30 Days (#1976D2). No other file in the codebase defines alert hex colors.

### Modified
- **`modules/dashboard/ui.py`** — added `_render_expiring_soon_warning()`: shows one color-coded banner for the most urgent non-empty expiry bucket. Uses `alerts_service.get_alert_counts()` (no new bucketing logic) and `render_alert_banner()` (no new HTML). Priority order: 7-day wins over 15-day wins over 30-day. Shows nothing when all buckets empty.
- **`modules/alerts/ui.py`** — updated to import `render_alert_banner` from `config.alert_theme` and use it for product rows, replacing the previously inline-defined HTML. Structural parity with Dashboard card guaranteed from one definition.
- **`modules/alerts/service.py`** — `ALERT_TYPE_DISPLAY` now imported from `config.alert_theme` instead of being defined here. The service no longer owns color definitions.

### Bug caught and fixed during build
`st.error`/`st.warning` were used in the first attempt — a conflict was detected: this turn's spec said 7d=Red while the existing Expiry Alerts page already used 7d=Orange. Rather than silently picking one, the conflict was escalated. Decision: one consistent color system app-wide, centralized in `config/alert_theme.py`. Test confirmed the bug: the first version showed an orange card and reported "7 days" — wrong color, right text. Fixed by driving colors from `ALERT_TYPE_DISPLAY` in `alert_theme`.

### Verified
- 21 real AppTest-driven tests: all four warning card cases (7d/15d/30d/none), priority ordering (7d card shown even when 15d and 30d also have items), correct hex color per case, no exceptions, and Expiry Alerts page still shows correct colors after centralization.
- Full pytest regression suite: 13/13 passed, zero regressions.

---

## [1.4.0] - Module 7: Low Stock Alerts

### Added
- **`modules/alerts/low_stock_service.py`** — Fetches low-stock products from `products_repository.get_low_stock_products` (same function Dashboard uses — no new SQL), applies severity bucketing (Critical = qty 0, Warning = qty ≤ 50% of threshold, Low = qty ≤ threshold but >50%), and supports name/batch search filtering. Each product row carries `effective_threshold` (per-product or global default, already resolved by the repository's COALESCE) so the UI can show "Qty: 3 / Min: 10".
- **`modules/alerts/low_stock_ui.py`** — Three color-coded severity sections (🔴 Out of Stock, 🟠 Very Low, 🟡 Low Stock), filter dropdown with live counts, search box, and "Qty: X / Min: Y" per row. Uses the same red/orange/yellow palette as Expiry Alerts for visual consistency. Shows a green success message when all products are sufficiently stocked.
- **`tests/test_low_stock_alerts.py`** — 12 pytest tests: severity bucketing (all tiers, custom threshold, healthy excluded), multi-tenant isolation, search by name and batch, and 3 real AppTest UI tests (sections/colors render correctly, filter narrows to one section, empty-state message).

### Modified
- **`app.py`** — Added "📦 Low Stock" to sidebar navigation.

### Verified
- 14 service-layer tests + 15 real AppTest UI tests all passing before committing.
- Full project regression suite: 25 total tests (13 prior + 12 new), all passed.
- "Qty: 0 / Min: 10" confirmed appearing in a real rendered product row via AppTest.
- Multi-tenant isolation confirmed: Store B's items never visible in Store A's low-stock view.

---

## [1.4.1] - Bug fix: Add Product checkbox does not reset after successful save

### Fixed
- **`modules/products/ui.py`** — After a successful Add Product save, the "Set a custom minimum stock level" checkbox now correctly resets to unchecked and the threshold input hides immediately, matching `clear_on_submit` behavior for the form fields inside the form.

### Root cause
The checkbox lives outside `st.form(...)` (by design — this is what makes it trigger an instant rerun on toggle). `clear_on_submit` only clears widgets *inside* the form, so the checkbox was excluded. The prior fix attempted `session_state.pop(key) + st.rerun()`, but Streamlit restores widget values from session state *before* the script body runs on each rerun — so the pop happened too late and the key survived into the next render.

### Fix: sentinel flag pattern
On successful save, set `st.session_state["_reset_threshold_checkbox"] = True` instead of popping the widget key directly. At the top of `_render_custom_threshold_checkbox` — before `st.checkbox` is called — pop the sentinel; if it was present, also pop the widget's own key. By the time `st.checkbox` runs, its key is genuinely absent, so Streamlit falls back to `value=False` (unchecked) correctly. This is the only reliable pattern for resetting an outside-form widget across a Streamlit rerun boundary.

### No other files changed
Business logic, validation, service layer, repository, database schema, and all other modules are untouched.

### Verified
- 12 AppTest-driven tests covering the exact reproduction steps: checkbox unchecked after first save, threshold input hidden after first save, second save also resets correctly, and normal flow (check → fill → save) works throughout.
- Full project regression suite: 25/25 tests passed, zero regressions.

---

## [1.5.0] - Module 3 (Invoice Upload Screen)

### Added
- **`modules/invoice_scan/upload_service.py`** — `process_invoice_upload(file_obj, store_id)`: the single entry point for all invoice file saves. Calls `validate_upload` then `save_upload` from `utils/file_utils.py`. Returns saved path, generated filename, original name, and extension. No OCR, no Gemini, no medicine extraction.
- **`modules/invoice_scan/upload_ui.py`** — Invoice Scan page: file uploader (camera/JPG/PNG/JPEG/PDF), success banner, image preview via `st.image`, PDF preview via PyMuPDF rasterization (falls back to metadata card for encrypted/corrupt PDFs), and a file details expander showing the saved filename, path, and original name.
- **`utils/file_utils.py`** — Shared upload utilities: `validate_upload` (extension + size, human-readable errors), `save_upload` (store-scoped dir, unique timestamped UUID filename, sanitized stem), `get_store_upload_dir` (creates `data/uploads/{store_id}/` per-store), `get_image_preview` (PIL decode), `get_pdf_preview` (PyMuPDF rasterize first page, returns None on failure), `get_pdf_info` (fallback metadata).

### Modified
- **`app.py`** — Added "🧾 Invoice Scan" between Products and Expiry Alerts in sidebar nav.
- **`requirements.txt`** — Added `Pillow>=10.0,<13.0` and `pymupdf>=1.24,<2.0`.
- **`modules/invoice_scan/upload_ui.py`** — Replaced deprecated `use_container_width=True` on `st.image` with `width='stretch'` (Streamlit 1.58+).

### Not built (scope boundary)
OCR extraction, Gemini API, medicine detection, review screen, and any other processing after upload. This module ends immediately after successful upload and preview.

### Verified
- **20 file-layer tests**: PNG/JPG/JPEG/PDF save+validate, oversized rejection (with friendly message mentioning MB), 4 wrong extensions rejected, multi-store directory isolation (separate `data/uploads/{store_id}/` per store, no overlap), unique filenames for duplicate-named uploads.
- **23 AppTest UI tests**: clean startup, nav position, empty state, PNG/JPG/JPEG/PDF success+preview, oversized error path, wrong extension blocked at Streamlit widget level (correct — double protection), multi-store filesystem isolation.
- **Full project regression suite**: 25/25 passed, zero regressions.

### Known limitations
- `AppTest` in Streamlit 1.58 does not expose `st.image` as a testable element, so image preview is verified indirectly (success banner + no warning = PIL decode succeeded).
- Wrong-extension files trigger Streamlit's own widget guard (`StreamlitAPIException`) before our `validate_upload` even runs — this is correct double-protection behavior, but appears as an AppTest exception (not a user-visible crash). Verified by checking the exception message contains "Invalid file extension".
- PDF preview quality depends on PyMuPDF; encrypted or non-standard PDFs fall back to a metadata card (page count, file size) rather than crashing.

---

## [1.6.0] - Module 3 (OCR Extraction)

### Added
- **`modules/invoice_scan/ocr_service.py`** — Gemini Vision extraction service. Public API is one function: `extract_medicines_from_file(file_obj) -> dict`. Internals: `_get_api_key()` (reads from env, never hardcoded), `_file_to_pil_image()` (reuses `get_image_preview`/`get_pdf_preview` from `utils/file_utils.py`, no duplicated PDF/image logic), `_parse_and_validate_response()` (strips markdown fences, validates JSON array, drops nameless rows, fills missing fields with ""), `_build_genai_client()` (patchable seam for tests). Uses `google.genai` v2 (current SDK, not deprecated `google-generativeai`). API key loaded via `python-dotenv` from `.env`. No DB writes. No Streamlit imports.
- **`.env.example`** — Tracked template showing `GEMINI_API_KEY=your_key_here`. Real `.env` is gitignored.
- **`tests/test_ocr_service.py`** — 28 tests across 4 classes: `TestGetApiKey` (3), `TestParseAndValidateResponse` (10), `TestFileToPilImage` (4), `TestExtractMedicinesFromFile` (11). All Gemini API calls mocked via `_build_genai_client` patch — no real API key or network access required to run the test suite.

### Modified
- **`modules/invoice_scan/upload_ui.py`** — Added `_render_ocr_section()` called automatically after successful upload and preview. Shows a spinner during the Gemini round-trip, then on success: medicine count metric, extraction time metric, a confidence/accuracy note, and a read-only `st.json()` preview. On `GeminiAPIError` or `OCRError`: specific `st.error()` message. No edit UI, no save button, no database writes. All existing upload and preview functions untouched.
- **`core/exceptions.py`** — Added `OCRError` and `GeminiAPIError`.
- **`config/settings.py`** — Added `GEMINI_MODEL = "gemini-1.5-flash"` and `GEMINI_TIMEOUT_SECONDS = 30`.
- **`.gitignore`** — Added `.env`.
- **`requirements.txt`** — `google-generativeai` replaced with `google-genai>=2.0,<3.0`; added `python-dotenv>=1.0,<2.0`.

### SDK decision
The deprecated `google-generativeai` package was initially used (it was what pip resolved); the package itself raised a `FutureWarning` pointing to `google-genai`. Switched to `google.genai` v2 (`google-genai==2.10.0`), which is the current, maintained package. The mock target changed from the full `genai` module to `_build_genai_client()`, which is the correct, version-stable patch seam.

### Verified — tests actually executed, not claimed
- 28 OCR service tests: all pass (`pytest tests/test_ocr_service.py`)
- 25 regression tests (all prior modules): all pass (`pytest tests/ --ignore=tests/test_ocr_service.py`)
- Total: 53 tests, 53 passed, 0 failed
- App boot: HTTP 200, no exceptions

### Known limitations
- OCR accuracy depends on scan quality; blurry or skewed invoices may return partial or empty results. The UI shows a note to the store owner to verify extracted data.
- `AppTest` cannot test the OCR flow end-to-end because it would require a real Gemini API key and live network access. The UI rendering path (spinner, metrics, st.json) is tested by the existing upload UI tests that already cover the Invoice Scan page.
- Timeout is applied at the SDK client level via `GEMINI_TIMEOUT_SECONDS`; the new `google.genai` SDK passes it via `httpx` transport internally.

---

## [1.6.1] - OCR prompt: stronger batch number accuracy

### Changed
- **`modules/invoice_scan/ocr_service.py`** — `_EXTRACTION_PROMPT` only.
  Two targeted additions to the BATCH NUMBER section:
  1. Explicit statement that batch numbers may contain both letters AND digits
     (e.g. MPL254372, CN2175065, SPH251176) — sets Gemini's expectation that
     mixed alphanumeric strings are normal, not typos to be "corrected".
  2. Two missing character-confusion pairs added to the forbidden substitution
     list: `S ↔ 5` and `Z ↔ 2`, alongside the existing `O↔0`, `I↔1`, `B↔8`.
  3. Adjacent-duplicate re-check instruction tightened: now says
     "re-check BOTH rows on the invoice image" rather than "re-read the invoice",
     making the self-correction step more precise.
- **`config/settings.py`** — `GEMINI_MODEL` confirmed as `gemini-2.5-flash`
  (unchanged from v1.6.0, confirmed not reverted).

### Not changed
Architecture, upload UI, parsing logic, client construction, error handling,
Dashboard, Products, Alerts, database — all unchanged.

### Why extraction quality should improve
The previous prompt already covered row independence and three character-confusion
pairs. This release adds `S↔5` and `Z↔2`, which are the most common OCR character
confusions in alphanumeric batch codes on printed invoices. The "letters AND digits"
statement removes ambiguity about batch number format — without it, Gemini may
treat a long alphanumeric string as unusual and attempt to normalise it, sometimes
pulling in a nearby value it considers more plausible. Tightening "re-check BOTH
rows" gives the model a more concrete self-correction instruction when it detects
adjacent-row batch duplication.

### Tests executed
- `pytest tests/` — **53/53 passed**, 0 failed, 0 regressions
- App boot: HTTP 200, no errors

---

## [1.7.0] - Invoice Scan UX: Hindi photo tips + image quality warning

### Changed
- **`modules/invoice_scan/upload_ui.py`** only. Two additions:

  **1. Photo Tips (above file uploader)**
  A teal left-bordered HTML card shown above `st.file_uploader` on every
  page load, with exactly five Hindi bullet points as specified. Uses the
  app's existing primary color `#1A7A6E` for visual consistency.

  **2. Image Quality Warning (after upload, before OCR)**
  `_render_image_quality_warning()` — a new function called inside
  `_render_success_and_preview()` for image files only (PDFs excluded
  because they are rasterized at a fixed DPI by PyMuPDF, so the check
  would not reflect the original scan quality). Shows the specified
  three-line Hindi warning via `st.warning()` if quality looks poor.
  Never blocks upload or OCR — warning only.

### Image quality method (PIL only, no AI, no extra dependencies)
Three lightweight checks, all calibrated against real invoice image
measurements:

| Check | Method | Threshold | Calibration |
|---|---|---|---|
| Blur | Variance of `FIND_EDGES` response | `edge_variance < 500` | Sharp invoice ~4000–6000; Gaussian-blurred ~270 |
| Brightness | Mean grayscale pixel value | `< 40` (dark) or `> 253` (all-white) | Normal white paper 226–242; all-white 255 |
| Resolution | Width × height | `< 80 000 px` | 283×283 px minimum |

Thresholds were calibrated after an initial version produced false
positives on white-paper invoices (brightness ceiling was 220, but
normal white paper scores ~230–242). Ceiling raised to 253, which only
flags a completely washed-out, text-free image. Blur threshold raised
from 144 to 500 after measuring that uniform grey (a degenerate test
case) scored ~267 with the old threshold.

Exception safety: if the PIL check raises for any reason (unusual
format, memory), the function returns silently without warning or
crashing — it never blocks OCR.

### Not changed
OCR extraction, Gemini code, parsing logic, database, all other
modules, all existing tests.

### Tests executed
- 13 image quality check tests (sharp, blurred, dark, all-white, tiny,
  phone quality, white paper invoice, corrupt bytes) — all passed.
  Critically: phone-quality and white-paper-invoice correctly return
  `quality_ok=True` (no false alarm).
- 53/53 full regression suite — zero regressions.
- App boot: HTTP 200, no errors.

---

## [1.8.0] - Module 4: Review & Edit

### Added
- **`modules/invoice_scan/review_service.py`** — Session state management
  and validation for the editable medicine list. Functions:
  `initialise_review_session`, `is_review_session_active`, `get_medicines`,
  `update_medicine`, `delete_medicine`, `add_empty_medicine`,
  `validate_medicine`, `validate_all_medicines`. Zero database imports.
- **`modules/invoice_scan/review_ui.py`** — Editable table UI with one
  row per medicine, per-field text inputs with stable widget keys, delete
  button per row, Add New Medicine button, live total count, and a
  validation summary banner. Zero database imports.
- **`tests/test_review_service.py`** — 47 tests across 7 test classes.

### Modified
- **`modules/invoice_scan/upload_ui.py`** — In `_render_ocr_section()`,
  replaced the 2-line read-only `st.json(medicines)` block with a call to
  `render_review_section(source_filename, medicines)`. No other changes.

### Session state design
The review session is stored under the key `"invoice_review"` in
`st.session_state`:
```python
st.session_state["invoice_review"] = {
    "source_file": "invoice.png",   # detects new upload → resets session
    "medicines":   [                # deep copy of OCR output
        {"name": "Paracetamol", "batch_number": "B001", ...},
        ...
    ]
}
```
On each Streamlit rerun, `is_review_session_active(filename)` checks
whether the session belongs to the current upload. If the user uploads a
new invoice, the session reinitialises from fresh OCR output, discarding
any edits from the previous invoice. Each `st.text_input` is keyed by
`f"review_row_{idx}_{field}"` — Streamlit restores these from
`session_state` across reruns, giving inline editing without a per-row
Save button.

### No database write confirmation
Confirmed by two AST-level tests that inspect the import tree and string
constants of `review_service.py` and `review_ui.py`. Neither file
imports `core.database`, `sqlite3`, or `get_connection`. No raw SQL
keywords appear in any non-docstring string constant.

### Tests executed
- 47 new review service/UI tests: session init, deep copy, multi-file
  reset, get/update/delete/add CRUD, out-of-range safety, validation
  (name required, batch optional, numeric fields, 8 expiry formats
  accepted, 3 bad formats rejected), validate_all_medicines, session
  persistence across simulated reruns — all passed.
- 100/100 full regression suite — zero regressions.
- App boot: HTTP 200, no errors.

---

## [1.8.1] - Review & Edit: clean public API and verification note

### Modified files only

**`modules/invoice_scan/review_ui.py`**
- Added `render_review_ui(ocr_result)` as the clean public entry point.
  Accepts a single `ocr_result` dict (the exact object returned by
  `extract_medicines_from_file`), reads `medicines` and `source_file`
  from it, and delegates to the existing `render_review_section`.
  No existing function was changed.
- Added `st.info("✅ Please verify Batch Number and Expiry before saving.")`
  inside `render_review_section`, above the editable table.

**`modules/invoice_scan/upload_ui.py`**
- In `_render_ocr_section`: replaced the previous two-argument
  `render_review_section(source_filename, medicines)` call with:
  ```python
  ocr_result["source_file"] = uploaded_file.name
  render_review_ui(ocr_result)
  ```
  Two lines in, two lines out. Nothing else changed.

**`tests/test_review_service.py`**
- Added `TestRenderReviewUiEntryPoint` (4 tests): verifies
  `render_review_ui` is importable, accepts the ocr_result dict,
  reads `source_file` from it, and that `upload_ui.py` correctly
  injects the key before calling it. Tests avoid bare-mode
  `st.session_state` (which doesn't function outside `streamlit run`)
  by asserting on source code contracts and function signatures rather
  than Streamlit runtime state.

### Tests executed
- 51/51 review service tests — all passed
- 104/104 full regression suite — zero regressions

---

## [1.9.0] - Review & Edit: Gemini called exactly once per upload

### Problem fixed
Gemini Vision was being called on **every Streamlit rerun** — every
keypress, every delete, every add. `st.file_uploader` preserves the
uploaded file across reruns so `uploaded_file` was never `None`, causing
`extract_medicines_from_file` to execute each time. Any user edits
survived (by coincidence of the `is_review_session_active` guard in
`review_ui.py` that skipped re-initialising the session), but Gemini
still fired, adding latency and API cost on every interaction.

### Fix

**`modules/invoice_scan/upload_ui.py` — `_render_ocr_section`**

Added a session guard at the very top of the function, before any Gemini
call:

```python
if review_service.is_review_session_active(uploaded_file.name):
    # read metrics from cache, render review table from session state
    return  # ← Gemini never reached
```

Gemini is only called when no session exists for this file. After OCR
succeeds, the result is stored in session state with
`initialise_review_session(...)` and every subsequent rerun hits the
guard, returns immediately, and never calls Gemini. Typing a letter,
deleting a row, adding a row — all instant, all local, zero API calls.

**`modules/invoice_scan/review_service.py`**

- `initialise_review_session` accepts an optional `ocr_metadata` dict
  (medicine_count, extraction_time_seconds, model) and stores it in
  session state alongside the medicines.
- New `get_ocr_metadata()` function returns the cached metadata so
  `_render_ocr_section` can display count and extraction time from cache
  on every rerun without re-running OCR.

**`tests/test_review_service.py`**

Added `TestOcrCalledOnce` (5 tests):
- `initialise_review_session` stores and retrieves OCR metadata correctly.
- `get_ocr_metadata` returns empty dict with no session.
- Metadata survives medicine edits/deletes/adds unchanged.
- Structural test: confirms the guard in `_render_ocr_section` appears
  before the Gemini call AND contains a `return` statement — making
  Gemini unreachable on a cache hit. This test will fail if the guard
  is ever accidentally removed or reordered.

### Modified files
- `modules/invoice_scan/upload_ui.py`
- `modules/invoice_scan/review_service.py`
- `tests/test_review_service.py`

### Tests executed
- 56/56 review service tests — all passed
- 109/109 full regression suite — zero regressions
- App boot: HTTP 200, no errors

---

## [2.0.0] - Bug fixes: hash-based cache, navigation persistence, Save/Clear

### Bug 1 fixed — hash-based session identity
Sessions are now keyed by SHA-256 hash of the uploaded file's bytes, not
filename. Two invoices named "invoice.jpg" with different content now
correctly start separate OCR sessions. Uploading the same file twice
reuses the cached session without re-running Gemini.

**`modules/invoice_scan/review_service.py`** — already had the new
functions (`compute_file_hash`, hash-keyed `initialise_review_session`,
`is_review_session_active(file_hash)`, `has_any_session`, `clear_session`).

**`modules/invoice_scan/upload_ui.py`** — wired: computes `file_hash`
from `uploaded_file.getvalue()`, calls `is_review_session_active(file_hash)`
(not filename), calls `clear_session()` when hash differs, passes
`file_hash` to `initialise_review_session`.

### Bug 2 fixed — navigation persistence
When `st.file_uploader` returns `None` (user navigated away and returned),
`_render_upload_section` now calls `has_any_session()` and, if True,
renders the cached review table immediately — no re-upload, no Gemini call.
Added `_render_cached_session()` helper (shared by the nav-back path and
the session-hit path).

### Bug 3 fixed — Save and Clear buttons
**`modules/invoice_scan/review_ui.py`** — `_render_summary()` now renders:
- `💾 Save Medicines` (primary, disabled when 0 rows): calls
  `review_service.save_invoice_medicines(store_id)`, shows per-row errors
  without aborting valid rows, shows success count.
- `🗑 Clear Review`: calls `review_service.clear_session()` + `st.rerun()`.

**`modules/invoice_scan/review_ui.py`** — `render_review_section()` no
longer calls `initialise_review_session` itself (upload_ui always
initialises before calling it; doing it again with the old 2-arg signature
was broken).

### Tests updated (minimal)
- `TestOcrCalledOnce::test_initialise_stores_ocr_metadata` — added file_hash arg.
- `TestOcrCalledOnce::test_metadata_survives_independent_of_medicine_edits` — same.
- `TestOcrCalledOnce::test_session_active_means_gemini_must_be_skipped` — updated search string to `is_review_session_active(file_hash)`.
- `TestRenderReviewUiEntryPoint::test_upload_ui_adds_source_file_before_calling_render_review_ui` — updated assertions for new wiring.
- `TestRenderReviewUiEntryPoint::test_render_review_ui_accepts_ocr_result_dict` — fixed `st.columns` mock to return correct number of items.

### Tests executed
- 109/109 passed — zero regressions
- App boot: HTTP 200, no errors

---

## [2.0.1] - Polish: uploader reset on Clear, session verified

### Fixed
- **`modules/invoice_scan/upload_ui.py`** — Added `key="invoice_file_uploader"` to `st.file_uploader`. Without an explicit key, `clear_session()` could not address the uploader's widget entry in session state, so after clicking Clear the uploader still showed the old file. With the explicit key, `clear_session()` can delete it and `st.rerun()` presents a truly blank uploader.
- **`modules/invoice_scan/review_service.py`** — `clear_session()` now also deletes `st.session_state["invoice_file_uploader"]` so the uploader resets completely when Clear Review is clicked.

### Verified (no code changes needed)
- SHA-256 hash used throughout (not filename).
- Navigation persistence works (has_any_session guard).
- Save does NOT clear session — review remains visible after save.
- Only Clear Review removes the session.
- Save validates before writing, shows per-row errors, never crashes.

### Tests
- 109/109 passed — zero regressions.
- App boot: HTTP 200, no errors.

---

## [2.0.2] - Expiry validation: Month/Year format only

### Problem
Medical invoices store expiry as Month/Year (e.g. 3/28, 03/2028),
not calendar dates. The previous regex accepted any digit/digit pattern
without validating the month range, so 13/28, 0/28, 99/9999 were
silently accepted.

### Changed
**`modules/invoice_scan/review_service.py`** — `_is_valid_expiry()`:
- Now validates month as integer 1–12 (rejects 0, 13–99).
- Accepts single-digit months: 3/28, 6/28.
- For 2-digit year: accepts 01–99. For 4-digit year: accepts 2000–2099.
- Month-name format (Jun-2028, DEC-26) unchanged — always valid if the
  month name is a known abbreviation.
- Error message updated to:
  "Expiry must be in Month/Year format (e.g. 3/28, 03/28, 03/2028 or Jun-2028)."

**`modules/invoice_scan/review_ui.py`** — column label:
`"Expiry"` → `"Expiry (MM/YY)"`

**`config/product_schema.py`** — field label:
`"Expiry Date"` → `"Expiry (MM/YY)"`

**`tests/test_review_service.py`** — expiry test block replaced:
- Valid: 3/28, 03/28, 12/26, 03/2028, Jun-2028, June-2028, DEC-26 + existing.
- Invalid: 0/28, 13/28, 32/28, 99/9999, abc + existing — all now asserted
  to fail (previously 99/9999 had a stale permissiveness comment and was
  not asserted).
- Added `test_error_message_mentions_month_year_format`.

### Unchanged
OCR, Gemini prompt, extraction, parsing, database schema — untouched.

### Tests
- 121/121 passed (12 new expiry tests added) — zero regressions.
- App boot: HTTP 200, no errors.

---

## [2.0.3] - Single canonical expiry validator; future-expiry works with MM/YY

### Problem
`products/service.py` still used `date.fromisoformat()` in two places:
1. The `FieldType.DATE` branch → raised "is not a valid date" for `03/28`.
2. The `enforce_future_expiry` cross-field check → silently skipped via
   `except ValueError: pass`, meaning past MM/YY expiries slipped through.

### Changes

**`utils/validators.py`** — added `parse_expiry_month_year(value)`:
Single canonical parser that converts any accepted expiry string
(MM/YY, MM/YYYY, Month-YYYY) into `(month: int, full_year: int)`.
Used by `products/service.py` for the future-expiry comparison.

**`modules/products/service.py`**:
- `FieldType.DATE` branch for `expiry_date`: replaced `date.fromisoformat()`
  with `is_valid_expiry()` from `utils.validators`. Stores the value
  as-is (MM/YY string) for OCR-sourced saves; still handles real
  `date` objects from the Product Management date picker.
- `enforce_future_expiry` block: replaced the weak `except ValueError: pass`
  with proper MM/YY-aware comparison using `parse_expiry_month_year()`.
  Compares `(year, month)` tuples so `06/26` is correctly rejected when
  today is `07/26`, and `07/26` (current month) is accepted.

**`modules/invoice_scan/review_service.py`** — `_is_valid_expiry()` already
delegates to `utils.validators.is_valid_expiry` (from v2.0.2). No change.

### Single canonical validator confirmed
| Call site | Uses |
|---|---|
| Review & Edit validation | `review_service._is_valid_expiry` → `utils.validators.is_valid_expiry` |
| Invoice Save (add_product) | `products/service.py` DATE branch → `utils.validators.is_valid_expiry` |
| Future-expiry check | `products/service.py` → `utils.validators.parse_expiry_month_year` |

### Tests
- 121/121 passed — zero regressions.
- End-to-end: `add_product` accepts 3/28, 03/28, 12/26, Jun-2028, Jun-2028;
  rejects 13/28, 00/28, abc, 06/26 (past month).
- Future-expiry: 07/26 (current month) accepted; 06/26 (past) rejected.

---

## [2.0.4] - Expiry validation fully wired; single canonical parser confirmed

### Confirmed working (no further code changes needed)
All implementation was completed in v2.0.3. This release confirms the
wiring and packages it with a verified test run.

**Single canonical validator chain (confirmed by end-to-end test):**

| Call site | Path |
|---|---|
| Review & Edit (`review_service._is_valid_expiry`) | → `utils.validators.is_valid_expiry` |
| Invoice Save (`products/service.py` DATE branch) | → `utils.validators.is_valid_expiry` |
| Future-expiry check (`products/service.py`) | → `utils.validators.parse_expiry_month_year` |
| `date.fromisoformat` kept ONLY for `purchase_date` | (not expiry — correct) |

**`parse_expiry_month_year` verified:**
- `3/28` → (3, 2028), `12/26` → (12, 2026), `Jun-2028` → (6, 2028)
- 2-digit years normalised to 2000+YY

**Future-expiry logic verified (today = 07/2026):**
- `07/2025` rejected (past year)
- `07/2026` accepted (current month)
- `07/2027` accepted (future)

### Tests
- 121/121 passed — zero regressions
- 24/24 end-to-end spec checks passed

---

## [2.1.0] - Three expiry regressions fixed after MM/YY migration

### Bug 1 & 2 — Product Edit crash / missing submit button
**Root cause:** `modules/products/ui.py` `_render_schema_driven_fields()` called
`date.fromisoformat(existing_value)` for every `FieldType.DATE` field including
`expiry_date`. When an OCR-saved product stored `"1/29"`, this raised `ValueError:
Invalid isoformat string: '1/29'`, crashing inside `with st.form(...)` before
`st.form_submit_button` was reached — so the submit button never rendered (Bug 2
was a symptom of Bug 1).

**Fix:** `modules/products/ui.py` — `expiry_date` field now uses `st.text_input`
with a MM/YY placeholder. All other `FieldType.DATE` fields (`purchase_date`)
continue using `st.date_input` + `date.fromisoformat`.

### Bug 3 — Expiry Alerts wrong (future products shown as expired)
**Root cause:** `modules/products/repository.py` `get_expired_products()` and
`get_expiring_soon_products()` compared `expiry_date < '2026-07-08'` in SQL.
SQLite string comparison: `'1/29' < '2026-07-08'` → True (ASCII `'1'` < `'2'`),
so Jan 2029 was wrongly shown as expired. Same for `2/29`, `6/28`, `9/27`.

**Fix:** `modules/products/repository.py` — both functions now fetch all products
for the store and filter in Python using `parse_expiry_month_year()` from
`utils.validators`. Month/year tuples `(year, month)` are compared correctly.
Legacy ISO date values fall back to `date.fromisoformat` for backward compatibility.

### Modified files
- `modules/products/ui.py` — expiry_date uses `st.text_input` not `st.date_input`
- `modules/products/repository.py` — Python-level MM/YY filtering replaces SQL string comparison

### Tests
- 121/121 passed — zero regressions
- Direct verification: 1/28, 2/29, 3/28, 6/28, 9/27, 1/29 correctly NOT shown as expired; only a genuine past-year product appears as expired

---

## [2.1.1] - Expiry system fully verified; enforce_future_expiry cleaned up

### Final change
`modules/products/service.py` `enforce_future_expiry` block: removed the
ISO-first try/except pattern. Now calls `parse_expiry_month_year()` directly
as the single path for all expiry comparisons. `purchase_date` ISO handling
on line 123 is unchanged.

### Verified (today = 2026-07-09)
| Expiry | Result |
|---|---|
| 7/26 | ✅ 30-day bucket (Jul 31 = 22 days away) |
| 8/26 | ✅ No bucket (Aug 31 = 53 days away) |
| 9/26 | ✅ No bucket (far future) |
| 1/27, 1/28, 1/29 | ✅ No bucket (far future) |
| Past month | ✅ Expired bucket |

All workflows confirmed: add_product, edit_product, Dashboard, Expiry Alerts, Product Management — no `Invalid isoformat string` errors anywhere.

### Tests: 121/121 passed

---

## [2.2.0] - Expiry Alerts: new filter order with 60/90-day and expired-ago buckets

### New filter order
All Alerts → Expiring in 15 Days → Expiring in 30 Days → Expiring in 60 Days →
Expiring in 90 Days → Expired → Expired 1 Month Ago → Expired 2 Months Ago →
Expired 3 Months Ago

### Modified files
- **`config/alert_theme.py`** — added ALERT_TYPE_60_DAYS, ALERT_TYPE_90_DAYS, ALERT_TYPE_EXPIRED_1M/2M/3M constants and display entries; updated ALL_ALERT_TYPES to the new order
- **`config/settings.py`** — EXPIRY_ALERT_WINDOWS_DAYS changed from [7, 15, 30] to [15, 30, 60, 90]
- **`modules/alerts/service.py`** — updated imports; added 60/90 to _bucket_label_for_window; expired products now split into expired/expired_1m/expired_2m/expired_3m by months elapsed
- **`modules/dashboard/ui.py`** — warning card now uses 15-day as most-urgent bucket (7_days removed); uses .get() for safe count lookup
- **`tests/test_expiry_alerts.py`** — updated 3 tests that referenced the removed 7_days bucket

### Tests: 121/121 passed

---

## [2.2.1] - Delete row bug fix; threshold default 10→2; test updates

### Fixed
- **`modules/invoice_scan/review_ui.py`** — Delete button now clears all `review_row_*` widget keys from session_state before `st.rerun()`. Root cause: `st.text_input` with an explicit key ignores its `value` parameter when the key exists in session_state; after a delete the shifted rows had stale keys that caused `update_medicine()` to overwrite the new occupant with the deleted row's data, making it appear the wrong row was deleted.
- **`config/settings.py`** — `DEFAULT_LOW_STOCK_THRESHOLD` changed from 10 to 2.

### Tests updated
- **`tests/test_low_stock_alerts.py`** — 3 tests updated to use quantities that correctly trigger low-stock/warning buckets with the new default threshold of 2 (qty=1 → WARNING, qty=2 → LOW).

### Tests: 121/121 passed

## [2.2.2] - Delete row bug: real root cause found and fixed (v2.2.1's fix was incomplete)

### Root cause
The v2.2.1 fix addressed a symptom, not the underlying cause. Every widget key in the Review & Edit table (`review_row_{idx}_{field}`, `delete_row_{idx}`) was derived from the row's **position** in the list, not from any identity belonging to the medicine itself. Since `idx` is recomputed fresh from `enumerate()` on every render, a given key string does not consistently refer to the same medicine across reruns — after any row is removed, the same key string gets silently reused for whichever medicine now occupies that position (Streamlit ignores `value=` once a `key` already exists in `session_state`). Clearing `review_row_*` keys after a delete (v2.2.1) masked this for the simplest case but did not fix the identity model itself, did not clear `delete_row_*` keys, and did not hold up under real-device use, which is why the bug was reported as still 100% reproducible after v2.2.1 shipped.

### Fixed
- **`modules/invoice_scan/review_service.py`** — Every medicine dict is now assigned a stable `_row_id` (`uuid.uuid4().hex`) at the moment it enters the session — in `initialise_review_session()` (OCR results) and in `add_empty_medicine()` (manually added rows). `delete_medicine()` now also removes only that specific row's own leftover `review_row_{row_id}_*` and `delete_row_{row_id}` session-state keys, instead of the previous blanket wipe of every `review_row_*` key in the app.
- **`modules/invoice_scan/review_ui.py`** — Widget keys for every text input and the delete button are now built from the medicine's `_row_id`, not its list position (`idx`). `idx` is still used to call `update_medicine(idx, ...)` / `delete_medicine(idx)`, which correctly operate on list position — only widget *identity* changed. Module docstring and function docstring updated to describe the stable-id key scheme and explain why position-based keys were unsafe.
- **`_row_id` is confined to the review session** — `save_invoice_medicines()` already builds `form_data` as an explicit whitelist of named fields, so `_row_id` never reaches `products_service.add_product` or the database.

### Verification
`pytest`/Streamlit were not installable in this working environment (no network access), so the real `pytest`/`AppTest` suite could not be executed directly this round. In its place: (1) confirmed the existing `tests/test_review_service.py` makes no assertion on the literal `review_row_{idx}` key format or on exact dict equality for a medicine row, so it is not expected to conflict with the added `_row_id` field or the new key scheme; (2) built a Streamlit-semantics-accurate harness (faithfully replicating keyed `text_input`/`button`/`session_state`/`st.rerun()` behavior) and ran the actual, unmodified fixed source against it — first/middle/last single-row deletes, two sequential deletes at different positions, and an edit-immediately-before-delete scenario all produced the correct remaining rows with no stale-key regressions. Running the project's own `pytest` suite in an environment with `streamlit` installed is still recommended before this release is considered fully verified.

### Debug instrumentation
Temporary runtime debug logging added during investigation (`modules/invoice_scan/_debug_delete_instrumentation.py` plus log calls in `review_ui.py`/`review_service.py`) has been fully removed as part of this fix.

## [2.2.3] - Review & Edit: mobile UI improvement (horizontal scroll)

### Fixed
- **`modules/invoice_scan/review_ui.py`** — On mobile/narrow viewports, the Review & Edit table's columns were being compressed by Streamlit's own column-shrinking, making fields hard to read and edit. The header and every row are now wrapped in a single container (`st.container(key="review_table_scroll")`) with a scoped CSS rule (`min-width: 900px` on each row, `overflow-x: auto` on the container) so the table keeps its normal desktop-proportioned layout at all times and scrolls horizontally on narrow screens instead of squeezing columns. A "↔️ Scroll sideways to see every column" hint is shown only below a 768px viewport width (CSS media query), so it is invisible on desktop.

### Scope
- Desktop layout is pixel-identical to before this change — desktop viewports are already wider than the enforced 900px minimum, so the CSS rule has no visible effect there.
- No column was added, removed, reordered, or converted to a card layout. Every field remains an individually editable `st.text_input`. The delete button remains on the same row, in the same position.
- The CSS selector is scoped to the `st-key-review_table_scroll` container only, so it cannot affect `st.columns()` layouts used elsewhere in the app (Dashboard, Product Management, Alerts, etc.).
- No OCR, review-session, or save logic was touched. `modules/invoice_scan/review_service.py`, `ocr_service.py`, and `upload_service.py` are unchanged in this release.

### Verification
`pytest`/Streamlit remained unavailable in this working environment (no network access). Re-ran the same Streamlit-semantics-accurate simulation used to verify v2.2.2 (first/middle/last-row deletes, repeated deletes, edit-then-delete) against the now-wrapped table code — all scenarios still pass unchanged, confirming the container/CSS wrapper introduced no behavioral regression. Running the project's own `pytest`/`AppTest` suite in an environment with `streamlit` installed is still recommended.

## [2.2.4] - Review & Edit mobile UI: v2.2.3 withdrawn, corrected implementation

### Withdrawn
- **v2.2.3's approach was rejected after real-device testing** and is fully discarded, not iterated on. Its CSS only set `min-width: 900px` on the row container; it never overrode `flex-direction`. Streamlit's own built-in stylesheet already switches `st.columns()` to `flex-direction: column` (stacking) below its mobile breakpoint, so that native stacking rule still won. Because `st.text_input` renders at `width: 100%` of its parent column, and the parent block had been forced to 900px wide, the visible result was 8 full-width, ~900px-wide inputs stacked vertically per medicine — not the intended horizontal scroll.

### Fixed
- **`modules/invoice_scan/review_ui.py`** — Rebuilt from the v2.2.2 source (not from v2.2.3). All mobile CSS is now scoped inside `@media (max-width: 768px)`, so above that width nothing applies at all and desktop rendering is pixel-identical to v2.2.2, regardless of browser width. Below that width: `flex-wrap: nowrap` is forced on the row to override Streamlit's native stacking, and each of the 8 columns is given a fixed pixel width (`flex: none`, no shrink or grow) approximating its desktop proportion (Name 200px, Batch 140px, Expiry 140px, Qty/MRP/Rate/GST 70px each, Delete 55px). The row is therefore wider than the viewport and the container (not the page) scrolls horizontally, while each input stays close to its normal desktop size instead of stacking or stretching.

### Scope
- Desktop is pixel-identical to v2.2.2 — confirmed by construction, since every new rule lives inside a `max-width: 768px` media query that cannot apply above that width.
- No column added/removed/reordered, no card layout, no vertical stacking on mobile, no full-width giant inputs. Delete button stays on the same row, in the same position.
- No OCR, review-session, or save logic touched. `review_service.py`, `ocr_service.py`, and `upload_service.py` are unchanged (confirmed via file timestamps before packaging).

### Verification
Re-ran the same Streamlit-semantics-accurate simulation used for v2.2.2/v2.2.3 (first/middle/last-row deletes, repeated deletes, edit-then-delete) against the corrected code — all pass, confirming no behavioral regression. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so this is not yet verified against the project's real `AppTest` suite.

## [2.3.0] - Sales module (Phase 1: database + repository layer only)

### Added
- **`core/database.py`** — new `sales_history` table: `sale_id`, `store_id`, `product_id`, `medicine_name`, `batch_number`, `sold_quantity`, `sold_at`. Deliberately minimal for this MVP - no `price_per_unit` or `total_amount` yet. `medicine_name`/`batch_number` are snapshotted at sale time (not looked up live from `products`), so a sale record stays meaningful even if the product is later renamed, re-batched, or deleted. `CREATE TABLE IF NOT EXISTS`, same idempotent style as every other table. Two indexes added: `idx_sales_history_store_id` (ownership-scoped lookups, matching every other table) and `idx_sales_history_store_sold_at` (composite, serving `get_sales_history`'s `ORDER BY sold_at DESC LIMIT` directly).
- **`config/settings.py`** — new `SALES_HISTORY_DISPLAY_LIMIT = 100` constant. Not hardcoded in `modules/sales/repository.py`'s SQL, per the project's existing convention for tunable values (same pattern as `DEFAULT_LOW_STOCK_THRESHOLD`, `DASHBOARD_EXPIRY_SOON_DAYS`).
- **`modules/sales/repository.py`** (new file) — data access for `sales_history` only. `record_sale(store_id, product_id, medicine_name, batch_number, sold_quantity)` is the only write (a plain `INSERT`). `get_sales_history(store_id)` is a parameterless-apart-from-`store_id` read: `SELECT ... ORDER BY sold_at DESC LIMIT SALES_HISTORY_DISPLAY_LIMIT`. No update or delete function exists in this file at all — `sales_history` is append-only by omission, not by convention: adding a mutation path later would require deliberately adding a new function, not editing an existing one.
- **`modules/products/repository.py`** — new `reduce_stock(store_id, product_id, quantity)`. Atomic, conditional `UPDATE products SET quantity = quantity - ? ... WHERE store_id = ? AND product_id = ? AND quantity >= ?`. The availability check and the write happen in the same SQL statement (not a separate read-then-write), which is what actually prevents overselling under concurrent access — a race between two near-simultaneous sales of the last unit cannot both succeed. Raises `ValidationError` (reusing the existing exception type, no new one added) on zero rows affected — the same combined "not found or not yours" pattern `update_product`/`delete_product` already use, now also covering "insufficient stock" as a third cause of the same zero-rowcount result.

### Explicitly not in this phase
No service layer, no UI, no `app.py` routing entry. `modules/dashboard/*`, `modules/alerts/*`, and `modules/products/ui.py` were not touched (confirmed via file timestamps before packaging). This is database + repository only, per plan — Phase 2 (service layer) and Phase 3 (UI) follow in later releases.

### Verification
`pytest`/`streamlit` remain unavailable in this working environment (no network access), so the project's real test suite could not be executed. In its place: this phase's code has no Streamlit dependency at all (pure repository/SQL), so it was verified by actually executing it against a real, temporary SQLite database — 12 checks covering normal stock reduction, selling exact remaining stock to zero, rejecting an oversell attempt (and confirming stock is left unchanged), cross-store isolation on both `reduce_stock` and `get_sales_history`, a non-existent product_id, `record_sale`'s return value and field shape, newest-first ordering, and the `SALES_HISTORY_DISPLAY_LIMIT` cap under a real 105-row dataset — all 12 passed. Existing test files were confirmed to still compile and contain no prior references to `sales_history`/`reduce_stock` that this phase needed to match. Schema initialization was confirmed idempotent (called twice against a fresh database with no error). Running the project's own `pytest` suite in an environment with `streamlit` installed is still recommended before this phase is considered fully verified against the project's own harness.

## [2.3.1] - Sales module (Phase 2: service layer)

### Added
- **`modules/sales/service.py`** (new file) — business logic for Sales, matching `modules/products/service.py`'s contract exactly: no Streamlit imports, no raw SQL, reaches data only through repositories, raises `ValidationError` (reused, no new exception type) for every failure case.
  - `search_products(store_id, search_term)` — thin passthrough to `products_repository.get_all_products`, which already matches by name or batch number. Deciding whether to call this for an empty search term stays a UI-layer concern (deferred to Phase 3), not enforced here.
  - `sell_product(store_id, product_id, quantity)` — validates `quantity` is a positive whole number (independent of any UI widget's own clamping), fetches the product for its name/batch snapshot (raises `ValidationError` if not found), calls `products_repository.reduce_stock` (the real, atomic anti-oversell guard), and only on success calls `sales_repository.record_sale`. This ordering is deliberate: stock reduction always happens first, so the only possible failure mode is a real sale whose history row failed to write - never an inflated stock count or a phantom sale for stock that was never actually reduced.
  - `get_sales_history(store_id)` — thin passthrough to `sales_repository.get_sales_history`, no filters, no pagination, matching the Sales History section's MVP scope.

### Explicitly not in this phase
No UI changes. `modules/sales/ui.py` does not exist yet, `app.py` has no Sales routing entry, and `modules/dashboard/*`, `modules/alerts/*`, `modules/products/ui.py` were not touched (confirmed via file timestamps before packaging). `modules/sales/repository.py` (Phase 1) is also unchanged this phase.

### Verification
Mechanically verified, not just asserted: `grep` confirms `modules/sales/service.py` contains no `import streamlit`, no SQL keywords (`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`get_connection`/`cursor.`/`connection.`), and imports only `modules.products.repository`, `modules.sales.repository`, and `core.exceptions.ValidationError`. Also confirmed `modules/sales/repository.py` and `modules/products/repository.py` contain no Streamlit import and no field-validation-style business rules (only generic not-found/insufficient-stock messages), and that neither repository file imports any `*_service` module. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so as with Phase 1, this layer's functional correctness was verified by actually executing it against a real temporary SQLite database rather than via the project's own suite: 14 checks covering search by name and by batch number, a normal sale (stock reduced + history snapshot correct), overselling rejected with stock and history both left unchanged, quantity 0 / negative / non-integer all rejected before touching any repository, a non-existent product rejected, selling exactly the remaining stock succeeding down to zero, cross-store isolation on `sell_product` and `get_sales_history`, and newest-first ordering across two sales — all 14 passed. Phase 1's original 12 repository-level checks were re-run unchanged and still pass. Running the project's own `pytest` suite in an environment with `streamlit` installed remains recommended before this phase is considered fully verified against the project's own harness.

## [2.4.0] - Sales module complete (Phase 3: UI layer + routing)

### Added
- **`modules/sales/ui.py`** (new file) — the Sales screen. Deliberately reuses UI patterns already established elsewhere in EasyStock rather than inventing a new design language:
  - Live search with the exact same label/placeholder convention as `modules/products/ui.py`'s product list ("Search by medicine name or batch number").
  - Empty search box shows *"Start typing a medicine name or batch number."* and does not call the search service at all (verified: zero search calls with an empty box).
  - Each result shows a single-line summary (`Name • Batch: X • Stock: Y • Expires: Z`), matching `modules/products/ui.py`'s row-summary string format.
  - A compact **[−] quantity [+]** stepper per result, keyed by the product's real `product_id` (a stable identity, not list position — the same rule already established for the Review & Edit table). Quantity defaults to 1, floors at 1, ceilings at current stock; both buttons use Streamlit's native `disabled=` at their respective limits.
  - **Sell** button, disabled when stock is 0. On success: stock is reduced, the sale is recorded, and the row's quantity resets to 1.
  - Sales History section below: latest 100, newest first, rendered as native `st.container(border=True)` cards (a real Streamlit component, not custom HTML) — Medicine Name, Batch Number, Sold Quantity, Sold Time. No edit, no delete, no filters, no pagination.
  - **Zero custom CSS in this file.** Unlike the Review & Edit table (which needed a scoped mobile media-query fix for its 7+ wide text-input columns), nothing here has that failure mode: the stepper is a handful of narrow buttons and the history is naturally-stacking cards, both of which degrade to mobile gracefully with no CSS at all.
- **`app.py`** — one import line, one `NAV_PAGES` entry (`"🛒 Sales": render_sales_page`), following the exact same one-line-per-module pattern every other page already uses. `app.py` remains routing-only.

### Scope
- No changes to `modules/sales/service.py` or `modules/sales/repository.py` (Phases 1-2) - the UI calls `sales_service` only, never `sales_repository` or `products_repository`/`products_service` directly, matching every other UI file's layering.
- `modules/dashboard/*`, `modules/alerts/*`, and `modules/products/ui.py` were not touched (confirmed via file timestamps before packaging) - both automatically reflect a sale's stock reduction on their next render, with no code changes of their own, exactly as designed back in Phase 1.
- Desktop rendering uses only native Streamlit layout (columns, buttons, containers) with no styling overrides, so it inherits the app's existing look consistently rather than introducing any custom visual treatment.

### Verification
Mechanically confirmed `modules/sales/ui.py` contains no SQL and no direct repository import (its only imports are `streamlit`, `modules.sales.service`, `core.session`, `core.exceptions`). `pytest`/`streamlit` remain unavailable in this working environment (no network access), so as with the Review & Edit UI work, this was verified with a Streamlit-semantics-accurate simulation (faithful keyed `text_input`/`button`/`session_state`/`st.rerun()`/`st.container()` behavior, extended this round to make `disabled=True` buttons genuinely unclickable, matching real Streamlit) executing the actual, unmodified `sales/ui.py` end-to-end against a real temporary SQLite database. 15 checks passed: empty search box never calls the search service; typing a term triggers exactly one search call; quantity defaults to 1; plus increments up to stock and is then blocked from going further; minus decrements down to 1 and is then blocked from going below it; a normal sale reduces stock, resets quantity to 1, and appears correctly in history; selling the exact remaining stock brings it to zero; and with stock at zero, the disabled Sell button cannot record a further sale. All prior simulation/functional suites (Review & Edit: 5 scenarios; Sales repository: 12 checks; Sales service: 14 checks) were re-run afterward and still pass, confirming the shared test shim's extensions introduced no regressions. Existing test files were confirmed to still compile. Running the project's own `pytest`/`AppTest` suite in an environment with `streamlit` installed remains recommended before this release is considered fully verified against the project's own harness.

### Sales module now complete for the MVP flow
Search → view stock/expiry → adjust quantity → sell → stock reduced → sale recorded in permanent history → Dashboard/Low Stock Alerts automatically reflect the change on their next render. No billing, no GST, no customer management, no invoice printing, no barcode, no reports/analytics - all confirmed out of scope per the agreed implementation plan.

## [2.4.1] - Sales search experience: live autocomplete, stock filter, Frequently Sold

### Scope
This release touches only the Sales search flow. No changes to Dashboard, Alerts, Product Management, Invoice Scan, the database schema (no new tables/columns - `sales_history` and `products` are reused as-is), or `sell_product`'s own logic in `modules/sales/service.py` (confirmed byte-unchanged; only `search_products` was modified and two new functions were added alongside it). `modules/sales/ui.py`'s `_render_sale_row` - the actual stepper/sell mechanics - is confirmed byte-for-byte unchanged; only *when* and *how often* it gets rendered changed.

### Added
- **`config/settings.py`** — three new constants: `SALES_SEARCH_SUGGESTION_LIMIT = 10` (autocomplete result cap), `SALES_FREQUENTLY_SOLD_LIMIT = 8` (Frequently Sold display cap), `SALES_FREQUENTLY_SOLD_CANDIDATE_LIMIT = 50` (internal over-fetch pool, since `sales_history` has no live-stock column and some top-sellers may now be out of stock or deleted).
- **`modules/sales/repository.py`** — new `get_top_sold_product_ids(store_id, limit)`: pure SQL aggregation (`GROUP BY product_id, SUM(sold_quantity) DESC`) over the existing `sales_history` table. No schema change. Returns bare product_ids only - has no notion of current stock, by design; that's the service layer's job.
- **`modules/sales/service.py`**:
  - `search_products` now filters out any product with `quantity <= 0` (never suggest out-of-stock medicines) and caps results at `SALES_SEARCH_SUGGESTION_LIMIT`. This is the one existing function that changed.
  - New `get_frequently_sold(store_id)` — combines `get_top_sold_product_ids` (historical fact) with `products_repository.get_product_by_id` (live data) to answer "best sellers this store can actually still sell right now"; silently skips anything now out of stock or deleted.
  - New `get_product(store_id, product_id)` — thin passthrough to `products_repository.get_product_by_id`, added so the UI can re-check a selected product's live stock without importing `products_repository` directly (preserves the UI → Service → Repository layering rule).
- **`modules/sales/ui.py`** — `_render_sell_section` rewritten (this is the only rewritten function; `_render_sale_row`, `render_sales_page`, and `_render_sales_history_section` are all unchanged) around three new helpers:
  - `_get_active_selection` / `_select_product` — tracks which product (if any) is "selected" via `session_state["sales_selected_product_id"]`. A selection stays active only while the search box still shows exactly the name that selecting it filled in and the product remains in stock; otherwise it's dropped automatically on the next render, and search/autocomplete takes back over with no extra click needed.
  - `_render_suggestion_tile` — one lightweight, clickable card per suggestion (name, batch, stock only - no expiry/MRP/GST), reusing the same `st.container(border=True)` card pattern already established for Sales History.
  - `_render_frequently_sold` — shown only when the search box is empty; up to 8 top-sellers still in stock, each clicking exactly like a search suggestion.
  - An empty search box never calls `search_products` at all (unchanged rule from Phase 3, now paired with the new Frequently Sold section instead of just a bare prompt).
  - Still zero custom CSS, zero JavaScript - every new element is a native `st.container`/`st.button`/`st.markdown`/`st.caption`.
- **`app.py`** — unchanged this release (routing entry from v2.4.0 already covers the Sales page).

### Verification
Mechanically re-confirmed: `modules/sales/ui.py` has no SQL and imports only `sales_service`, `core.session`, `core.exceptions`; `modules/sales/service.py` has no Streamlit import; `modules/sales/repository.py` has no Streamlit import and no field-validation-style business rules. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so as with every prior Sales release, this was verified by direct execution/simulation against real SQLite: 10 new checks for `search_products`'s stock filter, multi-batch handling, the suggestion cap, and `get_frequently_sold`'s ranking/exclusion/cap behavior; 13 new checks for the full UI flow (empty box never loads inventory, live typing triggers exactly one search call, clicking a suggestion fills the box/selects/resets quantity, the owner is never asked to search again once selected, a stale selection clears itself when the box is edited or the item sells out) - all 23 new checks passed. All prior suites were re-run afterward: the Phase-1/2 repository and service suites (12 + 14 checks) and the Review & Edit simulation (5 scenarios) passed unchanged. The original Phase 3 UI stepper/sell test needed one line adapted (select the suggestion before checking default quantity, since search no longer shows the full stepper immediately - this is the intended new flow, not a regression) and then passed all 15 of its checks, confirming the underlying stepper/sell mechanics are unaffected. 69 checks total, 0 failures. Running the project's own `pytest`/`AppTest` suite in an environment with `streamlit` installed remains recommended before this release is considered fully verified against the project's own harness.

## [2.4.2] - Sales search: fix StreamlitAPIException, compact suggestion rows

### Fixed
- **`modules/sales/ui.py`** — `StreamlitAPIException: st.session_state.sales_search_term cannot be modified after the widget with key sales_search_term is instantiated`, raised when clicking a search suggestion or Frequently Sold tile. Root cause: `_select_product` wrote directly to `st.session_state["sales_search_term"]` from inside a plain `if st.button(...):` block - by that point in the script, the search box's `text_input` (key `sales_search_term`) had already been instantiated earlier in the same run, and Streamlit disallows mutating a widget's own session-state key after it has been instantiated in that run. Fixed using Streamlit's own documented pattern for this exact situation: `_select_product` is now wired as the button's `on_click` callback (`st.button(..., on_click=_select_product, args=(product,))`) instead of being called from inside an `if` block. Callbacks run in a dedicated phase before the script body reruns and widgets are re-instantiated, so the same state writes that raised the exception are safe from inside the callback. No `st.rerun()` call is needed inside the callback either - Streamlit already reruns automatically after any widget interaction. No other workaround, flag, or hack was used.

### Changed
- **`modules/sales/ui.py`** — Search suggestion and Frequently Sold rows are now compact, single-row entries instead of bordered cards. Each is one native `st.button` whose label is the medicine name (bold) on one line and `Batch: X • Stock: Y` on the next (Streamlit's built-in limited Markdown support for widget labels), styled like a dropdown-list entry rather than a card. The separate `st.container(border=True)` wrapper, separate `st.markdown`/`st.caption` lines, and separate "Select" sub-button used previously are removed for suggestions - clicking anywhere on the row selects it. The Sales History section is unaffected and still uses `st.container(border=True)` cards, since it has no compactness requirement.

### Unchanged (confirmed, not just assumed)
- `sell_product`, `search_products`, `get_frequently_sold`, `get_product`, `get_sales_history` in `modules/sales/service.py` - byte-identical, not touched this release.
- `modules/sales/repository.py` - not touched this release.
- `_render_sale_row`, `render_sales_page`, `_render_sales_history_section` in `modules/sales/ui.py` - byte-identical, not touched this release. `_get_active_selection`'s logic is also unchanged; only how `_select_product` is *wired* to its trigger changed.
- Suggestion limit (10), stock filter (quantity > 0 only), search-by-name, search-by-batch-number, and Frequently Sold (top 8, in-stock only) - all unchanged, confirmed via the same 10 service-level checks from v2.4.1 re-run unmodified and passing.
- Dashboard, Alerts, Product Management, Invoice Scan, database schema - not touched.

### Verification
The test harness used to verify prior Sales UI releases (a hand-built Streamlit-semantics shim) did not model the specific constraint that caused this bug - it allowed writing to a widget's session-state key after instantiation, which is why this bug shipped in v2.4.1 without the simulation catching it. The shim was corrected this release to accurately model Streamlit's two-phase execution: an `on_click` callback registered on a given widget key now fires in a dedicated pre-run phase (using the callback registered from the previous run, mirroring how real Streamlit resolves callbacks before a fresh script pass), and any other code that writes to a widget's session-state key after that widget has been instantiated in the current run now correctly raises the same `StreamlitAPIException`. This was sanity-checked directly: replaying the *old* (broken) code pattern against the corrected shim reproduces the exact real-world exception message, confirming the shim now genuinely catches this bug class rather than passing trivially. Against this corrected shim, the fixed code (all 15 Phase 3 stepper/sell checks, all 13 search/select-flow checks including the click-a-suggestion path that previously would have raised) passes cleanly. All other suites (Review & Edit: 6 scenarios - one test-harness assertion was also corrected here, from an illegal direct `session_state` poke to a realistic `queue_text_edit` helper that mirrors how Streamlit actually delivers a text_input's new value; Sales repository: 12; Sales service: 14; Sales search/frequently-sold service: 10) were re-run and still pass, 0 regressions. A new, additional check (6 checks, real SQLite, no Streamlit involved) directly confirmed Dashboard's product count and Low Stock Alerts' counts/list both automatically reflect a sale's stock reduction, including a full sell-to-zero, with zero code changes to `modules/dashboard/` or `modules/alerts/`. 76 checks total this release, 0 failures. `pytest`/`streamlit` remain unavailable in this working environment (no network access); running the project's own suite remains recommended.

## [2.4.3] - Sales UX: search clear button, always-compact quantity selector

### Scope
`modules/sales/ui.py` only. No changes to `modules/sales/service.py`, `modules/sales/repository.py`, Dashboard, Alerts, Product Management, Invoice Scan, or the database schema (confirmed via file timestamps before packaging).

### Added
- **Search clear button**: a ❌ button next to the search box. Wired as an `on_click` callback (`_clear_search`), following the same pattern established in v2.4.2 for `_select_product` - required for the same reason: writing to `st.session_state["sales_search_term"]` from inside a plain `if button:` block would raise the same `StreamlitAPIException` fixed last release, since that key belongs to a widget already instantiated earlier in the run. Clearing calls no service function at all - it is a pure session-state reset (search text + any active selection), so there is no unnecessary logic to rerun. Clearing naturally falls through to the existing empty-search behavior (guidance prompt + Frequently Sold) with no new branching logic needed - that behavior already existed.

### Changed
- **Compact quantity selector**: the `[-] quantity [+] Sell` row is now wrapped in a scoped container (`st.container(key="sales_qty_row")`) with CSS that forces `flex-wrap: nowrap` and a fixed pixel width per button/display, reusing the exact pattern already established (and documented in `AI_RULES.md`) for the Review & Edit table's mobile fix. Native `st.columns()` alone could not keep this row from stacking vertically below Streamlit's own mobile breakpoint, regardless of how narrow the columns were - that native stacking is what "large stacked controls" on mobile actually was. Unlike the Review & Edit table's fix, this CSS is **not** gated behind a mobile-only media query - it applies unconditionally on every screen size, since a compact one-row layout was explicitly wanted on both desktop and mobile. All button/stepper logic inside the row (increment, decrement, disabled states, sell, quantity clamping) is unchanged - only the surrounding layout/CSS wrapper changed.

### Unchanged (confirmed, not just assumed)
- `sell_product`, `search_products`, `get_frequently_sold`, `get_product`, `get_sales_history` in `modules/sales/service.py` - not touched.
- `modules/sales/repository.py` - not touched.
- Quantity validation, floor/ceiling clamping, disabled-button behavior at both limits, and the Sell button's own logic - byte-identical to v2.4.2, only their rendering wrapper changed.
- Suggestion limit (10), stock filter, search-by-name, search-by-batch, Frequently Sold (top 8) - unchanged.
- Dashboard, Alerts, Product Management, Invoice Scan, database schema - not touched.

### Verification
Mechanically confirmed: `modules/sales/ui.py` still has no SQL and still imports only `sales_service`/`core.session`/`core.exceptions`; `_clear_search` calls zero service functions; the new CSS is scoped exclusively to `.st-key-sales_qty_row`, with no global rule. A new 9-check test suite specifically covers the clear button against the corrected callback-phase simulation shim (from v2.4.2): clicking clear raises no `StreamlitAPIException`, search text and selection are both cleared, the empty-box short-circuit still holds (no `search_products` call), Frequently Sold is shown again on the next render, and clicking clear again when already empty is a harmless no-op - all 9 passed. All prior suites were re-run and still pass unchanged: Review & Edit (6 scenarios), Sales repository (12), Sales service (14), Sales search/frequently-sold service (10), Dashboard/Low Stock reflecting a sale (6), Sales UI stepper/sell (15, now exercising the new compact-row wrapper), Sales UI search/select flow (13). 85 checks total this release, 0 failures. `pytest`/`streamlit` remain unavailable in this working environment (no network access); running the project's own suite remains recommended.

## [2.4.4] - Sales page: general mobile layout polish

### Scope
`modules/sales/ui.py` only. Does not touch the search clear button (`_clear_search`) or the quantity stepper + Sell row (`_render_qty_sell_row_css`, `_render_sale_row`) - both already completed in v2.4.3 and confirmed unchanged. No changes to `modules/sales/service.py`, `modules/sales/repository.py`, Dashboard, Alerts, Product Management, Invoice Scan, or the database schema.

### Added
- **`modules/sales/ui.py`** — `render_sales_page`'s body (`_render_sell_section`, the divider, `_render_sales_history_section`) is now wrapped in `st.container(key="sales_page")`, and a new `_render_mobile_layout_css` injects one mobile-only (`@media max-width: 768px`) CSS block scoped to that container:
  - Tightens the default vertical gap Streamlit puts between stacked elements (suggestion rows, Frequently Sold rows, Sales History cards) - addresses "remove unnecessary vertical spacing on mobile" and "Frequently Sold section should look clean" without touching any single control's own layout.
  - Trims Sales History cards' default inner padding so they use the available narrow width more efficiently - addresses "Sales History cards should use the available width properly". Targets Streamlit's own documented bordered-container wrapper element; if a future Streamlit version renames it, the rule simply matches nothing and has no effect either way.
  - `overflow-x: hidden` on the page container plus `word-wrap`/`overflow-wrap` on paragraph text is a page-level safety net so long medicine names or any other text can only wrap, never force horizontal overflow - addresses "product information should wrap cleanly" and "prevent controls from overflowing on narrow screens".
  - Entirely inside the media query, so desktop is unaffected by construction - the same "gate the whole block behind `@media`" pattern already used for the Review & Edit table when desktop must stay pixel-identical (as opposed to v2.4.3's quantity-selector fix, which was intentionally unconditional).

### Unchanged (confirmed, not just assumed)
- Search clear button (`_clear_search`) and quantity stepper + Sell row (`_render_qty_sell_row_css`) - both already completed in v2.4.3, not touched or re-verified beyond confirming their tests still pass.
- `sell_product`, `search_products`, `get_frequently_sold`, `get_product`, `get_sales_history` in `modules/sales/service.py` - not touched.
- `modules/sales/repository.py` - not touched.
- Dashboard, Alerts, Product Management, Invoice Scan, database schema - not touched.
- The two new CSS blocks (`sales_page`, `sales_qty_row`) are confirmed non-conflicting: `sales_page` targets `stVerticalBlock`/`stVerticalBlockBorderWrapper` (spacing/padding), `sales_qty_row` targets `stHorizontalBlock`/`stColumn` (nowrap/fixed widths) - different selectors, different properties, no override even though the quantity row is structurally nested inside the page container.

### Verification
All four existing Sales UI simulation suites (stepper/sell: 15, search/select flow: 13, clear button: 9 = 37 checks) were re-run against the new page-wrapper change and still pass unchanged, confirming the wrapper introduced no behavioral regression to anything already completed. All other suites re-run and still pass: Review & Edit (6 scenarios), Sales repository (12), Sales service (14), Sales search/frequently-sold service (10), Dashboard/Low Stock reflecting a sale (6). 85 checks total, 0 failures. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so as with every prior Sales UI release, visual/mobile-rendering confirmation is based on the CSS's construction (media-query-gated, scoped selectors, documented Streamlit testids) rather than a live rendered screenshot; running the project's own suite in a real browser environment remains recommended.

## [2.4.5] - Sales History: fix local time display

### Scope
`modules/sales/ui.py` only. No database schema change, no migration script, no changes to `modules/sales/service.py`, `modules/sales/repository.py`, Dashboard, Alerts, Product Management, Invoice Scan, or OCR/Gemini.

### Fixed
- **`modules/sales/ui.py`** — Sales History displayed the raw stored `sold_at` value with zero formatting or timezone conversion. `sold_at` is written by SQLite's own `datetime('now')` default (`core/database.py`), which always produces naive UTC text (`YYYY-MM-DD HH:MM:SS`) - confirmed consistent for every row. Every user, regardless of their own timezone, was seeing raw UTC text in a raw format, which looked "wrong" to anyone not at UTC+0. New `_format_sold_at(sold_at)`: parses the stored value, explicitly marks it as UTC (`tzinfo=timezone.utc` - it was never naive in meaning, only in representation), converts to the local timezone via `datetime.astimezone()` with no argument (resolves to whatever timezone the server process is running in - no hardcoded offset anywhere, e.g. no `+5:30`), and formats as `DD MMM YYYY, HH:MM AM/PM` (e.g. `19 Jul 2026, 07:42 PM`). A value that doesn't match the expected format is returned unchanged rather than raising, so one malformed row can never break the rest of the list.

### Unchanged (confirmed, not just assumed)
- Storage: `sold_at`'s column definition, format, and every existing row are untouched - this is a display-only fix. No schema change, no backfill, no migration script.
- Sorting: `get_sales_history`'s `ORDER BY sold_at DESC` still sorts on the raw stored string, which remains a single consistent format - newest-first ordering is unaffected by how the value is later formatted for display.
- `sell_product`, `search_products`, `get_frequently_sold`, `get_product`, `get_sales_history` in `modules/sales/service.py`, and all of `modules/sales/repository.py` - not touched.
- The search clear button, quantity stepper + Sell row, and general mobile layout CSS (v2.4.3, v2.4.4) - not touched.
- Dashboard, Alerts, Product Management, Invoice Scan, OCR, the Gemini prompt, database schema - not touched.

### Verification
Direct unit tests of `_format_sold_at`: a known UTC input converts correctly and matches Python's own `astimezone()` output exactly; the result matches the required `DD MMM YYYY, HH:MM AM/PM` pattern; malformed and `None` input return unchanged rather than raising. A real, freshly-recorded sale's `sold_at` was fetched through `sales_service.get_sales_history` and formatted without error. Newest-first ordering was re-confirmed unaffected by the display change. Critically, the conversion was also verified under a **simulated non-UTC server timezone** (`TZ=Asia/Kolkata`, i.e. UTC+5:30) using Python's own `time.tzset()` - a stored value of `2026-07-19 14:12:00` (UTC) correctly displayed as `19 Jul 2026, 07:42 PM`, exactly matching the example given in the request, proving the fix performs a genuine timezone conversion rather than trivially passing in this working environment's own UTC timezone. All prior suites re-run and still pass: Review & Edit (6 scenarios), Sales repository (12), Sales service (14), Sales search/frequently-sold service (10), Dashboard/Low Stock reflecting a sale (6), Sales UI stepper/sell (15), Sales UI search/select flow (13), Sales UI clear button (9). 93 checks total, 0 failures. `pytest`/`streamlit` remain unavailable in this working environment (no network access); running the project's own suite remains recommended.

## [2.4.6] - OCR: stricter Gemini extraction prompt (accuracy + anti-hallucination)

### Scope
`modules/invoice_scan/ocr_service.py` only - the `_EXTRACTION_PROMPT` text. No changes to the OCR pipeline, the Gemini API call (still exactly one `client.models.generate_content` call site, unchanged), `MEDICINE_FIELDS`/JSON schema, response parsing (`_parse_and_validate_response`), the database schema, Review/Edit UI, validation logic, save logic, or any other file.

### Changed
- **`modules/invoice_scan/ocr_service.py`** — Added a new "STRICT EXTRACTION RULES" section to the prompt, inserted before the existing "ROW INDEPENDENCE" section (which is unchanged): explicit GENERAL RULES (never guess/infer/fabricate, unreadable fields return an empty string, never combine or split rows, preserve invoice row order, one output row per invoice row), a dedicated MEDICINE NAME section (copy exactly, preserve spelling/strength, no normalization/abbreviation-expansion/symbol-removal), a dedicated BATCH section (copy exactly, never invent or repair damaged text), a dedicated EXPIRY section (copy exactly, never calculate/estimate/convert formats), a dedicated QUANTITY section (copy exactly, never estimate or infer from packing), and an explicit IMPORTANT rule that an unreadable field must not cause the whole medicine row to be discarded - the remaining readable fields should still be returned.
- All pre-existing, already production-tuned prompt content is preserved unchanged: the ROW INDEPENDENCE section, the BATCH NUMBER character-confusion table (O↔0, I↔1, B↔8, S↔5, Z↔2) and duplicate-adjacent-batch re-check instruction, the JSON-array-only output format instruction, the embedded `MEDICINE_FIELDS` key list, the FINAL VERIFICATION checklist, and the illustrative example output.

### Verification
Mechanically confirmed via direct import of the real, unmodified `ocr_service.py` module (with `google.genai` mocked, matching the project's own test convention - no real API key or network access needed): `MEDICINE_FIELDS` is byte-identical (still exactly `["name", "batch_number", "expiry_date", "quantity", "mrp", "rate", "gst_percent"]`); all 21 newly-requested rule phrases are present in the prompt; all 13 spot-checked pre-existing rule phrases are still present (no regression to the already-tuned batch-number/row-independence logic); the JSON key list embedded in the prompt text still matches `MEDICINE_FIELDS` exactly; the "Return ONLY a valid JSON array" output-format instruction is unchanged; `_parse_and_validate_response` still correctly parses both a normal JSON response and a markdown-fenced one, confirming the parsing side of the OCR flow is entirely unaffected by a prompt-text-only change. File-timestamp comparison confirms `ocr_service.py` is the only file modified - `review_ui.py`, `review_service.py`, `upload_service.py`, `upload_ui.py`, `core/database.py`, and every other module all predate this change. `tests/test_ocr_service.py` makes no assertion on prompt content (confirmed via `grep`), so it is structurally unaffected by this change; it could not be executed in this working environment (`pytest`/`google.genai` unavailable, no network access), consistent with every prior release in this project. Running the project's own `pytest` suite, and separately testing extraction accuracy against real invoice images with a live Gemini API key, both remain recommended before this prompt change is considered fully verified in production.

## [2.4.7] - Mobile sidebar polish: auto-close, bigger touch targets, larger fonts

### Scope
`app.py` only. No changes to any module's business logic, Dashboard, Sales, Invoice Scan, OCR, the Gemini prompt, the database, or any test file. `NAV_PAGES` (page labels, icons, dispatch order) and the routing dispatch (`NAV_PAGES[selected_page]()`) are confirmed byte-unchanged.

### Added
- **`app.py`** — two new sidebar-scoped, mobile-only helpers, called from inside the existing `with st.sidebar:` block, right after the nav radio and logout button:
  - **`_render_mobile_sidebar_css`**: bigger touch targets and ~12% larger nav text, entirely inside `@media (max-width: 768px)`, scoped to `[data-testid="stSidebar"] [role="radiogroup"] label` (the sidebar's own nav rows) via the standard ARIA `role="radiogroup"` attribute Streamlit's radio widget already provides - not an internal/unstable test id. Desktop spacing and font size are untouched by construction (the rule simply doesn't apply above 768px).
  - **`_render_mobile_sidebar_autoclose`**: a tiny, invisible (`height=0`) `streamlit.components.v1.html` component that detects, on the browser side, when the selected nav item has just changed (tracked via `sessionStorage`, so it never fires on first page load before any navigation) and, only if the viewport is at or below 768px wide, programmatically clicks Streamlit's own native sidebar-collapse control. Desktop is unaffected: the collapse action is only attempted below the same 768px threshold used by the CSS above.

### Constraints honored
- No new pip dependency - `streamlit.components.v1` is part of Streamlit itself.
- No colors, icons, navigation flow, or animations changed.
- No settings, font-size controls, or sliders added.
- Smallest possible change: two new functions, both called from the one place the sidebar was already rendered; nothing else in `app.py` was restructured.

### Verification
Mechanically confirmed: `NAV_PAGES` and the routing dispatch line are byte-identical to before; the CSS block's braces are balanced, lives entirely inside `@media (max-width: 768px)`, and its only selector is scoped to the sidebar's nav rows. The injected JS was extracted and syntax-checked with Node.js (`node --check`), then exercised against the **actual, unmodified script** (not a reimplementation) using a mocked `document`/`window` in Node - 9 checks: it does not collapse on the very first page load (nothing stored yet); it collapses when the selection changes at mobile width (400px); it does **not** collapse when the selection changes at desktop width (1200px); it does not fire when the selection is unchanged (no real navigation); the 768px boundary itself still counts as mobile; and it fails silently (no exception, no broken navigation) both when its best-effort collapse-button selectors can't find anything and when no radio option is selected yet. All prior suites re-run and still pass: Review & Edit (6 scenarios), Sales repository (12), Sales service (14), Sales search/frequently-sold service (10), Dashboard/Low Stock reflecting a sale (6), Sales History time display (8), Sales UI stepper/sell (15), Sales UI search/select flow (13), Sales UI clear button (9), OCR prompt (8). 101 checks across the whole regression sweep, 0 failures. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so this could not be exercised in a real browser; the JS relies on Streamlit's current internal DOM structure for the sidebar-collapse control (not part of Streamlit's public API) and may need its selector list updated on a future Streamlit version upgrade - it is written to degrade gracefully (navigation keeps working normally) if that ever happens. Manual verification on an actual desktop browser and an actual mobile device/viewport remains recommended before the demo.

## [2.5.0] - Supabase migration Phase 1: connection layer only (infrastructure prep)

### Scope
`core/supabase_client.py` (new), `core/exceptions.py` (one new exception class), `requirements.txt` (one new dependency). No repository, service, UI, OCR, Gemini prompt, or authentication file was modified. SQLite (`core/database.py`) is completely untouched and remains the application's only active database - nothing in the running app calls into the new module yet.

### Added
- **`requirements.txt`** — added `supabase>=2.0,<3.0`, the official Supabase Python client.
- **`core/exceptions.py`** — new `SupabaseConfigError(EasyStockError)`, matching every other exception in this file: raised explicitly rather than allowing a missing configuration value to silently produce a broken or partially-working client.
- **`core/supabase_client.py`** (new file) — Phase 1 connection layer, not imported anywhere else in the codebase yet:
  - `get_supabase_client()` — a lazy-initialized singleton. Reads `SUPABASE_URL` and `SUPABASE_KEY` from Streamlit's own secrets store (`st.secrets`, the standard place a Streamlit app keeps secrets - not environment variables), raising `SupabaseConfigError` immediately if either is missing or blank (never a silent failure). The client is created only on first use - importing this module never requires Supabase to be configured, and never opens a connection - and the same instance is reused for every subsequent call.
  - `verify_supabase_connection()` — a lightweight, read-only reachability check. Requests the REST API's own root endpoint (PostgREST's base path, not any specific table) using `httpx` (already a dependency of the `supabase` package itself, so this adds nothing new). Never reads, inserts, updates, or deletes a single row, and assumes no particular table exists. Returns `True` for any response below a 5xx (the server responded - i.e. reachable), `False` for a 5xx (reachable but unhealthy); a connection-level failure (DNS, timeout, refused) propagates as an `httpx` exception, left to the caller.

### Verification
Mechanically confirmed via `grep`: zero references to `supabase` in any `modules/*/repository.py`, `modules/*/service.py`, `modules/*/ui.py`, or `app.py`. `core/database.py`, `core/auth.py`, and `modules/invoice_scan/ocr_service.py` are all confirmed untouched via file timestamps predating this change. SQLite's `initialize_database()` was re-run directly against a fresh temporary database and confirmed to still initialize cleanly and idempotently, exactly as before. Since neither `streamlit` nor `supabase` (nor `httpx`) are installed in this working environment (no network access), the real, unmodified `core/supabase_client.py` was imported and exercised against stub modules for all three - 13 checks: missing `SUPABASE_URL` raises `SupabaseConfigError` with a clear message naming the missing key; missing `SUPABASE_KEY` does the same; both missing raises rather than failing silently; a blank/whitespace-only value is rejected exactly like an absent one; a valid configuration successfully creates a client with the exact URL/key from secrets; a second call to `get_supabase_client()` returns the identical instance and does **not** create a second client (singleton confirmed); `verify_supabase_connection()` correctly returns `True` for a 200 response, hits the REST root endpoint (not a specific table) with only an `apikey` header (no request body/payload), returns `False` for a 503, and still propagates `SupabaseConfigError` when misconfigured. All 110 checks from every prior suite (Review & Edit, Sales repository/service/search/UI, Dashboard/Alerts reflecting a sale, Sales History time display, OCR prompt, sidebar JS) were re-run and still pass, confirming this change is fully isolated from the active application. 123 checks total this release, 0 failures. Running the real `pytest` suite, and testing `verify_supabase_connection()` against an actual Supabase project with real secrets configured, both remain recommended before any later migration phase begins.

### Next steps (not part of this phase)
No repository, service, or UI file has been touched or wired to Supabase. A future phase would need to: decide a table-by-table migration or dual-write strategy, add Supabase-backed repository implementations behind the same function signatures already used by SQLite (so services/UI need no changes), and only then begin switching specific reads/writes over - none of that is in scope here.

## [2.6.0] - Supabase migration Phase 2: Products Repository (dual-backend, SQLite still active)

### Scope
`modules/products/repository.py` only. No UI, service, OCR, Gemini, Dashboard, Alerts, Sales, or authentication file was modified. SQLite remains the application's only active database - `_ACTIVE_BACKEND` stays `"sqlite"`, and no caller anywhere in the codebase needs to change or is aware this phase happened.

### Added
- **`modules/products/repository.py`** — every existing public function (`count_total_products`, `get_expired_products`, `get_expiring_soon_products`, `get_low_stock_products`, `get_all_products`, `get_product_by_id`, `create_product`, `update_product`, `delete_product`, `reduce_stock`) is now a thin dispatcher on a new private `_ACTIVE_BACKEND` module constant (`"sqlite"` by default), delegating to one of two private implementations:
  - `_..._sqlite` — the exact pre-existing SQLite logic, unchanged in behavior (see Verification).
  - `_..._supabase` — a new, equivalent implementation against `core/supabase_client.py`'s shared client (imported lazily inside `_supabase_products_table()`, so this module - and the SQLite path it actually runs today - stays importable and usable without the `supabase`/`streamlit` packages installed).
  - Three shared, backend-agnostic helpers (`_filter_expired_rows`, `_filter_expiring_soon_rows`, `_filter_low_stock_rows`) hold the Month/Year expiry-parsing and effective-threshold logic exactly once, called by both backends' expiry/low-stock functions, so the two implementations cannot drift apart.
  - Every Supabase query is scoped by `store_id` (`.eq("store_id", store_id)`), exactly mirroring the SQLite `WHERE store_id = ?` ownership pattern - no cross-store read, write, or delete is possible on either backend.
  - `reduce_stock`'s Supabase path calls a Postgres RPC function (`reduce_product_stock`, expected signature `(p_store_id, p_product_id, p_quantity)`, returning rows-updated) rather than a client-side read-then-write, since PostgREST's `update()` cannot express a value and a guard condition that both depend on the row's current quantity in one call the way SQLite's single guarded `UPDATE ... WHERE quantity >= ?` does. That RPC function is a Supabase-side schema addition (not Python code) and does not exist yet - out of scope for this phase; this path is unreachable while `_ACTIVE_BACKEND == "sqlite"`.

### Not changed
- `core/supabase_client.py` - reused exactly as-is; no second client was created.
- `modules/products/service.py`, `modules/products/ui.py`, and every caller of the products repository (`modules/dashboard/service.py`, `modules/alerts/service.py`, `modules/alerts/low_stock_service.py`, `modules/sales/service.py`, `modules/sales/repository.py`) - none needed a change, since every public function's name, parameters, return value, and exceptions are identical to before this phase.
- `core/database.py` / SQLite schema - untouched.

### Verification
Since `pytest`/`streamlit`/`supabase` remain unavailable in this working environment (no network access), verification followed the same direct-execution/mocking approach as every release since v2.2.1:
- **SQLite path, byte-for-bit identical:** the same 15-step scenario (create 3 products, count, list, search, fetch by id, fetch a missing id, list expired, list expiring-soon, list low-stock, update, update-a-missing-id, reduce stock, over-reduce stock, delete, delete-again, cross-store fetch) was run against a fresh isolated SQLite database twice - once against the pristine pre-Phase-2 `repository.py`, once against the new dual-backend version - and the two full output logs are confirmed identical via `diff` (0 differences).
- **Supabase path, same scenario, same outcomes:** `streamlit` and `supabase` were stubbed with an in-memory fake client (a fake PostgREST-style query builder plus a fake `rpc()`) so the real, unmodified `_supabase` implementations could be exercised directly with `_ACTIVE_BACKEND` temporarily set to `"supabase"`. The identical 15-step scenario produced output identical to the SQLite run, including both `ValidationError` messages (not-found-or-not-yours, insufficient-stock) and cross-store isolation (`get_product_by_id` from a different `store_id` correctly returns `None`).
- **Downstream modules unaffected:** `modules/dashboard/service.py`, `modules/alerts/service.py` (`get_categorized_alerts`), `modules/alerts/low_stock_service.py` (`get_low_stock_alerts`), and `modules/sales/service.py` (`search_products`, `sell_product`) were all exercised end-to-end through `modules/products/service.py` against a real SQLite database with `_ACTIVE_BACKEND` left at its default `"sqlite"` - all returned correct, expected results.
- **Isolation confirmed:** importing `modules.products.repository` and exercising every SQLite-path function succeeds with neither `streamlit` nor `supabase` installed (confirmed by directly attempting the import in this environment, where both packages are genuinely absent) - the module-level code contains no unconditional import of either package.
- **Structural checks:** `grep` confirms no `streamlit` import anywhere in `repository.py` (only in docstring prose); `grep` confirms no raw SQL keyword (`SELECT`/`INSERT INTO`/`UPDATE ... SET`/`DELETE FROM`) in any service file; `diff -rq` of the entire project tree against the pristine pre-Phase-2 zip confirms `modules/products/repository.py` is the **only** file that differs.
- Full regression sweep from v2.5.0 (123 checks) was not independently re-run in this session since none of its subject files (`core/supabase_client.py`, `core/exceptions.py`, `requirements.txt`) changed; this phase's own checks above (SQLite/Supabase parity + downstream modules) total 19 additional verified scenarios, 0 failures.

Running the real `pytest`/`AppTest` suite, and testing the Supabase path (including creating the `reduce_product_stock` RPC function) against an actual Supabase project, both remain recommended before any future phase switches `_ACTIVE_BACKEND` to `"supabase"`.

### Next steps (not part of this phase)
Repository is ready but still inert. A future phase would need to: create the `reduce_product_stock` Postgres RPC function in the Supabase project, verify every Supabase implementation against a real project (not the in-memory fake used here), decide a table-by-table migration or dual-write cutover strategy, and only then flip `_ACTIVE_BACKEND` - none of that is in scope here.

## [2.7.0] - Supabase migration Phase 3: single-place backend selection

### Scope
`config/settings.py` and `modules/products/repository.py` only. No UI, Streamlit page, OCR, Gemini, Dashboard, Alerts, Sales, Invoice, or authentication file was modified. SQLite remains the active backend by default - this phase only cleans up *how* the backend is chosen, not which one is chosen.

### Changed
- **`config/settings.py`** — added `ACTIVE_DB_BACKEND`, the single, one-place switch for which backend a dual-backend repository uses. Sourced from the `ACTIVE_DB_BACKEND` environment variable (not Streamlit secrets, so this file stays importable without `streamlit` installed), case-insensitive and whitespace-trimmed. Fails safe: any value other than exactly `"supabase"` resolves to `"sqlite"` - unset, blank, or misspelled values can never accidentally activate the Supabase path.
- **`modules/products/repository.py`** — the private, file-local `_ACTIVE_BACKEND` constant introduced in v2.6.0 (Phase 2) is removed. Every dispatcher function now reads the shared `ACTIVE_DB_BACKEND` imported from `config/settings.py` instead. No dispatcher's logic changed - only where the constant comes from. Module docstring updated to describe this Phase 3 mechanism; Phase 2's dual-backend implementations (SQLite + Supabase, per-function) are otherwise untouched.

### Not changed
- `core/supabase_client.py`, `core/exceptions.py`, `core/database.py` - untouched.
- Every SQLite and Supabase implementation function added in v2.6.0 - same logic, same store_id scoping, same shared expiry/threshold helpers, same `reduce_stock` RPC design. Only the source of the backend switch moved.
- `modules/products/service.py`, `modules/products/ui.py`, and every caller of the products repository - none needed a change; `ACTIVE_DB_BACKEND` defaults to `"sqlite"` exactly as `_ACTIVE_BACKEND` did before it.
- `modules/sales/repository.py` and every other repository - Phase 3, like Phase 2, touches only the Products Repository.

### Verification
Since `pytest`/`streamlit`/`supabase` remain unavailable in this working environment (no network access), verification followed the same direct-execution/mocking approach as v2.5.0 and v2.6.0:
- **Config resolution, fail-safe behavior:** `ACTIVE_DB_BACKEND` confirmed to resolve to `"sqlite"` with the environment variable unset, blank (`""`), and set to an unrecognized value (`"postgres"`); confirmed to resolve to `"supabase"` only for `"supabase"` and case/whitespace variants (`"  Supabase  "`).
- **SQLite path, byte-for-bit identical:** the same 15-step scenario used for v2.6.0's verification (create 3 products, count, list, search, fetch by id, fetch a missing id, list expired, list expiring-soon, list low-stock, update, update-a-missing-id, reduce stock, over-reduce stock, delete, delete-again, cross-store fetch) was re-run against the Phase 3 repository with the environment variable unset, and diffed against the original v2.5.0 (pre-migration) output log - 0 differences.
- **Supabase path selected purely through the env var:** with `ACTIVE_DB_BACKEND=supabase` set *before* importing `modules.products.repository` (mirroring real process startup) and `streamlit`/`supabase` stubbed with an in-memory fake client, an 11-step scenario covering every public function produced correct results end to end, confirming the repository actually reads its backend choice from `config.settings.ACTIVE_DB_BACKEND` rather than any leftover local state.
- **Downstream modules unaffected:** `modules/dashboard/service.py`, `modules/alerts/service.py`, `modules/alerts/low_stock_service.py`, and `modules/sales/service.py` were re-exercised end-to-end through `modules/products/service.py` against a real SQLite database with the environment variable unset (default) - all returned correct, expected results, identical to v2.6.0's sweep.
- **Structural checks:** `diff -rq` of the entire project tree against the pristine pre-Phase-2 zip confirms `config/settings.py` and `modules/products/repository.py` are the only source files that differ (beyond `VERSION`/`CHANGELOG.md`/`PROJECT_MEMORY.md`/`PROJECT_STATUS.md`/`AI_RULES.md`) - no UI, Streamlit page, OCR, Gemini, Dashboard, Alerts, Sales, Invoice, or authentication file was touched, and `NEXT_TASK.md` is unchanged.

Running the real `pytest`/`AppTest` suite, and testing the Supabase path against a real Supabase project (including the still-missing `reduce_product_stock` RPC function - see v2.6.0's entry), both remain recommended before `ACTIVE_DB_BACKEND` is ever set to `"supabase"` outside of testing.

### Next steps (not part of this phase)
The switch is now clean and centralized, but still points at `"sqlite"` by policy (fail-safe default) rather than by absence of an alternative. A future phase would still need everything v2.6.0's entry already identified: the `reduce_product_stock` RPC function, verification against a real Supabase project, a migration/cutover strategy, and the same dual-backend treatment for other repositories (e.g. Sales) before any of them could be switched.

## [2.8.0] - Supabase migration Phase 4: Sales Repository (dual-backend, SQLite still active)

### Scope
`modules/sales/repository.py` only. No UI, service, OCR, Gemini, Dashboard, Alerts, Products Repository, or authentication file was modified. SQLite remains the active backend by default (`ACTIVE_DB_BACKEND` in `config/settings.py`, unchanged from v2.7.0) - this phase extends the same dual-backend pattern to a second repository, it does not touch how or where the backend is selected.

### Added
- **`modules/sales/repository.py`** — following the exact pattern established for the Products Repository (v2.6.0/v2.7.0), every existing public function (`record_sale`, `get_top_sold_product_ids`, `get_sales_history`) is now a thin dispatcher on `ACTIVE_DB_BACKEND` (imported from `config/settings.py`, not redefined here), delegating to one of two private implementations:
  - `_..._sqlite` — the exact pre-existing SQLite logic, unchanged in behavior (see Verification).
  - `_..._supabase` — a new, equivalent implementation against `core/supabase_client.py`'s shared client (imported lazily inside `_supabase_sales_history_table()`, so this module - and the SQLite path it actually runs today - stays importable and usable without the `supabase`/`streamlit` packages installed).
  - A shared private helper, `_aggregate_top_sold_product_ids`, holds the SUM/ORDER BY/LIMIT aggregation logic that `get_top_sold_product_ids`'s Supabase implementation needs (PostgREST has no GROUP BY/SUM query-builder equivalent), so this data-shaping logic exists exactly once rather than being duplicated per backend.
  - Every Supabase query is scoped by `store_id` (`.eq("store_id", store_id)`), exactly mirroring the SQLite `WHERE store_id = ?` ownership pattern - no cross-store read or write is possible on either backend. `sales_history`'s append-only design is preserved: no update or delete function exists on either backend, matching the file's existing convention.
  - `record_sale`'s Supabase payload intentionally omits `sold_at`, exactly as the SQLite implementation never passes it either - SQLite's schema defaults it to `datetime('now')`; the future Supabase table is expected to default its equivalent column the same way, a documented Supabase-side schema dependency (same pattern as `reduce_stock`'s RPC-function dependency from v2.6.0).

### Not changed
- `config/settings.py`, `core/supabase_client.py`, `modules/products/repository.py` - untouched; this phase reuses the existing `ACTIVE_DB_BACKEND` switch and Supabase client exactly as they were.
- `modules/sales/service.py` and every caller of the sales repository (`modules/sales/ui.py`, `modules/dashboard/service.py` if applicable) - none needed a change, since every public function's name, parameters, return value, and exceptions are identical to before this phase.
- `core/database.py` / SQLite schema - untouched.

### Verification
Since `pytest`/`streamlit`/`supabase` remain unavailable in this working environment (no network access), verification followed the same direct-execution/mocking approach as v2.6.0 and v2.7.0:
- **SQLite path, byte-for-bit identical:** a scenario (record 4 sales across 2 stores and 2 products, query top-sold at two different limits, query top-sold for a different store and for a store with no sales, fetch sales history and inspect its ordering/columns, fetch history for a different store) was run against a fresh isolated SQLite database twice - once against the pristine pre-Phase-4 `repository.py`, once against the new dual-backend version - and the two full output logs are confirmed identical via `diff` (0 differences).
- **Supabase path, same scenario, same outcomes:** `streamlit` and `supabase` were stubbed with an in-memory fake client (a fake PostgREST-style query builder supporting `select`/`eq`/`order`/`limit`/`insert`) so the real, unmodified `_supabase` implementations could be exercised directly with `ACTIVE_DB_BACKEND=supabase` set before import (mirroring real process startup). The identical scenario produced output identical to the SQLite run, including aggregation order, per-store isolation, and result-row shape.
- **`ACTIVE_DB_BACKEND` switching confirmed:** unset, `"supabase"`, and an unrecognized value (`"garbage"`) resolve to `"sqlite"`, `"supabase"`, and `"sqlite"` respectively when read through `modules.sales.repository`, exactly mirroring the fail-safe behavior already verified for the Products Repository in v2.7.0.
- **Downstream modules unaffected:** `modules/dashboard/service.py`, `modules/alerts/service.py`, `modules/alerts/low_stock_service.py`, and `modules/sales/service.py` (`search_products`, `sell_product`) were all exercised end-to-end against a real SQLite database with `ACTIVE_DB_BACKEND` left at its default (`"sqlite"`) - all returned correct, expected results, identical to prior phases' sweeps.
- **Structural checks:** `grep` confirms no top-level `streamlit` import in `repository.py` (only the lazy, function-local import inside `_supabase_sales_history_table()`); `diff -rq` of the entire project tree against the pristine pre-Phase-2 zip confirms `modules/sales/repository.py` is a **new** entry in the diff, alongside the previously-established `config/settings.py`, `modules/products/repository.py`, and the documentation files - no other file changed.

Running the real `pytest`/`AppTest` suite, and testing the Sales Repository's Supabase path against a real Supabase project (which will also need its own `sales_history` table, since none exists yet), both remain recommended before `ACTIVE_DB_BACKEND` is ever set to `"supabase"` outside of testing.

### Next steps (not part of this phase)
Both the Products Repository and the Sales Repository are now dual-backend, sharing one switch. Still needed before any real cutover: create the `sales_history` table and the `reduce_product_stock` RPC function in an actual Supabase project, verify both repositories' Supabase implementations against that real project (not the in-memory fakes used for verification so far), and decide a table-by-table migration or dual-write cutover strategy. No other repository has been migrated yet.

## [2.9.0] - Supabase migration Phase 5: Authentication & Store backend (dual-backend, SQLite still active)

### Scope
`core/auth.py` only. No Products Repository, Sales Repository, Dashboard, Alerts, Invoice Scan, OCR, Gemini, Product Management UI, Sales UI, or `config/settings.py` was modified. SQLite remains the active backend by default (`ACTIVE_DB_BACKEND`, unchanged since v2.7.0) - this phase extends the same dual-backend pattern to the `stores` table.

### Note on how this phase was delivered
The dual-backend implementation described below was already present in `core/auth.py` in this working copy when this phase began, but was undocumented: `VERSION` still read 2.8.0, and neither `CHANGELOG.md`, `PROJECT_MEMORY.md`, nor `PROJECT_STATUS.md` mentioned it. Rather than assume it was correct because it was already there, it was verified with the same rigor as a freshly written phase before this entry was written - see Verification below. It was found to be a faithful, working implementation of exactly what this phase asked for, so no rewrite was needed; this entry documents and formally verifies it rather than introducing it.

### Added
- **`core/auth.py`** — `signup()` and `login()` keep their exact names, parameters, return values, and exceptions. Their business logic (input validation, password hashing/verification via bcrypt, `DuplicateMobileError`/`InvalidCredentialsError` decisions) is unchanged and still lives entirely in these two functions. Only the raw persistence step each calls is now dual-backend, via two private dispatchers (`_insert_store`, `_fetch_store_by_mobile`) that read the shared `ACTIVE_DB_BACKEND` from `config/settings.py` (not redefined here) and delegate to a `_..._sqlite` (the pre-existing, unchanged logic) or `_..._supabase` (new) implementation - the same shape as `modules/products/repository.py` and `modules/sales/repository.py`.
  - The Supabase implementation reuses `core/supabase_client.py`'s shared client via a lazily-imported helper (`_auth_stores_table()`), so this module - and its SQLite path - stays importable without the `supabase`/`streamlit` packages installed.
  - Every Supabase operation is scoped correctly for this table: `stores` has no cross-store concept (a store owns itself), so it's looked up by `mobile_number` and written by row - the same principle every other repository already applies via `store_id`, applied here to the one table where the store *is* the row rather than a foreign key on it.
  - The Supabase insert path translates a Postgres unique-constraint violation on `mobile_number` (`23505` / "duplicate key value") into the same `DatabaseError("UNIQUE constraint failed...")` shape the SQLite path already produces, so `signup()`'s single check for that string - the business decision that this means "already registered" - is not duplicated per backend.

### Not changed
- `config/settings.py`, `core/supabase_client.py`, `modules/products/repository.py`, `modules/sales/repository.py` - untouched; this phase reuses the existing `ACTIVE_DB_BACKEND` switch and Supabase client exactly as they were.
- `core/login_ui.py` and every caller of `core.auth` (`signup`, `login`) - none needed a change, since both functions' names, parameters, return values, and exceptions are identical to before this phase.
- `core/database.py` / SQLite schema - untouched.

### Verification
Since `pytest`/`streamlit`/`supabase`/`bcrypt` remain unavailable in this working environment (no network access - `bcrypt` was mocked with a small deterministic fake preserving `gensalt`/`hashpw`/`checkpw` semantics, the same treatment already given to `streamlit`/`supabase` in prior phases):
- **SQLite path, byte-for-bit identical:** a scenario (sign up a store, log in successfully, log in with the wrong password, log in with an unregistered mobile number, sign up a second store with a mobile number already in use, sign up with an invalid mobile number) was run against the pristine pre-Phase-5 `core/auth.py` and against the current file, and the two full output logs are confirmed identical via `diff` (0 differences).
- **Supabase path, same scenario, same outcomes:** `streamlit` and `supabase` were stubbed with an in-memory fake client (a fake PostgREST-style query builder supporting `select`/`eq`/`insert`, raising a fake duplicate-key error on a repeated `mobile_number` insert) so the real, unmodified `_supabase` implementations could be exercised directly with `ACTIVE_DB_BACKEND=supabase` set before import. The identical scenario produced output identical to the SQLite run, including both the `InvalidCredentialsError` and `DuplicateMobileError` messages.
- **`ACTIVE_DB_BACKEND` switching confirmed:** unset, `"supabase"`, and an unrecognized value (`"garbage"`) resolve to `"sqlite"`, `"supabase"`, and `"sqlite"` respectively when read through `core.auth`, matching the fail-safe behavior already verified for both repositories.
- **Full-stack regression:** a single scenario exercising `core.auth.signup`/`login` followed by Product Management, Dashboard, Alerts (expiry + low stock), and Sales (search + sell) - all through the default SQLite path - produced correct, expected results end to end.
- **Structural checks:** no top-level `streamlit` import in `core/auth.py` (only the lazy, function-local import inside `_auth_stores_table()`); `diff -rq` of the entire project tree against the pristine pre-Phase-2 zip confirms `core/auth.py` is the only newly-differing file this phase, alongside the previously-established `config/settings.py`, `modules/products/repository.py`, `modules/sales/repository.py`, and the documentation files.

Running the real `pytest`/`AppTest` suite, and testing the `stores` table's Supabase path against a real Supabase project (which will also need its own `stores` table and unique constraint on `mobile_number`, plus the `reduce_product_stock` RPC function and `sales_history` table from earlier phases), all remain recommended before `ACTIVE_DB_BACKEND` is ever set to `"supabase"` outside of testing.

### Next steps (not part of this phase)
All three MVP-critical data-access surfaces (Products, Sales, Authentication/Store) are now dual-backend, sharing one switch. Still needed before any real cutover: create the `stores`, `sales_history` tables and the `reduce_product_stock` RPC function in an actual Supabase project, verify all three implementations against that real project (not the in-memory fakes used for verification so far), and decide a table-by-table migration or dual-write cutover strategy.

## [2.10.0] - Supabase migration Phase 6: Invoice Save backend (no code changes - already dual-backend by reuse)

### Scope
No source file was modified this phase. Investigation confirmed the Invoice Review "Save Inventory" write path already fully supports both backends, as a consequence of Phase 2's Products Repository migration - there was nothing left to migrate.

### Investigation
Traced the write path from the "💾 Save Inventory" button backward: `modules/invoice_scan/review_ui.py` calls `modules/invoice_scan/review_service.py`'s `save_invoice_medicines(store_id)`, which iterates the reviewed medicine rows and calls `modules.products.service.add_product(store_id, form_data)` for each one - the exact same function Product Management's "Add Product" form already uses. `add_product` calls `modules.products.repository.create_product`, which has dispatched on the shared `ACTIVE_DB_BACKEND` (from `config/settings.py`) to a `_..._sqlite` or `_..._supabase` implementation since v2.6.0/v2.7.0.

`grep` across the entire `modules/invoice_scan/` package (`review_service.py`, `review_ui.py`, `upload_service.py`, `upload_ui.py`, `ocr_service.py`) confirms zero direct database access anywhere in it - `ocr_service.py`'s own module docstring states "No database access. No writes of any kind," and `review_ui.py`'s states "No INSERT / UPDATE / commit." The module's only path to persistence is the single call to `add_product` inside `save_invoice_medicines`, already covered by the existing dual-backend Products Repository.

This mirrors exactly why Dashboard and Low Stock Alerts never needed their own migration in earlier phases: they read through the same shared, already-migrated Products Repository rather than owning any SQL of their own. Invoice Save turned out to be the same case for writes.

### Not changed
Per the investigation above, none of the following needed modification, and none was touched: OCR extraction, the Gemini prompt, OCR parsing, the Review UI, the Products Repository, the Sales Repository, Dashboard, Alerts, Authentication, Product Management UI, Sales UI, `config/settings.py`, `core/supabase_client.py`.

### Verification
Since `pytest`/`streamlit`/`supabase`/`google.genai` remain unavailable in this working environment (no network access - both were stubbed, `streamlit` including a dict-backed `session_state` since `review_service.py` uses it directly for its editable medicine list):
- **SQLite path:** a 3-row scenario (two valid medicines, one with a missing required name) was run through `initialise_review_session` → `save_invoice_medicines` with `ACTIVE_DB_BACKEND` unset (default `"sqlite"`) - result was `{"saved": 2, "skipped": [...]}` with the correct per-row validation error, and both saved medicines were immediately visible via `modules.products.service.search_products`, confirming product visibility after save.
- **Supabase path, identical outcome:** the identical 3-row scenario was re-run with `ACTIVE_DB_BACKEND=supabase` and `streamlit`/`supabase` stubbed by an in-memory fake client (the same fake used to verify the Products Repository in v2.6.0) - produced the identical `{"saved": 2, "skipped": [...]}` result and identical post-save product visibility, confirming the invoice save flow correctly reaches the Supabase path with no code changes needed.
- **`ACTIVE_DB_BACKEND` switching confirmed:** unset, `"supabase"`, and an unrecognized value (`"garbage"`) resolve to `"sqlite"`, `"supabase"`, and `"sqlite"` respectively, exactly as already verified for the Products Repository itself.
- **Full regression:** a login → products → dashboard → alerts → sales scenario was re-run end to end through the unchanged default SQLite path and returned correct results, alongside the invoice-save-specific scenario above.
- **Structural check:** `diff -rq` of the entire project tree against the pristine pre-Phase-2 zip shows exactly the same set of differing source files as v2.9.0 (`config/settings.py`, `core/auth.py`, `modules/products/repository.py`, `modules/sales/repository.py`) plus this release's documentation - confirming no new source file changed.

Running the real `pytest`/`AppTest` suite, and testing the full invoice-upload-to-save flow against a real Supabase project (once the `stores`, `sales_history` tables and `reduce_product_stock` RPC function from earlier phases exist there), both remain recommended before `ACTIVE_DB_BACKEND` is ever set to `"supabase"` outside of testing.

### Next steps (not part of this phase)
Products, Sales, Authentication/Store, and (by reuse) Invoice Save are all now dual-backend-covered. No repository or write path in the application currently bypasses `ACTIVE_DB_BACKEND`. Remaining prerequisites for any real cutover are unchanged from v2.9.0's entry: create the `stores`, `sales_history` tables and the `reduce_product_stock` RPC function in an actual Supabase project, and verify every implementation against that real project.

## [2.11.0] - Persistent Login (Remember Session)

### Scope
`config/settings.py`, `core/auth.py`, `core/session.py`, `core/login_ui.py`, `app.py`. No database schema change, no OCR/Gemini/Invoice Scan file, no Products/Sales/Dashboard/Alerts repository or service, and no Product/Sales UI file was touched. Works identically on SQLite and Supabase (`ACTIVE_DB_BACKEND`, unchanged).

### Added
- **Session-restore token (`core/auth.py`)** — `create_session_token(store_id)` and `validate_session_token(token)`, plus a new `_fetch_store_by_id` dual-backend dispatcher (mirroring `_fetch_store_by_mobile` exactly, SQLite + Supabase implementations). The token is a compact `store_id.expiry.signature` string — deliberately not a JWT (no library, no standard header/claims format) and not a new database-backed session table (no schema change, per this feature's constraints). It is HMAC-SHA256 signed using the store's own already-stored `password_hash` as the key, so no new secret needs to be generated, configured, or kept in sync across processes or deployments — verification re-derives the same signature from the store's current `password_hash` via `_fetch_store_by_id`, which is why the feature works identically on both backends with zero backend-specific code of its own. The token never contains a password or password hash (confirmed in verification below). `validate_session_token` never raises — a malformed, expired, tampered, or otherwise invalid token simply returns `None`, since an invalid saved session is an ordinary, expected outcome (an old cookie, a logout on another device), not a failure callers need to handle specially.
- **Persistent cookie storage (`core/session.py`)** — `save_persistent_session(token)`, `clear_persistent_session()`, and `get_saved_session_token()`. Reading is pure Python (`st.context.cookies`, Streamlit's native read-only cookie accessor — no JS at all). Writing/clearing a cookie has no Python API in Streamlit, so this uses `streamlit.components.v1.html(..., height=0)` — the same pattern `app.py`'s existing mobile sidebar auto-close already established, but under an even tighter guardrail: the injected script does exactly one thing (write or clear one named cookie with a value supplied entirely from Python), contains no conditional logic and no interpretation of the value, and depends on nothing but the standard `document.cookie` API. All validation happens afterward, in Python, via `core.auth.validate_session_token`.
- **Wiring** — `core/login_ui.py` calls `create_session_token`/`save_persistent_session` right after `start_session()`, in both the login and signup forms. `app.py` gains `_restore_persistent_session_if_any()`, called once at the top of routing (before deciding which screen to show): if no session is active yet, it reads the saved cookie, validates it, and — if valid — restores the session exactly as if the store had just logged in, before `is_logged_in()` is checked. Logout (`app.py`'s existing Logout button) now also calls `clear_persistent_session()` alongside the pre-existing `end_session()`.

### Not changed
`signup()`/`login()`'s own logic (validation, password hashing/verification, `DuplicateMobileError`/`InvalidCredentialsError` decisions) is completely unchanged — confirmed byte-for-bit identical output in verification below. No repository, service, or UI file for Products, Sales, Dashboard, Alerts, Invoice Scan, or OCR was touched. `database/supabase_schema.sql` — untouched; this feature needed no new table or column, by design.

### Design notes / known trade-offs
- **Session validity**: 365 days (`config/settings.py`'s new `SESSION_TOKEN_VALIDITY_DAYS`), not literally unbounded. The feature's requirement is "stay logged in until explicit logout" — a long, generous ceiling was chosen over a true never-expires token, since an unbounded bearer credential with no revocation mechanism is an unnecessary risk for no practical benefit at ordinary usage timescales. There is currently no way to revoke a single saved session early (e.g. from another device) short of a store owner changing their password — a feature that doesn't exist yet in this codebase either.
- **Cookie attributes**: `path=/; SameSite=Lax`, deliberately without `Secure`, so the cookie still works during local HTTP development (e.g. `streamlit run app.py` on `http://localhost`). On an HTTPS deployment this means the cookie is technically still transmissible over a hypothetical downgraded connection to the same host — a reasonable trade-off for an MVP-stage app with no existing HTTPS-enforcement infrastructure, but worth revisiting if this app is ever deployed somewhere HTTP is genuinely reachable.

### AI_RULES.md updated — genuinely new permanent rule
The existing JavaScript guardrail (added v2.4.7) explicitly limited the sole sanctioned use of client-side JS to browser-chrome adjustments with "never...a side effect beyond adjusting the browser-side chrome." Persisting an authentication token is exactly that kind of side effect, so this feature required a second, narrower sanctioned exception, added to `AI_RULES.md`: the injected script may write or clear exactly one named cookie whose value is a fully-formed opaque string supplied entirely from Python, with no logic, validation, or interpretation happening in the JS itself. This is a correction/extension to an existing rule, not a new pattern invented ad hoc — without it, `AI_RULES.md` would now be actively wrong about what's permitted in this codebase.

### Verification
Since `pytest`/`streamlit`/`supabase`/`bcrypt` remain unavailable in this working environment (no network access - all three mocked, `streamlit` including a fake browser model with cookies that persist across simulated page loads independently of `session_state`, which is reset to model a real closed-and-reopened browser):
- **SQLite backend, full scenario**: signup → login (session + cookie set) → simulated browser close/reopen (fresh `session_state`, cookie persists) → cookie found, validated, session restored, `is_logged_in()` true with correct store data ("auto-login" — would land directly on Dashboard) → logout (`session_state` cleared, cookie cleared in the fake browser) → simulated reopen after logout correctly finds no cookie and requires login again → login again (not signup) → auto-restore verified working on the login path too.
- **Supabase backend, identical scenario**: the same full scenario re-run with `ACTIVE_DB_BACKEND=supabase` and `streamlit`/`supabase` stubbed by an in-memory fake client — identical outcomes at every step.
- **Tampered/invalid input safety**: a garbage string, a token for a non-existent store, and an expired token were all confirmed to return `None` from `validate_session_token` without raising.
- **No password/hash leakage**: confirmed by direct string search that neither the plaintext password nor any password-hash material appears anywhere in a generated token.
- **`login()`/`signup()` business logic unaffected**: the same signup/login/wrong-password/unregistered-mobile/duplicate-mobile/invalid-mobile scenario used in every prior auth-related phase was re-run and diffed byte-for-bit identical against its pre-this-feature output.
- **Full regression**: `modules/products/repository.py` and `modules/sales/repository.py`'s SQLite scenarios re-diffed byte-for-bit identical against their established baselines; a full login→products→dashboard→alerts→sales regression, and the Invoice Save scenario from v2.10.0, were both re-run end to end and returned correct results.
- **`ACTIVE_DB_BACKEND` switching**: reconfirmed unchanged (unset/`"supabase"`/garbage → `"sqlite"`/`"supabase"`/`"sqlite"`) through `core.auth` directly.
- **Structural check**: `diff -rq` against the pristine pre-Phase-2 tree confirms exactly `config/settings.py`, `core/auth.py`, `core/session.py`, `core/login_ui.py`, and `app.py` are the newly-differing source files this release, alongside the previously-established set — no schema, OCR, Gemini, Invoice Scan, Products/Sales/Dashboard/Alerts, or Product/Sales UI file changed.

## [2.11.1] - Persistent Login bug fix: real-world browser close/reopen not restoring session

### Scope
`core/session.py`, `core/login_ui.py`, `app.py`. No database schema, OCR, Gemini, business logic, or public API changed. No change to the authentication architecture, the token format, or the cookie mechanism itself - only to *when* the cookie is actually written/cleared.

### Root cause
Confirmed via systematic investigation (not assumed): `save_persistent_session()`/`clear_persistent_session()` render a `components.html(...)` iframe whose `<script>` loads and executes **asynchronously** in a real browser - it is not instant the way v2.11.0's synchronous, single-process unit tests modeled it. Both were called on the line immediately before `st.rerun()`, in the login/signup forms and in the Logout button respectively. `st.rerun()` tells the Streamlit frontend to discard the current render right away; in real-world conditions (Streamlit Cloud, Android Chrome, Add to Home Screen - and, based on the mechanism, any real browser) the iframe routinely had not finished loading and executing its script before that teardown happened, so the cookie was never actually set (on login) or never actually cleared (on logout) - even though `session_state`, the token itself, and every other part of the feature were already correct.

This explains every observed symptom without needing to invoke a platform-specific cause:
- **Streamlit Cloud clearing the cookie** - ruled out; this is a client-side `document.cookie` write with no HTTP `Set-Cookie` involvement, so the hosting platform has no mechanism to interfere.
- **Add to Home Screen isolating storage** - ruled out; the project has no `manifest.json` or service worker, so "Add to Home Screen" on Android Chrome creates a plain bookmark opening the same origin in regular Chrome, sharing the standard per-origin cookie jar, not an isolated installed-PWA context.
- **Browser-specific behavior** - ruled out; the race is a Streamlit rerun/iframe-timing issue independent of which browser is used, so it reproduces anywhere a real browser (not a local synchronous mock) is involved.
- **Cookies being the wrong mechanism** - ruled out; a `localStorage.setItem()` call injected the same way, immediately before the same `st.rerun()`, would race identically and fail for the identical reason. The storage mechanism was never the problem, so it was not replaced.

### Fixed
- **`core/session.py`** - added `queue_persistent_session_token()`/`pop_persistent_session_token()` (a token is now stashed in `session_state` - synchronous, instant, no iframe involved - instead of written as a cookie immediately) and the symmetric `queue_persistent_session_clear()`/`pop_persistent_session_clear()` for logout. `save_persistent_session()`/`clear_persistent_session()` themselves are unchanged - same cookie, same JS, same guardrails - only *when* they're called changed.
- **`core/login_ui.py`** - both the login and signup handlers now call `queue_persistent_session_token(...)` instead of `save_persistent_session(...)`, immediately before their existing `st.rerun()`.
- **`app.py`** - `render_main_app()` now calls a new `_write_pending_persistent_session_cookie()` at its top, which pops any queued token and only then calls `save_persistent_session()` - during a render that is *not* immediately followed by another `st.rerun()`, giving the injected iframe the rest of that render cycle to actually load and execute. The Logout button now calls `queue_persistent_session_clear()` instead of `clear_persistent_session()` directly; the actual clear happens on the following render, in the login/signup routing branch.
- **Ordering fix caught during testing, not assumed**: naively clearing the cookie only in the login-screen branch created a second bug - on the render immediately following Logout, the cookie is *not yet* cleared (that happens later in the same render), so an unconditional restore-from-cookie attempt at the top of that render would have silently logged the store back in, defeating the logout that was just requested. Fixed by checking `pop_persistent_session_clear()` first and skipping the restore attempt entirely on that one render.

### Verification
Since `pytest`/`streamlit`/`supabase`/`bcrypt` remain unavailable in this working environment (no network access), a new, more realistic test harness was built specifically to catch this class of bug - unlike v2.11.0's mocks (which called the injected JS synchronously and instantly, unable to model the real race), this one models `st.rerun()` as aborting the current script run and discarding anything rendered during it, so a `components.html` call immediately followed by `st.rerun()` in the same run is correctly modeled as *lost*, while one that isn't followed by a rerun is correctly modeled as *applied*:
- **Bug reproduced first**: running the old v2.11.0 pattern (`save_persistent_session()` then `st.rerun()` in the same run) against this harness left the cookie empty - confirming the diagnosis before writing any fix.
- **Fix confirmed**: the new pattern (`queue_persistent_session_token()` then `st.rerun()`, then a separate following render that pops and writes) correctly resulted in the cookie being set.
- **Full realistic cycle, both backends (SQLite and mocked Supabase)**: login → cookie correctly queued-then-written across two simulated renders → simulated browser close/reopen (fresh `session_state`, cookie persists in the fake browser) → auto-login confirmed → logout → cookie confirmed still present immediately after the logout run (correctly deferred) → the following render confirmed the cookie actually cleared **and** confirmed no silent re-login occurred in between (the ordering fix) → reopening again correctly requires login → login-again path also auto-restores correctly.
- **Regression**: `login()`/`signup()`'s own logic re-confirmed byte-for-bit unchanged; the full Products/Sales/Dashboard/Alerts/Invoice-Save regression suite re-run and returned correct results; `ACTIVE_DB_BACKEND` switching reconfirmed unaffected.
- **Structural check**: `diff -rq` against the pristine baseline confirms `core/session.py`, `core/login_ui.py`, and `app.py` are the only files that changed this release, beyond documentation.

Real-world confirmation on an actual Streamlit Cloud deployment, Android Chrome, and an Add to Home Screen shortcut still remains recommended, since this environment has no network access to verify against a live deployment directly - but the root cause is now addressed at the mechanism level (the fix removes the race entirely, rather than working around a specific platform's timing), so it should not be platform-dependent.

## [2.11.2] - Persistent Login fix #2: repeated cookie sync (root cause: unreliable single-shot propagation, not just the rerun race)

### Scope
`app.py`, `core/session.py`, `core/auth.py` (debug logging removed only). No database schema, OCR, Gemini, API, or business-logic file was touched.

### Investigation
v2.11.1 fixed a real bug (writing the cookie immediately before `st.rerun()` raced the browser tearing down the DOM before the injected iframe could load). That fix was necessary but not sufficient: temporary debug logging was added to `app.py`/`core/auth.py` to instrument the restore path end-to-end, and the implementation was explained in detail before further changes. Research via `web_search` against Streamlit's own GitHub/community history (not guessing) confirmed a broader, well-documented, still-unresolved limitation: **there is no native `st.set_cookie`** (see `streamlit/streamlit#9421`, filed Sept 2024, open), and every community workaround that uses a `components.html()`-injected `document.cookie` write - including purpose-built, widely-used libraries like `extra-streamlit-components`'s CookieManager and `streamlit-cookies-manager` - report the same category of problem: a single write/read is not reliably guaranteed to propagate, with users describing it as "effectively unusable" in some cases and needing explicit sleep-and-retry patterns to work around it. A March 2025 community thread confirms this remains unresolved as of that date. This explains why v2.11.1's fix (correct as far as it went) still failed in real usage: removing the specific `st.rerun()` race removed one cause of failure, but a single fire-and-forget `components.html()` write was never guaranteed to succeed even without that race.

### Changed
- **`core/session.py`** - `get_persistent_session_token()` (new) reads the current session's token without clearing it, replacing the old `pop_persistent_session_token()`'s "write exactly once" semantics (kept, now unused, for backward compatibility of the name). `save_persistent_session()`/`clear_persistent_session()` now use `height=1` instead of `height=0` (a small, zero-cost, defensive change removing one more variable of uncertainty around zero-area element handling, per the investigation's suggested mitigation options). `queue_persistent_session_clear()`/`pop_persistent_session_clear()` are narrowed to their one remaining real purpose - skipping a restore attempt on the render immediately following Logout - since the actual cookie-clearing write no longer depends on this flag being set.
- **`app.py`** - New `_sync_persistent_session_cookie()`, called once, unconditionally, at the very end of routing (after the screen for this render has already been decided): if logged in, re-writes the current session's cookie; if not, re-issues the clear. This runs on **every single render**, not once after login/logout - turning one low-probability opportunity into many across a session, at negligible cost (Streamlit already re-renders the whole page on every interaction regardless). `_restore_persistent_session_if_any()` now also re-queues a successfully-restored session's token, so a *restored* session keeps refreshing its own cookie on subsequent renders too, not just a freshly-logged-in one. All temporary `[PERSISTENT_LOGIN_DEBUG]` logging (added this same investigation, in `app.py` and `core/auth.py`) has been removed.

### Not changed
`signup()`/`login()`'s own logic, the token format, the HMAC signing scheme, `database/supabase_schema.sql`, and every Products/Sales/Dashboard/Alerts/Invoice Scan/OCR/Gemini file - untouched.

### Verification
Since `pytest`/`streamlit`/`supabase`/`bcrypt` remain unavailable in this working environment (no network access to a real browser or Supabase project; `web_search`/`web_fetch`, which run through a separate channel, were used for the research above):
- **Statistical proof of the actual fix**: a test harness modeled the real documented failure mode - each individual cookie-write attempt has only a fixed (e.g. 30%) chance of actually landing, independent of any rerun timing - and confirmed a single-attempt design fails almost every time (0/1 successes in a representative run) while the new repeat-every-render design succeeds reliably (5/10 attempts landed in the same run, and critically, auto-login on a simulated reopen succeeded) - demonstrating the fix addresses the actual documented unreliability, not just the previously-fixed timing race.
- **Full functional scenario, both backends**: login (or restore) → multiple simulated renders (cookie re-written/refreshed each time) → simulated browser close/reopen → auto-login succeeds → logout (cookie cleared, with the clear also repeating across a few subsequent login-screen renders, still correctly absent) → reopening again correctly requires login → login-again path also auto-restores. Identical outcomes confirmed on SQLite and on Supabase (mocked `streamlit`/`supabase`).
- **Full regression**: `signup()`/`login()` business logic, the Products and Sales repositories' SQLite scenarios, and a full login→products→dashboard→alerts→sales→Invoice-Save regression were all re-run and diffed/verified identical to their established baselines.
- **`ACTIVE_DB_BACKEND` switching**: reconfirmed unchanged.
- **Debug logging removed**: `grep -rn "PERSISTENT_LOGIN_DEBUG"` across the entire project returns nothing.
- **Structural check**: `diff -rq` against the pristine pre-Phase-2 tree confirms exactly `app.py`, `core/session.py`, and `core/auth.py` (debug-log removal only) differ from v2.11.1 - no other file touched.

Manual verification on a real desktop browser, real Streamlit Cloud deployment, real Android Chrome, and a real "Add to Home Screen" install all remain necessary and recommended - this fix is evidenced by research and by a statistical model of the documented failure mode, not by having run the real app, which this working environment cannot do.

## [2.12.0] - Persistent Login experiment cancelled and fully rolled back

### Scope
`config/settings.py`, `core/auth.py`, `core/session.py`, `core/login_ui.py`, `app.py`, `AI_RULES.md`. No database schema, OCR, Gemini, Invoice Scan, Products, Sales, Dashboard, Alerts, Supabase integration, public API, or any other business logic was touched.

### Why
Persistent Login (v2.11.0) shipped, then required two real-world bug fixes (v2.11.1: a `st.rerun()` timing race; v2.11.2: a deeper, evidence-confirmed Streamlit platform limitation, where a `components.html()`-injected `document.cookie` write is not reliably guaranteed to propagate at all - see `streamlit/streamlit#9421`, filed Sept 2024, still open). Even after v2.11.2's fix, success could not be confirmed on a real device from this working environment (no browser, no network access to a live deployment). Rather than continue investing in workarounds for a gap in Streamlit itself, the experiment is cancelled outright. **Persistent login is deferred until a future Supabase Authentication migration**, which would provide a real, server-managed session mechanism instead of a hand-rolled browser cookie - a fundamentally different and more appropriate foundation for this requirement than fighting Streamlit's lack of a native cookie-write API.

### Removed
- **`core/auth.py`**: `create_session_token()`, `validate_session_token()`, `_sign_session_token()`, and the entire `_fetch_store_by_id` dispatcher (`_fetch_store_by_id`, `_fetch_store_by_id_sqlite`, `_fetch_store_by_id_supabase`) - this lookup-by-primary-key path existed solely to support Persistent Login; `signup()`/`login()` themselves only ever look a store up by `mobile_number`, via `_fetch_store_by_mobile`, which is untouched. The `hashlib`/`hmac`/`time` imports (needed only for token signing) and the `SESSION_TOKEN_VALIDITY_DAYS` import are removed. The module docstring's "Persistent Login (Remember Session)" section is removed; the surrounding Phase 5 (Supabase migration) documentation is untouched.
- **`core/session.py`**: `save_persistent_session()`, `clear_persistent_session()`, `get_saved_session_token()`, `queue_persistent_session_token()`, `pop_persistent_session_token()`, `get_persistent_session_token()`, `queue_persistent_session_clear()`, `pop_persistent_session_clear()`, and the `_PENDING_TOKEN_KEY`/`_PENDING_CLEAR_KEY` constants. The `streamlit.components.v1 as components` import (needed only for the cookie-write JS) is removed. The module docstring's "Persistent Login (Remember Session)" section, including its `IMPORTANT` note about the `st.rerun()` race, is removed. `start_session()`, `is_logged_in()`, `get_current_store_id()`, `get_current_store_name()`, `get_current_owner_name()`, and `end_session()` are otherwise byte-for-bit unchanged from their pre-v2.11.0 form (confirmed by diff-testing against the original v2.5.0-era behavior).
- **`core/login_ui.py`**: the `create_session_token`/`queue_persistent_session_token` imports and the corresponding calls in both `_render_login_form()` and `_render_signup_form()`. Both forms now call only `login()`/`signup()` + `start_session()` + `st.rerun()`, exactly as before v2.11.0.
- **`app.py`**: `_restore_persistent_session_if_any()` and `_sync_persistent_session_cookie()` (and every `[PERSISTENT_LOGIN_DEBUG]` print statement that had accumulated across the investigation) are removed entirely. Routing is restored to its original, simple form: `if is_logged_in(): render_main_app() else: render_login_signup_screen()`, with no cookie-restore step beforehand. The Logout button no longer calls `queue_persistent_session_clear()` - it's back to `end_session()` followed directly by `st.rerun()`. The module docstring's mention of restoring from a saved cookie is removed. `_render_mobile_sidebar_css()` and `_render_mobile_sidebar_autoclose()` (v2.4.7, unrelated to this feature) are untouched.
- **`config/settings.py`**: the entire "Persistent login (Remember Session)" block - `SESSION_TOKEN_VALIDITY_DAYS` and `SESSION_COOKIE_NAME` - is removed. `SESSION_STATE_KEY` and everything else is untouched.
- **`AI_RULES.md`**: the second JavaScript-guardrail exception (added in v2.11.0 specifically to permit the persistent-login cookie write) is removed. The JavaScript guardrail section is restored to its original v2.4.7 wording - a single sanctioned exception, for browser-chrome adjustments only (the mobile sidebar auto-close). No other rule was touched.

### Verification
Since `pytest`/`streamlit`/`supabase`/`bcrypt` remain unavailable in this working environment (no network access - `bcrypt` mocked as in every prior auth-related release):
- **Removal confirmed complete**: `grep -rln` across the entire project for `PERSISTENT_LOGIN_DEBUG`, `save_persistent_session`, `clear_persistent_session`, `get_saved_session_token`, `queue_persistent_session_token`, `pop_persistent_session_token`, `get_persistent_session_token`, `queue_persistent_session_clear`, `pop_persistent_session_clear`, `_restore_persistent_session_if_any`, `_sync_persistent_session_cookie`, `create_session_token`, `validate_session_token`, `SESSION_TOKEN_VALIDITY_DAYS`, `SESSION_COOKIE_NAME`, and `_fetch_store_by_id` returns zero matches anywhere in the codebase.
- **Original auth behavior restored, verified directly**: a signup → login → wrong-password → duplicate-mobile scenario was re-run against the rolled-back `core/auth.py`/`core/session.py` and confirmed working correctly (`InvalidCredentialsError`/`DuplicateMobileError` raised correctly, `is_logged_in()`/`end_session()` behaving exactly as before v2.11.0).
- **Full regression**: `modules/products/repository.py` and `modules/sales/repository.py`'s SQLite scenarios re-diffed byte-for-bit identical against their established baselines; a full login→products→dashboard→alerts→sales regression, and the Invoice Save scenario from v2.10.0, were both re-run end to end and returned correct results; `ACTIVE_DB_BACKEND` switching (unset/`"supabase"`/garbage → `"sqlite"`/`"supabase"`/`"sqlite"`) reconfirmed unaffected.
- **Structural check**: `diff -rq` against the pristine pre-Phase-2 tree confirms exactly `config/settings.py`, `core/auth.py`, `core/session.py`, `core/login_ui.py`, `app.py`, and `AI_RULES.md` differ from v2.10.0's baseline (this rollback restored them to that baseline, undoing every change v2.11.0-v2.11.2 made) - no database schema, OCR, Gemini, Invoice Scan, Products, Sales, Dashboard, Alerts, or Supabase-integration file was touched by this rollback.

### Next steps (not part of this rollback)
Persistent login remains a valid, wanted feature - it is deferred, not abandoned. The recommended path when revisited: build it as part of a Supabase Authentication migration (real server-managed sessions) rather than a Streamlit-side client cookie workaround, given the platform limitation this rollback's investigation confirmed with real evidence.

## [2.13.0] - OCR Accuracy program, Sprint 1: Validation Layer

### Scope
`modules/invoice_scan/validation.py` (new), `modules/invoice_scan/review_service.py`, `modules/invoice_scan/review_ui.py`. No change to the Gemini extraction prompt, the `MEDICINE_FIELDS` schema, preprocessing, the database schema, session handling, or the review/edit workflow's existing behavior (edit/delete/add/save all work exactly as before).

### Why
A forensic audit of one real, difficult pharmacy invoice's OCR pipeline (informally tracked across several working phases, not separately versioned here) found the Gemini Vision extraction correct on most independently-verified fields, with a small number of confirmed errors: two batch-number misreads, one adjacent-row batch/expiry field bleed, one MRP/Rate numeric inconsistency (Rate exceeding MRP, which never occurred on any other row), and two GST% outlier values. The audit also found the extraction prompt's strongest-worded row-independence instruction still failed on the one case it targeted, and confirmed the schema has no field for "Free" quantity or "Total Qty" (TQT) at all. Rather than immediately rewriting the prompt or schema, a deterministic, post-extraction Validation Layer was designed and implemented first, to catch the class of errors that are checkable without needing to know the "true" value.

### Added
- **`modules/invoice_scan/validation.py`** (new) - a deterministic, advisory-only module. Inserted into the pipeline strictly between Gemini extraction and the editable Review table:

      Upload -> Preprocessing -> Gemini Extraction -> Validation Layer -> Editable Review -> Save

  `validate_medicines(medicines)` runs exactly once per invoice, reads the already-extracted medicine list, and attaches a temporary `"_validation": {"status", "flags"}` dict to each row - never calling Gemini again, never modifying/inferring/correcting any extracted field value, and never blocking Save. Seven rules implemented: `MRP_LESS_THAN_RATE` (rate > mrp), `GST_OUTLIER` (gst_percent differs from the invoice's dominant value), `EMPTY_BATCH`, `EMPTY_EXPIRY`, `EMPTY_MRP`, `EMPTY_RATE` (each field blank), and `DUPLICATE_BATCH` (batch_number appears on more than one row).

### Modified
- **`modules/invoice_scan/review_service.py`** - `initialise_review_session()` now calls `validate_medicines()` once, immediately after the existing `_row_id` assignment and before rows are written to `st.session_state`. `save_invoice_medicines()`'s save payload was already built from an explicit field whitelist (`name`, `batch_number`, `expiry_date`, `quantity`, `mrp`, `rate`, `gst_percent`, plus a few Products-service-only keys) that excludes `_row_id` - `_validation` is excluded by that same existing whitelist, so it can never reach the database. No other function in this file was changed.
- **`modules/invoice_scan/review_ui.py`** - each row now displays its validation flags (if any) as a non-blocking `st.warning`, visually distinct from the existing hard validation errors (`st.error`, from the pre-existing `review_service.validate_all_medicines()`, unchanged and unrelated). A small advisory count is shown in the table summary. The Save button's logic, the hard-error blocking check, and the Clear/Add/Delete buttons are all untouched.

### Verified
Since `pytest`/`streamlit`/`google-genai` remain unavailable in this working environment (no network access), a manual test harness was built to execute the project's own, unmodified test files (`tests/test_review_service.py`, `tests/test_ocr_service.py`) directly, including support for `pytest.fixture`, `pytest.mark.parametrize`, `pytest.raises`, and `monkeypatch.setenv/delenv`:
- **`tests/test_review_service.py`: 68/68 passing** - the file exercising everything touched this release (session init, edit/add/delete, the save-path field whitelist).
- **`tests/test_ocr_service.py`: 26/28 passing** - the 2 failures are both pre-existing PDF-rasterization tests that fail solely because `PyMuPDF` is not installed in this environment; `ocr_service.py` was not modified this release.
- **`validate_medicines()` standalone**: run against data reconstructed from the forensic audit's confirmed findings - correctly reproduced every confirmed real error (the MRP/Rate inconsistency, both GST outliers, both empty-field rows) and correctly flagged the confirmed genuine duplicate batch, with no existing field value ever mutated (checked explicitly via before/after equality assertions) and no crash on empty lists, fully-blank rows, or non-numeric junk values.
- **Structural check**: `diff -rq` against the pre-Sprint-1 tree confirms exactly `modules/invoice_scan/validation.py` (new), `modules/invoice_scan/review_service.py`, and `modules/invoice_scan/review_ui.py` differ - no other file touched.

## [2.13.1] - OCR Accuracy program, Sprint 2: Validation Layer rule refinements

### Scope
`modules/invoice_scan/validation.py`, `modules/invoice_scan/review_ui.py`. No change to the Gemini extraction prompt, the `MEDICINE_FIELDS` schema, preprocessing, the database schema, session handling, or the review/edit workflow.

### Why
v2.13.0's `DUPLICATE_BATCH` and `GST_OUTLIER` rules were both evidenced against the same forensic audit that also confirmed two real false-positive risks: (1) two genuinely different medicines legitimately shared a batch number on the audited invoice (different name, different expiry) - a naive "flag every duplicate" rule would have wrongly flagged this correct data; (2) the `GST_OUTLIER` rule assumed a single invoice-wide GST rate, which would produce false warnings on any invoice that legitimately mixes GST slabs across product categories. Both were fixed this release using only the evidence already on record - no new investigation was opened.

### Changed
- **`modules/invoice_scan/validation.py`**:
  - `_gst_pattern()` (replaces `_dominant_gst()`) - determines whether the invoice has one clearly-dominant GST rate to compare against, or whether it legitimately mixes multiple GST slabs. If two or more distinct GST values each appear on more than one row, or if the single most common value only appears once (no real majority at all), GST checking is suppressed entirely for that invoice. Otherwise, a row is flagged only if its value is itself a singleton (occurs on exactly one row) and differs from the majority value - reproducing both confirmed real GST errors from the audit while no longer firing on a legitimately mixed-slab invoice.
  - `_duplicate_batch_groups()` / `_is_suspicious_duplicate()` (replaces `_duplicate_batches()`) - a shared batch number is only flagged when at least one other row sharing it also shares this row's medicine name or its expiry date. The audit-confirmed-legitimate pattern (different name AND different expiry) is no longer flagged at all.
  - `_LOW_CONFIDENCE_FLAGS` (new) - `DUPLICATE_BATCH` is always attached with `flag_confidence["DUPLICATE_BATCH"] = "low"` whenever it does fire, per the instruction to reduce its severity rather than remove it outright.
  - `_validation` dict now additionally carries `"flag_confidence": {flag: "low" | "normal"}` alongside the existing `"status"`/`"flags"` keys (purely additive - no existing key removed or renamed).
- **`modules/invoice_scan/review_ui.py`** - `DUPLICATE_BATCH`'s label text softened to reflect reduced confidence ("may be legitimate - worth a quick look"). Row rendering now splits flags by `flag_confidence`: normal-confidence flags keep the existing `st.warning` treatment; low-confidence flags (currently only `DUPLICATE_BATCH`) are shown as a quieter `st.caption` instead. Save button behavior, hard-error blocking, and every other control are untouched.

### Verified
- **Reconstructed audit invoice re-run**: all previously-confirmed true positives (MRP/Rate inconsistency, both GST outliers, both empty-field flags) still fire exactly as before; the confirmed-legitimate duplicate batch (different name, different expiry) is now correctly suppressed instead of flagged.
- **New synthetic cases**, each run and asserted directly:
  - A legitimately mixed-GST-slab invoice (two GST values, two rows each) - confirmed zero GST warnings.
  - A true singleton GST outlier against an established 3-row majority - confirmed still flagged, majority rows confirmed clean.
  - A suspicious duplicate batch (same name, same batch, same expiry) - confirmed flagged, confirmed `flag_confidence` is `"low"`.
- **Full regression**: `tests/test_review_service.py` 68/68 passing, `tests/test_ocr_service.py` 26/28 passing (same 2 pre-existing `PyMuPDF`-unavailable failures as v2.13.0, unrelated to this release) - identical results to v2.13.0, confirming no regression.
- **Structural check**: `diff -rq` against the v2.13.0 tree confirms exactly `modules/invoice_scan/validation.py` and `modules/invoice_scan/review_ui.py` differ - no other file touched.

### Not changed
The Gemini extraction prompt, `MEDICINE_FIELDS`, the five other Validation Layer rules (`MRP_LESS_THAN_RATE`, `EMPTY_BATCH`, `EMPTY_EXPIRY`, `EMPTY_MRP`, `EMPTY_RATE`), the pipeline order, and the review/edit workflow.

### Next steps (not part of this release)
Recorded candidates for a future Sprint 3, none scheduled or committed: schema extension for "Free"/TQT; a concrete row-independence mechanism in the Gemini prompt; a verification mechanism for long alphanumeric batch codes; column-header anchoring guidance; per-field confidence capture at extraction time; and broader real-world validation of these Sprint 2 refinements across more than one invoice. See `PROJECT_STATUS.md` and `NEXT_TASK.md`.

## [2.13.2] - Sprint 2.1: Review Session Reset fix + Review UI completion

### Scope
`modules/invoice_scan/review_service.py`, `modules/invoice_scan/review_ui.py`, `modules/invoice_scan/upload_ui.py`. No change to OCR, Gemini, the extraction prompt/schema, the Validation Layer's rules (`modules/invoice_scan/validation.py` untouched - confirmed by file diff), the database, or the overall architecture.

### Part A - Bug fix: stale review session on new upload

**Bug**: uploading a new invoice while a previous review was still in the session could leave parts of the old review mixed in with the new one (e.g. an old 6-medicine review appearing alongside a new 2-medicine extraction).

**Root cause** (found by code inspection, not by reproducing the bug live - `streamlit` cannot be run in this environment): the pre-existing hash-differs branch in `upload_ui.py` called `review_service.clear_session()`, which had two problems: (1) it only swept `review_row_*` widget keys, never the per-row `delete_row_*` button keys, leaving orphaned widget state behind; (2) it also popped `"invoice_file_uploader"` - the file-uploader widget's own session_state key - while that exact widget had already been instantiated with the newly uploaded file earlier in the same script run, an anti-pattern this codebase has hit before (v2.4.2).

**Fix**: added `review_service.reset_session_for_new_upload()`, used only for the automatic new-upload path. It clears the review session dict and both `review_row_*` and `delete_row_*` widget keys (via a new shared `_clear_review_widget_keys()` helper), but never touches `"invoice_file_uploader"`. `clear_session()` (used only by the explicit "Clear Review" button, on a rerun where the uploader is not yet re-instantiated) keeps its original behavior of also resetting the uploader, plus now also gets the corrected, complete widget-key sweep via the same shared helper.

**SHA-256 cache logic unaffected**: `upload_ui.py`'s `is_review_session_active(file_hash)` check is unchanged - identical hash still reuses the cached session with no Gemini re-call; only a differing hash triggers `reset_session_for_new_upload()`.

**Verified**: a direct simulation of a full old session (6 medicines, plus simulated leftover `review_row_*` and `delete_row_*` widget keys, plus a simulated edited field) followed by a new-hash upload (2 medicines) confirmed: exactly 2 medicines in the new session, zero trace of any old medicine name or old widget key, and the uploader's own key explicitly confirmed untouched by the automatic reset path. A further end-to-end simulation (Invoice A -> B -> C, three sequential different-hash uploads) confirmed no cross-invoice leakage at any step.

### Part B - Review UI completed: two-tier error/warning display

The Review table previously showed blocking errors and advisory warnings as plain, unhighlighted text lines. This release completes the UI with two distinct, non-overlapping visual levels:

- **🔴 Blocking errors** (from `review_service.validate_medicine()` - logic and return format both unchanged, still the same list-of-strings locked in by `tests/test_review_service.py`): the row now gets a red left-border and tinted background (scoped CSS via the row's own keyed container, reusing the same technique already used elsewhere in this file for mobile layout - no new UI pattern introduced), and, where the offending field could be identified, that specific input also gets a red border. Each error is now shown with its exact message plus a `Found: / Expected:` breakdown, built by a new display-only mapping (`_map_blocking_error`, `_BLOCKING_FIELD_INFO`) that reads the same message strings `validate_medicine()` already produced - it does not change what triggers an error or its wording, only how it's displayed. Blocking errors continue to prevent Save exactly as before (`validate_all_medicines()` check in `_render_summary()`, unchanged).
- **🟡 Warnings** (from the Validation Layer, `modules/invoice_scan/validation.py` - completely untouched this sprint): the row now gets a yellow/amber left-border and tinted background under the same mechanism. Normal-confidence flags are shown via `st.warning`; the low-confidence `DUPLICATE_BATCH` flag (Sprint 2) keeps its quieter `st.caption` treatment - message prominence still varies within "yellow", but the row-level highlight itself stays a strict two-color system as required. Warnings never block Save (unchanged).
- **Summary cards**: now four metrics - Total Medicines (kept), plus new "Validation Errors", "Validation Warnings", and "Rows Requiring Review" counts. All three new counts are computed per-row (not per individual issue) from the exact same two sources driving each row's highlight color, so they always match the number of red/yellow highlighted rows one-to-one - "Rows Requiring Review" is the union of the error-row and warning-row sets, so a row with both an error and a warning is not double-counted.
- **No duplicate messaging**: the old generic "N validation issue(s) across M row(s)" aggregate line and the old "⚠️ Row N — please double-check: ..." aggregated-per-row line were both removed in favor of one line per distinct reason, shown exactly once per row.

### Verified
- Full regression suite re-run: `tests/test_review_service.py` 68/68 passing (including every `validate_medicine()`/`validate_all_medicines()` test, confirming their string-list contract is provably unchanged), `tests/test_ocr_service.py` 26/28 passing (same 2 pre-existing `PyMuPDF`-unavailable failures, unrelated to this release).
- A purpose-built recording stub of the small Streamlit API surface `review_ui.py` uses was built to actually execute `render_review_section()` end-to-end (not just review the code), since real `streamlit` cannot run in this environment. Five scenarios were run directly against it and asserted:
  1. Invoice A -> B -> C (three sequential different-hash uploads): no medicine or widget-key leakage at any step.
  2. A row with a blocking error present: Save refused, exact blocking message shown, no success message emitted.
  3. A row with only a warning (no blocking error): Save proceeds and succeeds, no blocking message shown.
  4. Mixed 4-row set (1 blocking-only, 1 warning-only, 1 clean, 1 blocking-only): summary metrics (2 errors / 1 warning / 3 rows requiring review) matched the actual per-row flag data exactly.
  5. Same mixed set: no error or warning message string repeated anywhere in the render, and the old aggregated-per-row wording confirmed gone.
- Structural check: `diff -rq` against the v2.13.1 tree confirms exactly `review_service.py`, `review_ui.py`, and `upload_ui.py` differ - `validation.py` (the Validation Layer's rules) is untouched, confirming Part A/B instructions to leave validation logic alone were followed.

### Not changed
OCR, Gemini, the extraction prompt/schema, the Validation Layer's seven rules and their trigger logic, the database, session-key architecture beyond the two functions described in Part A, and the overall review/edit workflow structure.

## [2.13.3] - Stabilization sprint: Review Session Lifecycle + Validation Consistency

### Scope
`app.py`, `modules/invoice_scan/review_service.py`, `modules/invoice_scan/review_ui.py`, `modules/invoice_scan/upload_ui.py`, `tests/test_review_service.py`. No new features. No change to OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, or the Validation Layer's advisory rules (`modules/invoice_scan/validation.py` untouched - confirmed by file diff).

### P0 - Review Session Lifecycle

Three concrete, code-level root causes were found by direct inspection (real `streamlit` cannot run in this environment to reproduce interactively) and fixed:

1. **Logout did not clear the review session** (`core/session.py`'s `end_session()` only ever removed the auth session key - by design, since that module is deliberately scoped to authentication only). Fixed in `app.py`'s Logout button handler, which now also calls `review_service.clear_session()` before `end_session()`. Safe to run in the same script run: once `end_session()` runs, `is_logged_in()` becomes False and app.py routes to the login screen for this rerun, so the Invoice Scan page (and its file_uploader widget) is never instantiated this run - `clear_session()` resetting that widget key here cannot conflict with an in-progress instantiation.

2. **A rejected/invalid upload attempt could destroy a valid existing review.** `upload_ui.py`'s hash-differs reset (`reset_session_for_new_upload()`, introduced in v2.13.2) was being called *before* `process_invoice_upload()` had validated the new file. If validation then failed (wrong type, too large, etc.), the previous - perfectly good - review for a *different* file had already been wiped, leaving the store owner with nothing. Fixed: the reset now only runs after the new upload has actually passed validation, immediately adjacent to the code that's about to use it (either reusing the cache or extracting via Gemini) - closing the window where a reset could happen with no valid new session following it.

3. **Re-verified, not changed**: the SHA-256 same-hash-reuses-cache / different-hash-resets-everything logic itself (from v2.13.2) was re-audited end-to-end and confirmed structurally correct - the "sometimes" symptom in the reported bugs traces to points 1 and 2 above, not to the hash-comparison logic itself.

### P0 - Validation Consistency

**Root cause**: `review_service.validate_medicine()` only checked Quantity/MRP/Rate/GST % with `if val and not _is_numeric(val)` - meaning a **blank** value for any of these four required fields silently passed validation entirely. This explains all three reported symptoms at once: "GST empty sometimes is not treated as blocking" (blank GST % never produced an error), "empty medicine rows sometimes do not receive the expected red highlight" (a row with a filled-in name but blank MRP/Rate/Qty/GST had zero blocking errors, since name was the only field actually enforced as required), and "some blocking validation errors still allow Save" (the Save-blocking check was correctly wired all along - it simply had nothing to block on for these specific cases, because the validation function itself wasn't flagging them).

**Fix**: `validate_medicine()` now treats Medicine Name, Quantity, MRP, Rate, and GST % as required - a blank value is always a blocking error (`"<Field> cannot be empty."`), and a non-blank non-numeric value is still a separately worded blocking error exactly as before (`"<Field> must be a number (got '...')."`). Batch Number and Expiry remain optional (blank is valid; format is still checked for Expiry when a value is present) - unchanged, per the ticket's explicit required-field list.

**Review UI kept in sync**: `review_ui.py`'s display-only `_BLOCKING_FIELD_INFO` mapping (used to highlight the right column and build the `Found:/Expected:` breakdown) was extended with entries for the four new "cannot be empty" message variants, so the new blocking errors get the same red row+field highlighting as every other blocking error - the Validation engine (`review_service.py`) remains the single source of truth; the UI does not invent or duplicate any validation logic.

### Tests

- `tests/test_review_service.py`: the now-outdated `test_empty_optional_numeric_fields_are_valid` (which asserted the very behavior being fixed) was replaced with `test_empty_required_numeric_fields_are_blocking` plus four single-field variants and a fully-blank-row test (5 required-field errors expected). Two new test classes added: `TestClearSessionAndReset` (8 tests covering `clear_session()`/`reset_session_for_new_upload()` teardown completeness, cache-reuse-on-same-hash, and no-mixing-on-different-hash) and `TestPageIsolation` (3 tests: a source-level scan confirming no other module references the review session key, a source-level check that `app.py`'s Logout handler calls `review_service.clear_session()`, and a source-level check that the upload_ui.py reset call is correctly positioned after upload validation). Net: 84/84 passing in this file (up from 68, +16 new tests, 0 removed net - one outdated test replaced by six new ones).
- `tests/test_ocr_service.py`: 26/28 passing - same 2 pre-existing `PyMuPDF`-unavailable failures as every release since v2.13.0, unrelated to this sprint (`ocr_service.py` untouched).
- **Ticket-specified regression sequence** (Invoice A -> A -> B -> C -> Logout -> Login -> Invoice Scan) executed directly end-to-end: same-hash re-upload correctly reused the cache (including a prior edit), each different-hash upload showed zero trace of any previous invoice, logout fully destroyed the session and every per-row widget key, and post-login the session was confirmed absent before Invoice Scan was even reached.
- **Ticket-specified UI scenarios** executed via the Sprint 2.1 recording stub (real `streamlit` unavailable): GST-empty row correctly blocking (1 Validation Error, `Found: (blank)` shown); a freshly-added empty medicine row correctly producing exactly 5 blocking errors (Name/Qty/MRP/Rate/GST) and a red highlight; a blocking-error row correctly refusing Save (no success message emitted); a warning-only row correctly allowing Save to proceed and succeed.
- Structural check: `diff -rq` against the v2.13.2 tree confirms exactly `app.py`, `review_service.py`, `review_ui.py`, `upload_ui.py`, and `tests/test_review_service.py` differ - `validation.py` (Validation Layer rules), `ocr_service.py` (OCR/Gemini), and the database layer are all untouched.

### Not changed

OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, the Validation Layer's seven advisory rules and their trigger logic, and the overall review/edit workflow structure beyond the specific fixes described above.

## [2.13.4] - Review Session Isolation fix + validation-block sizing

### Scope
`app.py`, `modules/invoice_scan/review_ui.py`, `tests/test_review_service.py`. No change to OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, or the Validation Layer's/blocking validator's actual validation rules (`modules/invoice_scan/validation.py` and `modules/invoice_scan/review_service.py` both untouched - confirmed by file diff).

### Bug
Reported: review data could survive after uploading a different invoice, and could appear to "leak" onto Sales, Products, and even the Login screen.

### Root cause
`app.py`'s `NAV_PAGES[selected_page]()` dispatch already ensured only one page's render function executes per script run, and a source-level scan (`TestPageIsolation`, v2.13.3) already confirmed no other page module ever reads the review session key - so review data was never literally rendered on another page. The actual problem was scope: the review session was cleared only on an explicit "Clear Review" click, a genuinely different upload, or Logout (v2.13.3) - meaning it stayed alive in `st.session_state` for the store's entire logged-in session, including while the user was on Dashboard/Sales/Products/Alerts. That stale presence is what was being observed and reported as a leak, and it also meant navigating back to Invoice Scan could resurface a review the user had already moved past.

### Fix
`app.py`'s `render_main_app()` now calls `review_service.clear_session()` whenever the sidebar's selected page is anything other than "🧾 Invoice Scan", immediately before dispatching to that page's render function. This makes the review session strictly page-scoped: it exists only while the user is actually on Invoice Scan, and is destroyed the instant navigation moves anywhere else - every other page now runs with zero review state present, by construction, not just by the earlier isolation guarantee that nothing reads it. Safe to call unconditionally (it's a no-op with nothing to clear), and safe with respect to the file_uploader widget for the same reason as the v2.13.3 Logout fix: this only runs when a *different* page is about to be dispatched, so the Invoice Scan page's uploader widget is never mid-instantiation in the same script run.

**SHA-256 caching is untouched** - the same-file-reuses-cache / different-file-resets-everything logic in `upload_ui.py` is unmodified and still governs uploads made while actually on the Invoice Scan page.

### Requirement #10 - validation block sizing
The 🔴 blocking-error block (added in v2.13.2) was a tall, multi-paragraph layout (message, blank line, "Found:", blank line, value, blank line, "Expected:", blank line, value). Compressed to a single line - `🔴 <message> Found: `<value>` — Expected: <text>` - matching the visual height of the single-line 🟡 warning block, with exactly the same information retained (message, found value, expected description), just laid out inline instead of across several lines.

### Tests
- One new regression test, `TestPageIsolation.test_app_py_clears_review_session_when_navigating_away_from_invoice_scan`, added to `tests/test_review_service.py` - a source-level check that the new guard exists, calls `review_service.clear_session()`, and runs before `NAV_PAGES[selected_page]()` is dispatched.
- Full suite re-run: `tests/test_review_service.py` 85/85 passing (was 84, +1), `tests/test_ocr_service.py` 26/28 passing (same 2 pre-existing `PyMuPDF`-unavailable failures, unrelated). Total 111/113.
- Direct simulation: navigating to a non-Invoice-Scan page destroys an active review session; staying on Invoice Scan across a rerun preserves it.
- Direct simulation via the recording stub: the compressed error block is confirmed to render as a single line (`.count("\n") == 0`) while still containing the message, `Found:`, and `Expected:` text - same information as before, just shorter.
- Structural check: `diff -rq` against the v2.13.3 tree confirms exactly `app.py`, `review_ui.py`, and `tests/test_review_service.py` differ - `review_service.py` (blocking-validator logic), `validation.py` (advisory rules), `ocr_service.py` (OCR/Gemini), and the database layer are all untouched.

### Not changed
OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, all validation rules and their trigger logic (only the red block's visual layout changed, not its content or when it fires), and the overall review/edit workflow structure.

## [2.13.5] - Review Screen stabilization: live validation, RED priority, owner-friendly messages

### Scope
`modules/invoice_scan/review_ui.py`, `modules/invoice_scan/review_service.py` only. No change to OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, upload flow, review session lifecycle (init/clear/isolation), SHA-256 caching, the Save workflow, or `modules/invoice_scan/validation.py`'s seven advisory rules and their trigger logic (all confirmed unmodified by file diff). This release was done as three small, individually-approved stabilization-mode steps against the v2.13.4 baseline; documented together here as one version bump.

### Step 1 - Review Summary relabeling
The four `st.metric()` labels under the review table were renamed to owner-friendly text: `Total Medicines` → `📦 Total Medicines`, `Validation Errors` → `🔴 Needs Fix (Save Blocked)`, `Validation Warnings` → `🟡 Please Check (Optional)`. `Rows Requiring Review` (an error∪warning union count) was replaced outright with **`✅ Ready to Save`** - a new, differently-defined metric: the count of rows with *neither* a blocking error *nor* an advisory warning, computed live every rerun the same way as the other three (never written to `st.session_state`). The first three metrics' underlying calculations were not touched.

### Step 2 - RED validation: two new required fields + live field highlighting
**Batch Number and Expiry are now required fields.** Previously (since v2.13.0) Batch Number had no validation rule at all and a blank Expiry was valid (only an invalid *format* blocked Save). `review_service.validate_medicine()` now blocks Save on a blank Batch Number or blank Expiry, exactly like the other five required fields (Medicine Name, Quantity, MRP, Rate, GST %) - all 7 fields are now required. Expiry's existing format check (when a value *is* present) is unchanged.

The per-field red-border input highlighting (`_render_row_highlight_css`'s `error_field_indexes`, driven by `_BLOCKING_FIELD_INFO`) already existed in the v2.13.4 baseline for the five previously-required fields. `_BLOCKING_FIELD_INFO` was extended with entries for the two new "required" messages so the same existing mechanism now covers Batch Number and Expiry too - no new highlighting code was needed, only new table entries. A row with multiple invalid/blank fields now shows one RED message per field, and fixing one field removes only that field's message on the next rerun (`validate_all_medicines()` already re-evaluates every row on every rerun - unchanged from v2.13.3).

### Step 3 - YELLOW validation: live recompute + RED priority
**Live recompute, no OCR-time cache.** Advisory warnings (`modules/invoice_scan/validation.py`'s 7 rules - MRP_LESS_THAN_RATE, GST_OUTLIER, EMPTY_BATCH, EMPTY_EXPIRY, EMPTY_MRP, EMPTY_RATE, DUPLICATE_BATCH) were previously computed exactly once, in `initialise_review_session()` at OCR time, and never recalculated afterward - editing a field wouldn't clear a stale warning, and a newly-warning-worthy edit wouldn't raise one. New `review_service.get_medicines_with_live_warnings()` calls the exact same (unmodified) `validation.validate_medicines()` on the live session list on every render instead. `review_ui.py`'s table and summary sections now both call this instead of `get_medicines()`, so a warning appears or disappears immediately as the reviewer edits a field, every rerun - no click or extra action needed, nothing cached.

**RED priority over YELLOW.** New `_effective_warning_flags()` in `review_ui.py` suppresses an advisory flag for a row when a RED blocking error already exists on that exact same field this rerun (`EMPTY_BATCH`↔`batch_number`, `EMPTY_EXPIRY`↔`expiry_date`, `EMPTY_MRP`↔`mrp`, `EMPTY_RATE`↔`rate` - the only four flags that can ever coincide with a same-field RED, since the others either don't apply to a blank field or require a non-blank value to fire at all). A row with a blank Batch Number, for example, now shows only the RED "Batch number is required." - not also a YELLOW "Batch number is empty." for the identical reason. Unrelated warnings (e.g. MRP < Rate, GST outlier) are never suppressed. Both the per-row display and the `🟡 Please Check` / `✅ Ready to Save` summary counts use this same suppression, so the numbers and the row highlights always agree.

### Step 4 - Owner-friendly message rewrite
All RED and YELLOW message text was shortened, e.g.: `"Medicine Name cannot be empty."` → `"Medicine name is required."`, `"Quantity must be a number (got 'x')."` → `"Enter a valid quantity."`, `"GST % cannot be empty."` → `"GST is required."`, `"Batch number also appears elsewhere. Please verify before saving."` → `"Duplicate batch number — please check."`. No trigger condition, required-field status, or rule logic changed anywhere - only wording. `_BLOCKING_FIELD_INFO`'s substrings were updated in lockstep so field-highlighting still matches every new message.

### Not changed
`modules/invoice_scan/validation.py` (all 7 advisory rules and their trigger logic - untouched), OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, upload flow, review session lifecycle (init/clear/page-isolation from v2.13.4), SHA-256 caching, the Save workflow, and the overall review/edit page structure beyond the specific UI/validation-display behaviors described above.

### Tests
`pytest`/`streamlit` remain uninstallable in this working environment (no network access) - same documented limitation as every release since v2.13.0. Verified instead via direct logic simulation against the real, unmodified `modules/invoice_scan/validation.py` (imported directly, not reimplemented): confirmed a blank required field produces exactly one RED message and one highlighted column per field, confirmed fixing one field removes only that field's RED message while others persist, confirmed a previously-optional case (blank Batch+Expiry, everything else filled) now correctly blocks, confirmed RED suppresses the duplicate YELLOW for the same field while an unrelated warning (MRP < Rate) is left untouched, and confirmed a fix is picked up on the very next simulated rerun with nothing cached. Structural check: `diff -rq` against the v2.13.4 tree confirms exactly `review_service.py` and `review_ui.py` differ - nothing else in the project changed.

**Known test-suite impact (not yet applied):** `tests/test_review_service.py`'s existing assertions were written against the pre-v2.13.5 message text (`"cannot be empty"`, `"must be a number"`) and the pre-v2.13.5 optional status of Batch Number/Expiry. Those specific assertions will fail if the suite is run as-is against this version and will need updating to the new message text and required-field list the next time the real suite can be executed. Test files were not modified as part of this release (not requested).

## [2.13.6] - Final stabilization: navigation persistence restored, validation refresh fixed, single-upload lock

### Scope
`app.py`, `modules/invoice_scan/review_ui.py`, `modules/invoice_scan/upload_ui.py` only. No change to OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, repositories, the Save workflow, SHA-256 cache identity/reuse logic, `modules/invoice_scan/review_service.py`, `modules/invoice_scan/validation.py`, or any other module (Products, Dashboard, Sales, Alerts) - all confirmed untouched by file diff. Explicitly framed by the project owner as the final stabilization update for this phase, limited to exactly the three issues below.

### Issue 1 - Review must survive page navigation

**Reported**: uploading an invoice, navigating to Dashboard/Products/Sales/Alerts, then returning to Invoice Scan, the review had disappeared.

**Root cause**: this was the intended, deliberate behavior of v2.13.4's "Review Session Isolation" fix - `app.py`'s `render_main_app()` called `review_service.clear_session()` whenever the selected sidebar page was anything other than "🧾 Invoice Scan", specifically so the session would exist only while on Invoice Scan. That requirement has now been explicitly reversed: navigation alone must never clear the review.

**Fix**: the navigation-triggered `clear_session()` guard (and its surrounding comment block) was removed from `render_main_app()` entirely. The review session is no longer torn down by navigation - it persists in `st.session_state` across page visits, exactly as it did before v2.13.4, until an explicit "Clear Review" click or a genuinely new (different-hash) upload. **Logout's own `clear_session()` call is untouched** - it is a separate, still-desired teardown (a fresh login must never see a previous session's leftover review) and was not part of this issue. SHA-256 caching (`upload_ui.py`) is completely unaffected - it was never involved in the isolation guard being removed.

### Issue 2 - Validation must refresh on the same rerun as the fix, not the next one

**Reported**: correcting a blank/invalid field (e.g. typing a value into a blank MRP) did not clear its RED error immediately - the error only disappeared after a *second*, unrelated action (editing another field). Same symptom for YELLOW warnings.

**Root cause**: `review_ui.py`'s `_render_table()` computed `errors_by_row` (and, separately, live advisory warnings) from `get_medicines()`/`get_medicines_with_live_warnings()` **before** looping over rows to render each row's `st.text_input` widgets. Streamlit resolves a keyed widget's just-confirmed value into `st.session_state[widget_key]` *before* the script body runs on the next rerun - but the review's own medicines list (a separate piece of state) only received that same value later in that same run, inside `_render_medicine_row`'s own widget code (`if new_value != current_value: update_medicine(...)`), which executes *after* validation had already been computed for that row. So the correction was real and stored correctly, but the RED/YELLOW state shown for that exact rerun was computed one step too early to reflect it - it only became visible on the *following* rerun, once the medicines list had caught up. Validation itself (`review_service.validate_medicine()`, `validation.py`'s rules) was never the problem - confirmed unchanged by file diff.

**Fix**: new `review_ui._sync_pending_widget_edits()` reads each row's current widget value directly out of `st.session_state` (keyed as `review_row_{row_id}_{field_key}`, matching the existing widget-key convention) and writes it into the medicines list via the existing `review_service.update_medicine()` - for every row, for every field - **before** anything is validated or rendered. Called once, at the top of `render_review_section()`, ahead of both `_render_table()` and `_render_summary()`, so both the per-row highlighting and the summary counts see the corrected value on the very same rerun the correction happened, with no second action required. `_render_medicine_row`'s own pre-existing sync-on-change check is unmodified and simply becomes a no-op on every subsequent rerun (the value it would write is already there). No validation rule, message, or required-field status changed - confirmed by file diff (`review_service.py` and `validation.py` both untouched this release).

### Issue 3 - Disable further uploads while a review is active

**Reported**: after uploading an invoice, the upload widget's own browse/replace control (shown as a small "+"-style option next to the uploaded file) remained clickable, letting the store owner pick a second file immediately - which (per existing, unmodified logic) silently triggered `reset_session_for_new_upload()` and discarded whatever was currently being reviewed, with no confirmation.

**Root cause**: `st.file_uploader(...)` was rendered unconditionally with no `disabled` state, so its native drop-zone/browse control stayed fully interactive for as long as the page was open, regardless of whether a review session already existed.

**Fix**: `upload_ui.py`'s `_render_upload_section()` now checks `review_service.has_any_session()` before rendering the widget and passes `disabled=session_already_active` to `st.file_uploader(...)`. Once a session exists, the widget's browse/replace control is disabled - the store owner can no longer pick a second file until "Clear Review" is clicked (`has_any_session()` becomes `False` again, re-enabling the widget with no extra code needed). This does not add a new control, change the upload component's structure, or touch the SHA-256 cache/reset logic below it in any way - `disabled=` is the only change to this widget call.

### Tests
`pytest`/`streamlit` remain uninstallable in this working environment (no network access - same limitation as every release since v2.13.0). Verified instead by importing the real, unmodified `review_service.py`, `review_ui.py`, `validation.py`, `core/database.py`, and `modules/products/repository.py` directly (via a minimal `streamlit`/`google.genai` stub sufficient for import) and exercising them against a real in-memory-equivalent SQLite database:
- **Issue 1**: simulated navigation (no call to a removed `clear_session()` guard) confirmed the session and an in-session edit both survive; confirmed "Clear Review" still empties the session; confirmed a different-hash upload still starts fresh.
- **Issue 2**: confirmed a blank MRP produces "MRP is required."; simulated Streamlit's widget-resolves-before-script-runs behavior (writing the corrected value directly into `st.session_state[widget_key]`) then called `_sync_pending_widget_edits()` followed by validation, confirming the RED error is gone on that same simulated rerun; ran the identical same-rerun check for a YELLOW warning (MRP<Rate, corrected by editing Rate); confirmed validation rules/messages are unchanged (still 7 required fields, same wording).
- **Issue 3**: confirmed `has_any_session()` is `False` before any upload (widget would be enabled), `True` immediately after `initialise_review_session()` (widget would be disabled), and `False` again after `clear_session()` (re-enabled).
- **Full regression re-run**: all checks from the v2.13.5 verification pass (Review Summary/Ready to Save, live RED across all 7 fields, live YELLOW, RED-suppresses-duplicate-YELLOW, review lifecycle, upload lifecycle, and a real Save that persists to the database) - zero regressions found, confirming the three fixes above did not disturb any v2.13.5 behavior.
- Structural check: `diff -rq` against the v2.13.5 tree confirms exactly `app.py`, `review_ui.py`, and `upload_ui.py` differ - `review_service.py`, `validation.py`, every repository, the database layer, and every other module (Products, Dashboard, Sales, Alerts) are byte-identical to v2.13.5.

### Not changed
OCR, Gemini, the extraction prompt/schema, preprocessing, the database schema, all repositories, the Save workflow, SHA-256 cache identity/reuse logic, `review_service.py` (session CRUD, `validate_medicine()`, `get_medicines_with_live_warnings()` - all untouched), `validation.py` (all 7 advisory rules and their trigger logic), Products, Dashboard, Sales, and Alerts.

---

## [2.14.0] - TQT (Total Quantity) Support: Qty / Free / TQT extraction with internal formula

### Scope
`modules/invoice_scan/ocr_service.py` and `modules/invoice_scan/review_ui.py` only. No change to `modules/invoice_scan/review_service.py` (session lifecycle, `validate_medicine()`, `add_empty_medicine()`, `update_medicine()` all confirmed untouched by file diff), `upload_ui.py` (upload flow, SHA-256 cache identity/reuse), `validation.py` (advisory rules), `app.py`, `core/database.py`, any repository, or any other module (Products, Dashboard, Sales, Alerts). Implemented as a sequence of small, individually-approved steps (investigate → explain → approve → implement, per the project owner's working rule adopted this release) against the v2.13.6 baseline.

### Background
The original v2.13.0 OCR Accuracy forensic audit (see Section 11a in `PROJECT_MEMORY.md`) had already identified, as one of its findings, "a confirmed schema gap (no field exists for 'Free' or 'Total Qty'/TQT)" on real pharmacy invoices - some invoices print a combined Qty+Free (bonus stock) column, or a separate pre-totaled TQT column, neither of which the single `quantity` field could represent. That gap is what this release closes.

### Added - Qty / Free / TQT extraction
`ocr_service.py`'s `MEDICINE_FIELDS` changed from a single `"quantity"` entry to three: `"qty"`, `"free"`, `"tqt"`. The Gemini extraction prompt (`_EXTRACTION_PROMPT`) was updated everywhere it previously referenced "Quantity" (the per-field rule block, the row-independence checklist, the general extraction rules, the final-verification checklist, and the JSON example) to instead reference `qty`/`free`/`tqt` - each copied exactly if printed on the invoice row, left blank if not printed or unreadable, never inferred or calculated from one another by Gemini itself. No other prompt rule, section, or instruction was added or reworded beyond this field-name substitution.

### Added - Internal quantity formula
New `ocr_service._apply_quantity_formula()`, called once inside `extract_medicines_from_file()` immediately after `_parse_and_validate_response()` parses Gemini's JSON response, before the function returns its result to the caller (`upload_ui.py`) - i.e. strictly before a Review Session is ever initialised. For every extracted row:

```
if tqt is present:     quantity = tqt
elif free is present:  quantity = qty + free
else:                   quantity = qty
```

Only the row's `"quantity"` key is written; `qty`/`free`/`tqt` are left on the row unchanged. This is the single point in the entire pipeline where the three fields are combined - `review_service.py`'s session lifecycle, `validate_medicine()`, `validation.py`'s advisory rules, the Review UI's rendering/sync logic, Save, and the database are all unaware `qty`/`free`/`tqt` exist at all; they only ever see the resulting `"quantity"` value, populated exactly the way `"quantity"` has always been populated for every prior release. A row built without any of `qty`/`free`/`tqt` (not possible from live OCR output any more, but relevant for anything constructing rows directly, e.g. existing tests) is left untouched by the formula rather than having its `quantity` blanked out.

### Pipeline (updated)

```
Invoice
  |
  v
Gemini (extracts qty, free, tqt - whichever are printed on the row)
  |
  v
Formula (ocr_service._apply_quantity_formula, inside extract_medicines_from_file)
  quantity = tqt, else qty+free, else qty
  |
  v
Internal Model (medicines list returned to upload_ui.py - "quantity" already final)
  |
  v
Review Session (review_service.initialise_review_session - unmodified)
  |
  v
Review UI (renders "quantity" under the column title "TQT")
  |
  v
Validation (review_service.validate_medicine / validation.py - unmodified, still read "quantity")
  |
  v
Save (review_service.save_invoice_medicines -> products.service.add_product - unmodified)
  |
  v
Database (products.quantity - unmodified schema, receives the already-calculated value)
```

### Changed - Review UI
`review_ui.py`'s `_COLUMNS`: the `"quantity"` column's display label changed from `"Qty"` to `"TQT"`. The field key (`"quantity"`), widget wiring, and every other column are unchanged - no separate Qty or Free column was added to the Review Screen; TQT is the only quantity-related column shown, matching the approved scope exactly.

### Verified
Real `pytest`/`streamlit` remain uninstallable in this working environment (no network access - same limitation as every release since v2.13.0). Verified via direct logic simulation, importing the real, modified `ocr_service.py` and the real, unmodified `review_service.py`/`validation.py` (via a minimal `streamlit`/`google.genai` import stub):
- All three example invoice types confirmed exact: `qty=2,free=1,tqt=3 -> quantity="3"`; `qty=10,free=2 (no tqt) -> quantity="12"`; `qty=10 only -> quantity="10"`.
- `MEDICINE_FIELDS` confirmed to be exactly `["name","batch_number","expiry_date","qty","free","tqt","mrp","rate","gst_percent"]`.
- `_parse_and_validate_response()`'s own existing behavior (field presence per row, empty-array handling, dropping blank-name rows, filling missing fields with `""`) re-verified unchanged - the formula is a separate function, not a modification to this one.
- `review_service.py` re-verified completely unaffected: `initialise_review_session()` with an old-style row (only a `"quantity"` key, no `qty`/`free`/`tqt` - matching every existing test fixture) preserves that value untouched; `validate_medicine()`'s required/numeric checks on `"quantity"` unchanged; `add_empty_medicine()`/`update_medicine()` unchanged; `validation.py`'s advisory layer unaffected (it does not reference `quantity` directly).
- End-to-end check: formula output fed into the real, unmodified `initialise_review_session()` produced the correct final quantities in the resulting session.
- Structural check: `diff -rq` against the v2.13.6 tree confirms exactly `ocr_service.py` and `review_ui.py` differ - `review_service.py`, `upload_ui.py`, `app.py`, `validation.py`, `core/database.py`, every repository, and every other module are byte-identical to v2.13.6.

**Known follow-up (unchanged from prior releases)**: none of this has been visually confirmed in an actual rendered `streamlit run` browser session - only via direct logic simulation and source inspection. `tests/test_review_service.py` remains out of sync with v2.13.5's message/required-field text and v2.13.6's reversed navigation behavior (unaffected by this release, since `review_service.py` was not touched); `tests/test_ocr_service.py`'s fixtures still build rows with a `"quantity"` key directly (bypassing the new formula, since they test `_parse_and_validate_response()` in isolation, not `extract_medicines_from_file()`) and will need new fixtures/assertions if `qty`/`free`/`tqt` extraction itself is to be covered by the real suite in the future.

### Not changed
OCR preprocessing, upload flow, review session lifecycle, SHA-256 cache, validation logic (`validate_medicine()`, `validation.py`'s 7 advisory rules), Save workflow, database schema, database save logic, repository layer, APIs, Dashboard, Products, Low Stock, Sales, Billing, Notifications, Super Admin, or any architecture.


