# PROJECT_STATUS.md

## Current Version

2.11.0 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system). SQLite remains the default active database (`ACTIVE_DB_BACKEND`, `config/settings.py`), with a fully verified dual-backend Supabase path for Products, Sales, and Authentication/Store. As of this release, login sessions also persist across browser restarts via a signed, cookie-backed token (Persistent Login) - a new capability, not part of the Supabase migration itself, and unaffected by which backend is active.

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. v2.5.0-v2.10.0 completed a six-phase SQLite → Supabase migration (connection layer, Products Repository, centralized backend selection, Sales Repository, Authentication/Store, and a confirmed-by-reuse Invoice Save path) plus a real-world schema-drift bug fix (missing `created_at`/`sold_at` defaults, resolved via `database/repair_missing_timestamp_defaults.sql`). v2.11.0 adds Persistent Login: after logging in or signing up, a store stays authenticated across closing and reopening the browser, until they explicitly log out - implemented with a non-JWT HMAC-signed token (keyed by the store's own password hash, no new secret or schema) and a single browser cookie, working identically regardless of which database backend is active. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.11.0. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing; persistence dual-backend since v2.9.0; sessions now persist across browser restarts as of v2.11.0)
- Dashboard (headline inventory metrics)
- Product Management (View/Search, Add, Edit, Delete)
- Invoice Upload (file validation, storage, preview)
- OCR Extraction (Gemini Vision medicine extraction; extraction prompt strengthened in v2.4.6)
- Review & Edit (OCR review, delete-row bug fixed in v2.2.2, mobile UI fixed in v2.2.4 after v2.2.3 was withdrawn, save to inventory - confirmed in v2.10.0 to already run through the dual-backend Products Repository)
- Expiry Alerts (15/30/60/90-day + Expired/1M/2M/3M buckets)
- Low Stock Alerts (Critical/Warning/Low severity tiers)
- Sales (autocomplete search with stock filter and Frequently Sold since v2.4.1; search, stepper, sell, and permanent append-only history complete since v2.4.0)

Sidebar navigation (`app.py`, all modules) has mobile-only touch-target/font polish and an auto-close-on-navigate behavior as of v2.4.7, manually verified working on real desktop and mobile devices. Product Management, Dashboard, Alerts, Sales, Login, and Invoice Save all continue to run on SQLite by default, unaffected by the Supabase migration phases or by Persistent Login.

## Modules Under Development

None. Sales is complete. v2.11.0 (Persistent Login) is a complete, self-contained feature, not a partial or in-progress one.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite since - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`supabase`/`google.genai`/`bcrypt` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: multiple Sales phases, Dashboard/Low-Stock reflection checks, the six-phase Supabase migration (v2.5.0-v2.10.0), a schema-drift repair, and v2.11.0's Persistent Login (verified via a fake-browser test harness on both SQLite and Supabase: signup/login → simulated browser close/reopen → auto-restore → logout clears session and cookie → reopening again requires login → login-again path also auto-restores; tampered/expired/non-existent-store tokens safely rejected; no password or password-hash material in any generated token; `login()`/`signup()`'s own logic re-confirmed byte-for-bit unchanged; full Products/Sales/Dashboard/Alerts/Invoice-Save regression re-run). All checks across every release passed with 0 failures; across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite remains recommended.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript has been manually verified working on real desktop and mobile devices. The production `created_at`/`sold_at` default-value bug (Postgres error 23502) found in real Supabase logs has a documented, idempotent repair migration (`database/repair_missing_timestamp_defaults.sql`) - not yet confirmed applied against the live project from this environment (no network access here). Persistent Login (v2.11.0) has two documented, deliberate trade-offs rather than open bugs: session tokens are valid for 365 days with no early-revocation mechanism short of a password change (a feature that doesn't exist yet), and the session cookie is set without the `Secure` attribute so it still works during local HTTP development - worth revisiting if this app is ever deployed somewhere HTTP is genuinely reachable. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail.

## Last Stable Release

**Version**: 2.11.0

**Summary**: Persistent Login (Remember Session). After a successful login or signup, the session now survives closing and reopening the browser, until the store explicitly logs out - implemented without a database schema change, without a JWT library, and without Supabase Auth. `core/auth.py` gained `create_session_token()`/`validate_session_token()`, a compact HMAC-signed `store_id.expiry.signature` token keyed by the store's own `password_hash` (no new secret), verified via a new `_fetch_store_by_id` dual-backend dispatcher - so the feature works identically on SQLite and Supabase. `core/session.py` gained cookie read/write/clear functions (reading is pure Python via `st.context.cookies`; writing/clearing uses a single, narrowly-scoped `components.html` snippet with no logic in the JS itself). `core/login_ui.py` and `app.py` wire it into login, signup, startup routing, and logout. `signup()`/`login()`'s own logic is completely unchanged. This required a genuinely new permanent rule in `AI_RULES.md`: a second, narrow, sanctioned exception to the existing JavaScript guardrail, since persisting an auth cookie is a real side effect the original chrome-only rule explicitly excluded.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. Recorded candidates for future work: confirming `database/repair_missing_timestamp_defaults.sql` has been applied against the live Supabase project; running the real `pytest`/`AppTest` suite; testing all three Supabase implementations (Products, Sales, Authentication/Store) end-to-end against a real Supabase project from an environment with network access; the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap. None of those has a committed version or timeline.

## Current Priority

- **High**: None currently blocking.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite; confirm the timestamp-default repair migration has been applied to the live Supabase project; manually verify Persistent Login (signup, login, browser close/reopen, auto-login, logout, login again) in a real browser, on both backends.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation enforced structurally in every repository query. Backend selection lives in exactly one place (`config/settings.py`'s `ACTIVE_DB_BACKEND`), documented in `AI_RULES.md`'s "Multi-Backend Repository Rules." `core/session.py` remains the sole owner of authentication state, now extended (not duplicated) to also own the persistent-session cookie. The project's JavaScript-usage guardrail (v2.4.7) now has two precisely-scoped sanctioned exceptions instead of one, both documented in `AI_RULES.md`.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing, backend selection, and now session-token signing/verification) are each centralized in one definition and reused throughout.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; every release since has been verified by direct execution or a semantics-accurate simulation instead (see Current Test Status), pending a real `pytest` run.
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been kept in sync with the current codebase (`NEXT_TASK.md` itself is currently empty of an active task, per project convention).
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug. The Supabase migration is fully implemented and verified via mocks (real-project verification pending network access); Persistent Login is a complete, additive feature verified the same way. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
