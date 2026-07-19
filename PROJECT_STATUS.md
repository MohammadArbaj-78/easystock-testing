# PROJECT_STATUS.md

## Current Version

2.4.2 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system).

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. Sales' search experience was reworked in v2.4.1 (live autocomplete, out-of-stock filtering, a Frequently Sold shortlist), then a real `StreamlitAPIException` crash in that new search flow was found and fixed in v2.4.2, with suggestion rows also made compact. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.4.2. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (autocomplete search with stock filter and Frequently Sold since v2.4.1; a `StreamlitAPIException` on selecting a suggestion fixed and suggestion rows made compact in v2.4.2; search, stepper, sell, and permanent append-only history complete since v2.4.0)

## Modules Under Development

None. Sales is complete; v2.4.1 and v2.4.2 improved its search UX without leaving it in a partial state.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new test file has been added to the project's own `pytest` suite for Sales - every Sales release has instead been verified by direct execution/simulation, since `pytest`/`streamlit` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Sales verification to date: Phase 1/2 (v2.3.0-v2.3.1, no Streamlit dependency) - 26 checks via real SQLite execution. Phase 3 (v2.4.0), the search rework (v2.4.1), and the crash fix + compact rows (v2.4.2) - all Streamlit UI - verified via a Streamlit-semantics-accurate simulation shim executing the real, unmodified source end-to-end. That shim was itself found to be missing a real Streamlit constraint (the one that caused v2.4.1's bug) and was corrected in v2.4.2 - then sanity-checked by replaying the *old, broken* code against the corrected shim and confirming it reproduces the exact real error, before confirming the fixed code passes cleanly. v2.4.2 also added a new direct check (no Streamlit involved) confirming Dashboard and Low Stock Alerts both automatically reflect a sale, with zero code changes to either module. 76 checks passed in v2.4.2 alone (0 failures); across all Sales work to date, well over 100 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite remains recommended before any of these are treated as fully verified against the project's own harness.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail, and the caveat above about test-suite verification.

## Last Stable Release

**Version**: 2.4.2

**Summary**: Fixed a real `StreamlitAPIException` crash when selecting a Sales search suggestion or Frequently Sold tile (root cause: a session-state write to the search box's own widget key from inside a plain `if button:` block, after that widget had already been instantiated in the same run; fixed with Streamlit's own `on_click` callback pattern). Also made suggestion/Frequently-Sold rows compact single-row entries instead of bordered cards, per request. `sell_product` and every other Sales service function are confirmed byte-unchanged; only `_select_product`'s wiring and `_render_suggestion_tile`'s rendering changed in `modules/sales/ui.py`. Dashboard, Alerts, Product Management, Invoice Scan, and the database schema were not touched.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. The only recorded candidates for future work are the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap; none of those has a committed version or timeline. A recurring, still-open recommendation across recent releases: run the project's actual `pytest`/`AppTest` suite (v2.2.2 through v2.4.2 were all verified by simulation or direct execution instead, for lack of network access to install `streamlit`/`pytest` in this working environment).

## Current Priority

- **High**: None documented - Sales is complete and its known crash is fixed; no other module has an open, in-progress task.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite against v2.2.2 through v2.4.2 to confirm them against the project's own test harness.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation (`store_id` scoping) enforced structurally in every repository query. v2.4.2 added a new permanent rule to `AI_RULES.md`: a button click that must set a session-state key belonging to an earlier-rendered widget must use `on_click`, never a plain `if button:` block.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing) are each centralized in one definition and reused throughout. Sales continues to reuse `products_repository` (via its own service) rather than duplicating product-table access, and reuses existing UI patterns rather than introducing a new visual language.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; v2.2.2/v2.2.4/v2.4.0/v2.4.1/v2.4.2 (Streamlit UI changes) verified by simulation, v2.3.0/v2.3.1 (no Streamlit dependency) verified by real SQLite execution - all pending a real `pytest` run (see Current Test Status). The simulation shim's own accuracy is now treated as something to verify, not assume, after v2.4.1's bug slipped past an incomplete version of it.
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been generated from and verified against the current codebase.
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules (including Sales, through its v2.4.2 fix) are functionally complete with no open bug. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
