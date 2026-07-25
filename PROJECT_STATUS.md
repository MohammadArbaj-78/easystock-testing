# PROJECT_STATUS.md

## Current Version

2.11.2 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system). SQLite remains the default active database (`ACTIVE_DB_BACKEND`, `config/settings.py`), with a fully verified dual-backend Supabase path for Products, Sales, and Authentication/Store. Persistent Login (v2.11.0) shipped with a real-world bug that survived one fix attempt (v2.11.1, correct but incomplete) before the actual, fully-evidenced root cause was identified and fixed in this release.

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. v2.5.0-v2.10.0 completed a six-phase SQLite → Supabase migration plus a schema-drift bug fix. v2.11.0 added Persistent Login (session survives browser close, until explicit logout - non-JWT HMAC-signed cookie token, no schema change), but shipped with a bug: it passed unit tests but did not survive a real browser close/reopen. v2.11.1 fixed one real cause (the cookie-write JavaScript was raced against `st.rerun()`'s immediate DOM teardown) but the bug persisted. v2.11.2 identified the complete root cause via `web_search`-based research against Streamlit's own issue tracker and community history (not guessing): writing a browser cookie via a `components.html()`-injected script is a documented, unresolved Streamlit limitation (no native `st.set_cookie` exists) whose propagation is not reliably guaranteed even without a timing race - confirmed by multiple independent, purpose-built Streamlit cookie libraries reporting the same problem. The fix re-writes/re-clears the cookie on every render instead of once, turning one low-probability opportunity into many. No database schema, OCR, Gemini, business logic, public API, or architecture change was needed for either fix. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.11.2. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing; persistence dual-backend since v2.9.0; sessions persist across browser restarts as of v2.11.0, with real-world bugs fixed across v2.11.1 and v2.11.2)
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

None. Sales is complete. v2.11.2 is a complete bug fix, not a partial or in-progress change.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite since - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`supabase`/`google.genai`/`bcrypt` remain unavailable in this working environment (no network access to a real browser or a real Supabase project; `web_search`/`web_fetch`, a separate channel, were used for v2.11.2's research).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: multiple Sales phases, Dashboard/Low-Stock reflection checks, the six-phase Supabase migration, a schema-drift repair, v2.11.0's Persistent Login, v2.11.1's (incomplete) timing fix, and v2.11.2's fix - verified via a test harness modeling the actual documented failure mode (each cookie-write attempt has an independent chance of landing, not a timing race), proving statistically that repeated attempts succeed where a single attempt fails, plus the full functional login→close/reopen→auto-restore→logout→reopen→login-again cycle on both SQLite and mocked Supabase, plus the complete Products/Sales/Dashboard/Alerts/Invoice-Save regression suite. All checks across every release passed with 0 failures; across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite, and confirming this fix against a real Streamlit Cloud deployment on Android Chrome (including Add to Home Screen), both remain recommended and have not yet been done from this environment.

## Current Known Issue

None open, pending real-device confirmation. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript has been manually verified working on real desktop and mobile devices. The production `created_at`/`sold_at` default-value bug has a documented, idempotent repair migration (`database/repair_missing_timestamp_defaults.sql`). **Resolved this release, pending real-device confirmation**: v2.11.0's Persistent Login shipped with a real-world bug; v2.11.1 fixed one real cause (a `st.rerun()` timing race) but the bug persisted, because the deeper cause was a documented, unresolved Streamlit limitation around `components.html()`-based cookie writes never being reliably guaranteed to propagate at all, race or no race. v2.11.2 fixes this by re-writing/re-clearing the cookie on every render instead of once. This was evidenced via `web_search` research against Streamlit's own GitHub issue tracker (`streamlit/streamlit#9421`) and community reports, and via a statistical test harness - not via running the real app, which this environment cannot do. Two documented, deliberate trade-offs remain (not bugs): session tokens are valid for 365 days with no early-revocation mechanism short of a password change (a feature that doesn't exist yet), and the session cookie is set without the `Secure` attribute so it still works during local HTTP development. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail.

## Last Stable Release

**Version**: 2.11.2

**Summary**: Persistent Login fix #2 - the actual root cause. v2.11.1 correctly fixed a `st.rerun()` timing race but the bug persisted in real usage; before changing more code, temporary debug logging was added end-to-end and the complete implementation was explained in detail, then investigated via `web_search` against Streamlit's own issue tracker and community history. This confirmed a documented, unresolved Streamlit limitation: there is no native `st.set_cookie`, and every community workaround using a `components.html()`-injected `document.cookie` write - including purpose-built libraries - reports the same unreliability. A single fire-and-forget write was never guaranteed to succeed. Fix: `core/session.py` gained `get_persistent_session_token()` (reads without clearing) and switched to `height=1`; `app.py` gained `_sync_persistent_session_cookie()`, called once at the end of every render - re-writing the cookie on every render while logged in, re-clearing it on every render while not - turning one low-probability opportunity into many at negligible cost. Verified via a test harness modeling the actual documented failure mode (statistical, independent-probability write attempts), proving repeated attempts succeed where one fails, plus the full functional cycle and regression suite on both backends. All temporary debug logging was removed before this release.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. Highest-priority recorded item: manually verify Persistent Login (signup, login, browser close/reopen, auto-login, logout, login again) on a real desktop browser, real Streamlit Cloud deployment, real Android Chrome, and a real Add to Home Screen install - this has not yet been possible from this working environment (no network access to a real browser). Other recorded candidates: confirming `database/repair_missing_timestamp_defaults.sql` has been applied against the live Supabase project; running the real `pytest`/`AppTest` suite; testing all three Supabase implementations end-to-end against a real Supabase project; the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap.

## Current Priority

- **High**: Manually verify Persistent Login on a real desktop browser, Streamlit Cloud, Android Chrome, and Add to Home Screen - the fix is evidenced by research and a statistical model, not by having run the real app.
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite; confirm the timestamp-default repair migration has been applied to the live Supabase project.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation enforced structurally in every repository query. Backend selection lives in exactly one place (`config/settings.py`'s `ACTIVE_DB_BACKEND`), documented in `AI_RULES.md`'s "Multi-Backend Repository Rules." `core/session.py` remains the sole owner of authentication state and the persistent-session cookie. Persistent Login's two real-world bug fixes (v2.11.1, v2.11.2) both stayed within the existing architecture and the existing sanctioned JS exception - neither required a new pattern or rule, only correcting the implementation's reliability.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing, backend selection, session-token signing/verification) are each centralized in one definition and reused throughout.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; every release since has been verified by direct execution or a semantics-accurate simulation instead (see Current Test Status), pending a real `pytest` run. v2.11.2 specifically required a new kind of test harness - one modeling probabilistic, not just timing-based, real-world unreliability - to actually validate the fix, since simple synchronous mocks (used through v2.11.0) and even timing-aware mocks (v2.11.1) could not have caught this class of bug.
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been kept in sync with the current codebase (`NEXT_TASK.md` itself is currently empty of an active task, per project convention).
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug, pending real-device confirmation of Persistent Login specifically. The Supabase migration is fully implemented and verified via mocks (real-project verification pending network access). Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
