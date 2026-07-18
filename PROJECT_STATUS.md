# PROJECT_STATUS.md

## Current Version

2.4.0 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system).

## Overall Progress

Eight modules are now implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and (as of v2.4.0) Sales. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.4.0. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (search, quantity stepper, sell, permanent append-only history - complete as of v2.4.0)

## Modules Under Development

None. Sales (the only module previously in progress) is now complete.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new test file has been added for Sales - its three phases were each verified by direct execution/simulation instead (see below).
- **Pass status**: 121/121 passing as of the v2.2.1 release. `pytest`/`streamlit` remain unavailable in this working environment (no network access), so the project's own suite could not be run this session. In its place: Sales' database/repository/service layers (v2.3.0-v2.3.1) were verified by executing the real code against a temporary SQLite database (12 + 14 = 26 checks, all passing); Sales' UI (v2.4.0) and the earlier Review & Edit UI work (v2.2.2/v2.2.4) were each verified with a Streamlit-semantics-accurate simulation executing the real, unmodified source end-to-end - Sales UI: 15 checks (empty-search guard, stepper clamping via native `disabled=` at both ends, a full sell reducing stock/resetting quantity/recording history, zero-stock correctly blocking a further sale), all passing. All prior suites were re-run after the UI work and still pass. Running the real `pytest`/`AppTest` suite is recommended before any of these are treated as fully verified against the project's own harness.

## Current Known Issue

None open. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail, and the caveat above about test-suite verification.

## Last Stable Release

**Version**: 2.4.0

**Summary**: Sales module complete - Phase 3 (UI layer) added `modules/sales/ui.py` (live search with empty-state guidance, per-result quantity stepper and Sell button, card-based Sales History) and one `app.py` `NAV_PAGES` entry. No custom CSS in the new file - reuses the products-list search/summary pattern and the review-table's divider convention rather than inventing a new visual language, and relies on native Streamlit components (`disabled=`, `st.container(border=True)`) instead of CSS wherever one already existed. `modules/sales/service.py` (Phase 2, v2.3.1) and `modules/sales/repository.py` + `products_repository.reduce_stock` (Phase 1, v2.3.0) are unchanged this release. `modules/dashboard/*`, `modules/alerts/*`, `modules/invoice_scan/*`, and `modules/products/ui.py` were not touched at any point across all three Sales phases.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. The only recorded candidates for future work are the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap; none of those has a committed version or timeline. A recurring, still-open recommendation across recent releases: run the project's actual `pytest`/`AppTest` suite (v2.2.2, v2.2.4, v2.3.0, v2.3.1, v2.4.0 were all verified by simulation or direct execution instead, for lack of network access to install `streamlit`/`pytest` in this working environment).

## Current Priority

- **High**: None documented - Sales (the prior High priority) is now complete, and no other module has an open, in-progress task.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite against v2.2.2/v2.2.4/v2.3.0/v2.3.1/v2.4.0 to confirm them against the project's own test harness.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation (`store_id` scoping) enforced structurally in every repository query. Sales' UI (v2.4.0) follows the same UI-layer contract as every other page: no SQL, no direct repository access, talks only to its own service module.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing) are each centralized in one definition and reused throughout. Sales reuses `products_repository` (via its own service) rather than duplicating product-table access, and reuses existing UI patterns (search/summary format, row dividers) rather than introducing a new visual language.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; v2.2.2/v2.2.4/v2.4.0 (Streamlit UI changes) verified by simulation, v2.3.0/v2.3.1 (no Streamlit dependency) verified by real SQLite execution - all pending a real `pytest` run (see Current Test Status).
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been generated from and verified against the current codebase.
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules (including the now-complete Sales) are functionally complete with no open bug. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
