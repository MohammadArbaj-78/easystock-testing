# PROJECT_STATUS.md

## Current Version

2.10.0 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system). SQLite remains the application's sole active database - the Products Repository, Sales Repository, `core/auth.py`'s store persistence, and (by reuse, confirmed this release) the Invoice Save flow all run through Supabase-capable code paths behind their existing function signatures, selected by the single, one-place `ACTIVE_DB_BACKEND` switch (`config/settings.py`) that fails safe to `"sqlite"`, so nothing about the running application has changed.

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. v2.5.0 began Phase 1 of a planned SQLite → Supabase migration (`core/supabase_client.py`, isolated). v2.6.0 completed Phase 2 (Products Repository dual-backend). v2.7.0 completed Phase 3 (centralized `ACTIVE_DB_BACKEND` switch). v2.8.0 completed Phase 4 (Sales Repository dual-backend). v2.9.0 completed Phase 5 (Authentication & Store backend dual-backend). v2.10.0 completed Phase 6: an investigation (not a code change) confirmed the Invoice Review "Save Inventory" write path already runs entirely through the Products Repository's existing dual-backend `add_product`/`create_product` path - no invoice-specific persistence code exists anywhere in `modules/invoice_scan/`, so there was nothing left to migrate. No source file changed this release; SQLite continues to be the only database actually in use. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.10.0. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing; persistence dual-backend as of v2.9.0, SQLite active by default)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction; extraction prompt strengthened in v2.4.6)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory - confirmed in v2.10.0 to already run through the dual-backend Products Repository)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (autocomplete search with stock filter and Frequently Sold since v2.4.1; search, stepper, sell, and permanent append-only history complete since v2.4.0)

Sidebar navigation (`app.py`, all modules) has mobile-only touch-target/font polish and an auto-close-on-navigate behavior as of v2.4.7, manually verified working on real desktop and mobile devices. Product Management, Dashboard, Alerts, Sales, Login, and Invoice Save all continue to run on SQLite exclusively via each dual-backend code path's default, unaffected by v2.6.0 through v2.10.0.

## Modules Under Development

None. Sales is complete. v2.5.0 through v2.10.0's Supabase work is infrastructure, not a module, and is not "in development" in the sense of an unfinished feature - each is a complete, self-contained phase deliverable that intentionally changes no observable application behavior yet (v2.10.0 changed nothing at all, by design - see Overall Progress).

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite since - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`supabase`/`google.genai`/`bcrypt` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: multiple Sales phases, Dashboard/Low-Stock reflection checks, v2.4.6's OCR prompt, v2.4.7's sidebar JS, v2.5.0's Supabase connection layer, v2.6.0's Products Repository dual-backend work, v2.7.0's backend-selection centralization, v2.8.0's Sales Repository dual-backend work, v2.9.0's Authentication/Store dual-backend work, and v2.10.0's Invoice Save verification (a 3-row save scenario - two valid medicines, one missing a required name - run through the real Review & Edit save function with `ACTIVE_DB_BACKEND` unset and again with it set to `"supabase"` and `streamlit`/`supabase`/`google.genai` mocked, producing identical `{"saved": 2, "skipped": [...]}` results and identical post-save product visibility on both; `ACTIVE_DB_BACKEND` switching reconfirmed; a full login→products→dashboard→alerts→sales regression re-run). All checks across every release passed with 0 failures; across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite, and testing the Supabase implementations against an actual Supabase project, both remain recommended.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript has been manually verified working on real desktop and mobile devices. The Products Repository (v2.6.0/v2.7.0), Sales Repository (v2.8.0), and Authentication/Store (v2.9.0) Supabase paths - and, by reuse, the Invoice Save flow (v2.10.0) - are all complete but unverified against a real Supabase project: the Products Repository's `reduce_stock` depends on a Postgres RPC function that doesn't exist yet, and the Sales Repository and Authentication/Store paths depend on a `sales_history` table and a `stores` table (with a unique constraint on `mobile_number`) that don't exist yet in any Supabase project. None of this is a bug, since all paths are unreachable unless `ACTIVE_DB_BACKEND` is deliberately set to `"supabase"` (it defaults to, and fails safe to, `"sqlite"`), but all are known prerequisites for any future phase that switches it. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail, and the caveats above about test-suite verification.

## Last Stable Release

**Version**: 2.10.0

**Summary**: Phase 6 of a planned SQLite → Supabase migration - Invoice Save backend, investigation only, no source file modified. Traced the "Save Inventory" write path (`modules/invoice_scan/review_service.py`'s `save_invoice_medicines`) and found it calls `modules.products.service.add_product` for every reviewed row - the exact same function Product Management's "Add Product" form uses, already dual-backend since v2.6.0/v2.7.0. `grep` across every file in `modules/invoice_scan/` confirmed zero direct database access anywhere in the package (`ocr_service.py` and `review_ui.py`'s own docstrings already stated as much). This is the same reuse pattern that already meant Dashboard and Low Stock Alerts never needed their own migration. Verified end to end with both `ACTIVE_DB_BACKEND=sqlite` (default) and `=supabase` (mocked): identical save results and identical post-save product visibility on both backends. OCR extraction, the Gemini prompt, OCR parsing, the Review UI, the Products Repository, the Sales Repository, Dashboard, Alerts, Authentication, and both UIs were all confirmed untouched by design. No new architectural rule was needed, so `AI_RULES.md` was left untouched.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. The Supabase migration's next phase (not started) would need to: create the `stores` table (with a unique constraint on `mobile_number`), a `sales_history` table, and the `reduce_product_stock` Postgres RPC function in an actual Supabase project, verify all three Supabase implementations (Products, Sales, Authentication/Store - which together now cover every write path in the application, including Invoice Save) against that real project, decide a table-by-table migration or dual-write cutover strategy, and only then consider setting `ACTIVE_DB_BACKEND` to `"supabase"` outside of testing. Beyond that, the only other recorded candidates for future work are the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap; none of those has a committed version or timeline. A recurring, still-open recommendation: run the project's actual `pytest`/`AppTest` suite, and test all three Supabase implementations against a real Supabase project.

## Current Priority

- **High**: None currently blocking.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite; create the `stores` and `sales_history` tables and the `reduce_product_stock` RPC function, and test all three repositories' Supabase paths against a real Supabase project with real secrets configured.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation enforced structurally in every repository query - by `store_id` for Products/Sales, and by row identity/`mobile_number` for the `stores` table itself. Backend selection lives in exactly one place (`config/settings.py`'s `ACTIVE_DB_BACKEND`), a pattern documented as a permanent convention in `AI_RULES.md`'s "Multi-Backend Repository Rules." v2.10.0 confirmed this architecture's reuse principle extends correctly to Invoice Save with zero additional code, the same way Dashboard and Alerts already reused the Products Repository rather than owning their own SQL.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing, backend selection) are each centralized in one definition and reused throughout. The Products Repository, Sales Repository, and `core/auth.py` all share small helper functions between their SQLite and Supabase implementations rather than duplicating logic per backend.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; every release since has been verified by direct execution or a semantics-accurate simulation instead (see Current Test Status), pending a real `pytest` run.
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been kept in sync with the current codebase (`NEXT_TASK.md` itself is currently empty of an active task, per project convention).
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug, and all Supabase migration work so far (connection layer, Products Repository, centralized backend selection, Sales Repository, Authentication/Store, and the confirmed-by-reuse Invoice Save path) is inert/default-off infrastructure, not a live dependency. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
