# PROJECT_STATUS.md

## Current Version

2.12.0 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system). SQLite remains the default active database (`ACTIVE_DB_BACKEND`, `config/settings.py`), with a fully implemented dual-backend Supabase path for Products, Sales, and Authentication/Store. The Persistent Login experiment (v2.11.0-v2.11.2) was fully implemented, debugged twice, and then completely rolled back in v2.12.0 after hitting a genuine, evidence-confirmed Streamlit platform limitation that couldn't be verified resolved from this working environment. The login/signup/logout flow is back to exactly its pre-experiment behavior.

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. v2.5.0-v2.10.0 completed a six-phase SQLite → Supabase migration plus a schema-drift bug fix. v2.11.0-v2.11.2 implemented, then twice attempted to fix, a Persistent Login feature; v2.12.0 fully reverted it - every persistent-login function, setting, and its one `AI_RULES.md` guardrail addition were removed, and the login/signup/logout flow is confirmed byte-for-bit identical to its pre-v2.11.0 form. Persistent login is deferred (not abandoned) until a future Supabase Authentication migration, which would provide a real server-managed session instead of a client-side cookie workaround. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.12.0. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing; session lives in `session_state` only - no cross-session persistence, exactly as before the Persistent Login experiment)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction; extraction prompt strengthened in v2.4.6)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory - confirmed in v2.10.0 to already run through the dual-backend Products Repository)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (autocomplete search with stock filter and Frequently Sold since v2.4.1; search, stepper, sell, and permanent append-only history complete since v2.4.0)

Sidebar navigation (`app.py`, all modules) has mobile-only touch-target/font polish and an auto-close-on-navigate behavior as of v2.4.7, manually verified working on real desktop and mobile devices - unaffected by the Persistent Login rollback. Product Management, Dashboard, Alerts, Sales, and Login all continue to run on SQLite by default.

## Modules Under Development

None. Sales is complete. v2.12.0 is a complete, clean rollback - not a partial or in-progress change.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite since - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`supabase`/`google.genai`/`bcrypt` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: multiple Sales phases, Dashboard/Low-Stock reflection checks, the six-phase Supabase migration, a schema-drift repair, the Persistent Login experiment and its two fix attempts, and v2.12.0's rollback verification - a `grep` across the entire project confirms zero remaining references to any persistent-login function or constant; a signup/login/wrong-password/duplicate-mobile scenario was re-run against the rolled-back `core/auth.py`/`core/session.py` and confirmed working exactly as before v2.11.0; the complete Products/Sales/Dashboard/Alerts/Invoice-Save regression suite and `ACTIVE_DB_BACKEND` switching were both re-run and confirmed unaffected. All checks across every release passed with 0 failures; across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite remains recommended.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript has been manually verified working on real desktop and mobile devices. The production `created_at`/`sold_at` default-value bug has a documented, idempotent repair migration (`database/repair_missing_timestamp_defaults.sql`). Persistent Login is not an open issue - it was cancelled and fully removed in v2.12.0, deferred until a future Supabase Authentication migration. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9/11 for full detail.

## Last Stable Release

**Version**: 2.12.0

**Summary**: Persistent Login experiment cancelled and fully rolled back. After v2.11.0's feature shipped and required two real-world bug fixes (a `st.rerun()` timing race in v2.11.1, then a deeper Streamlit platform limitation around unreliable `components.html()`-injected cookie writes in v2.11.2 - confirmed via real research against `streamlit/streamlit#9421`), success still couldn't be verified on a real device from this working environment. Rather than continue investing in a workaround for a gap in Streamlit itself, the feature was cancelled outright. Removed: `core/auth.py`'s `create_session_token()`/`validate_session_token()`/`_sign_session_token()`/`_fetch_store_by_id` (dispatcher + both backends); `core/session.py`'s entire persistent-cookie API (`save_persistent_session()`, `clear_persistent_session()`, `get_saved_session_token()`, and the queue/pop helpers); `app.py`'s `_restore_persistent_session_if_any()`/`_sync_persistent_session_cookie()` and all debug logging; `core/login_ui.py`'s calls into any of the above; `config/settings.py`'s `SESSION_TOKEN_VALIDITY_DAYS`/`SESSION_COOKIE_NAME`; and `AI_RULES.md`'s persistent-login-specific JavaScript guardrail exception. The login/signup/logout flow is confirmed byte-for-bit identical to its pre-v2.11.0 form. No database schema, OCR, Gemini, Invoice Scan, Products, Sales, Dashboard, Alerts, or Supabase-integration file was touched. Persistent login is deferred until a future Supabase Authentication migration.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. Recorded candidates for future work: a future Supabase Authentication migration (which would also be the appropriate place to revisit persistent login, this time on a real server-managed session rather than a client-side cookie workaround); confirming `database/repair_missing_timestamp_defaults.sql` has been applied against the live Supabase project; running the real `pytest`/`AppTest` suite; testing all three Supabase implementations (Products, Sales, Authentication/Store) end-to-end against a real Supabase project; the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap. None of those has a committed version or timeline.

## Current Priority

- **High**: None currently blocking.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite; confirm the timestamp-default repair migration has been applied to the live Supabase project.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation enforced structurally in every repository query. Backend selection lives in exactly one place (`config/settings.py`'s `ACTIVE_DB_BACKEND`), documented in `AI_RULES.md`'s "Multi-Backend Repository Rules." `core/session.py` is back to its original, single responsibility - owning `session_state` only, no persistent-cookie concern. `AI_RULES.md`'s JavaScript guardrail is back to its original single sanctioned exception (the mobile sidebar auto-close) - the second exception, added solely for the now-removed persistent-login cookie write, was removed along with the feature.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing, backend selection) are each centralized in one definition and reused throughout. No dead code remains from the Persistent Login experiment - every function, constant, import, and comment introduced for it across v2.11.0-v2.11.2 was removed in v2.12.0, confirmed by a full-project `grep` sweep.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; every release since has been verified by direct execution or a semantics-accurate simulation instead (see Current Test Status), pending a real `pytest` run.
- **Documentation**: `CHANGELOG.md` records every module, fix, and rollback with version bumps and verification notes going back to v1.0.0 (the Persistent Login experiment's full history, including its rollback, is preserved there rather than erased); `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been kept in sync with the current (post-rollback) codebase (`NEXT_TASK.md` itself is currently empty of an active task, per project convention).
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug. The Supabase migration remains fully implemented and verified via mocks (real-project verification pending network access). Persistent Login is cleanly deferred, not left in a half-working state. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
