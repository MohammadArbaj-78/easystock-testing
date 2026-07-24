# PROJECT_STATUS.md

## Current Version

2.11.1 (per `VERSION` and the latest `CHANGELOG.md` entry).

## Project Stage

MVP. Multiple source files (`config/settings.py`, `config/product_schema.py`) explicitly label current rules and scope as "MVP" (e.g. India-only mobile validation, medical-store-only product fields, no formal migration system). SQLite remains the default active database (`ACTIVE_DB_BACKEND`, `config/settings.py`), with a fully verified dual-backend Supabase path for Products, Sales, and Authentication/Store. Persistent Login (v2.11.0) now actually works across a real browser close/reopen as of this release - v2.11.0 shipped with a real-world bug (see Current Known Issue history) that this release fixes.

## Overall Progress

Eight modules are implemented and working: Login, Dashboard, Product Management, Invoice Upload, OCR Extraction, Review & Edit, Expiry Alerts, Low Stock Alerts, and Sales. v2.5.0-v2.10.0 completed a six-phase SQLite → Supabase migration plus a schema-drift bug fix. v2.11.0 added Persistent Login (session survives browser close, until explicit logout - non-JWT HMAC-signed cookie token, no schema change). v2.11.1 fixed a real-world bug in that feature: it passed unit tests but silently failed to survive an actual browser close/reopen on Streamlit Cloud, Android Chrome, and Add to Home Screen, because the cookie-writing/clearing JavaScript was raced against `st.rerun()`'s immediate DOM teardown and routinely lost. The fix defers the actual cookie write/clear to a render that isn't immediately followed by a rerun - no schema, OCR, Gemini, business logic, public API, or architecture change was needed. The application enforces multi-tenant data isolation throughout, follows a consistent layered architecture (UI → Service → Repository → Core/Config), and has an unbroken versioned release history from v1.0.0 through v2.11.1. Three modules remain unbuilt placeholder packages.

## Stable Modules

- Login (store signup/login, bcrypt password hashing; persistence dual-backend since v2.9.0; sessions persist across browser restarts as of v2.11.0, with a real-world timing bug fixed in v2.11.1)
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

None. Sales is complete. v2.11.1 is a complete bug fix, not a partial or in-progress change.

## Placeholder Modules

- `modules/billing/` - empty package, not yet implemented
- `modules/notifications/` (incl. `notifications/channels/`) - empty package, not yet implemented
- `modules/super_admin/` - empty package, not yet implemented (`core/admin_auth.py` referenced but also not yet built)

## Current Test Status

- **Number of tests**: 121 (per the most recent reported count in `CHANGELOG.md`, v2.2.1), across 5 test files. No new file has been added to the project's own `pytest` suite since - every release since has instead been verified by direct execution/simulation, since `pytest`/`streamlit`/`supabase`/`google.genai`/`bcrypt` remain unavailable in this working environment (no network access).
- **Pass status**: 121/121 passing as of the v2.2.1 release. Since then: multiple Sales phases, Dashboard/Low-Stock reflection checks, the six-phase Supabase migration, a schema-drift repair, v2.11.0's Persistent Login, and v2.11.1's fix, which required a new, more realistic test harness (one that correctly models `st.rerun()` discarding anything rendered during that same run, unlike v2.11.0's synchronous single-process mocks). That harness first reproduced the reported bug against the old code, then confirmed the fix resolves it, on both SQLite and mocked Supabase, across the full login→close/reopen→auto-restore→logout→reopen→login-again cycle. The full Products/Sales/Dashboard/Alerts/Invoice-Save regression suite was re-run and returned correct results. All checks across every release passed with 0 failures; across all work since v2.2.1, well over 150 checks have passed with 0 unresolved failures. Running the real `pytest`/`AppTest` suite, and confirming this fix against a real Streamlit Cloud deployment on Android Chrome (including Add to Home Screen), both remain recommended.

## Current Known Issue

None open. The Sales `StreamlitAPIException` on selecting a search suggestion is resolved as of v2.4.2. The Review & Edit delete-row bug is resolved as of v2.2.2, and its mobile UI is resolved as of v2.2.4. The v2.4.7 sidebar auto-close JavaScript has been manually verified working on real desktop and mobile devices. The production `created_at`/`sold_at` default-value bug has a documented, idempotent repair migration (`database/repair_missing_timestamp_defaults.sql`). **Resolved this release**: v2.11.0's Persistent Login shipped with a real-world bug - it passed unit tests but never actually survived a real browser close/reopen (the cookie-writing JS lost a timing race against `st.rerun()`'s DOM teardown, on Streamlit Cloud, Android Chrome, and Add to Home Screen) - fixed in v2.11.1 by deferring the cookie write/clear to a render not immediately followed by a rerun; verified via a new test harness that actually models this class of race, which the previous synchronous mocks could not. Two documented, deliberate trade-offs remain (not bugs): session tokens are valid for 365 days with no early-revocation mechanism short of a password change (a feature that doesn't exist yet), and the session cookie is set without the `Secure` attribute so it still works during local HTTP development. See `CHANGELOG.md` and `PROJECT_MEMORY.md` Section 9 for full detail.

## Last Stable Release

**Version**: 2.11.1

**Summary**: Bug fix for Persistent Login (v2.11.0), which had passed unit tests but silently failed to survive a real browser close/reopen in production use (Streamlit Cloud, Android Chrome, Add to Home Screen). Root cause, confirmed by systematic investigation rather than assumed: the cookie-write/clear JavaScript was invoked immediately before `st.rerun()`, which discards the current render right away - in real browsers, the injected iframe's asynchronous script routinely never got a chance to execute before that teardown, so the cookie was never actually written or cleared. Platform-specific explanations (Streamlit Cloud interference, Add-to-Home-Screen storage isolation, browser-specific quirks, localStorage as a better mechanism) were each investigated and ruled out - this was a universal timing bug, not a platform or storage-mechanism issue. Fix: the actual cookie write/clear is now deferred to the next render, via new queue/pop helpers in `core/session.py`, wired through `app.py`. A second, related bug (a not-yet-cleared cookie silently re-authenticating the store right after Logout) was caught during testing and fixed in the same change. No database schema, OCR, Gemini, business logic, public API, or the authentication architecture itself changed.

## Next Planned Release

**Version**: Not formally committed.

**Main goals**: Not documented as a committed plan. Recorded candidates for future work: confirming this release's fix against a real Streamlit Cloud deployment on Android Chrome (including an actual Add to Home Screen shortcut); confirming `database/repair_missing_timestamp_defaults.sql` has been applied against the live Supabase project; running the real `pytest`/`AppTest` suite; testing all three Supabase implementations end-to-end against a real Supabase project from an environment with network access; the remaining placeholder modules (Billing, Notifications, Super Admin) and Super Admin authentication (`core/admin_auth.py`), per `PROJECT_MEMORY.md`'s Pending Roadmap. None of those has a committed version or timeline.

## Current Priority

- **High**: Confirm this release's Persistent Login fix on a real Streamlit Cloud deployment, Android Chrome, and an actual Add to Home Screen shortcut - the previous release's report of the original bug came from exactly this kind of real-world usage, which this environment cannot reproduce directly (no network access).
- **Medium**: Recommended follow-up (not formally prioritized) - run the real `pytest`/`AppTest` suite; confirm the timestamp-default repair migration has been applied to the live Supabase project.
- **Low**: None documented.

## Project Health

- **Architecture**: Consistently layered (UI/Service/Repository/Core/Config) across every implemented module, with data isolation enforced structurally in every repository query. Backend selection lives in exactly one place (`config/settings.py`'s `ACTIVE_DB_BACKEND`). `core/session.py` remains the sole owner of authentication state, including the persistent-session cookie - v2.11.1 refined (not expanded) that ownership with a queue/pop pattern that defers write timing without introducing any new mechanism. The JavaScript-usage guardrail (v2.4.7, extended v2.11.0) needed no further change this release - only the calling convention around the already-sanctioned cookie JS changed, not the JS itself.
- **Code Quality**: Shared concerns (product fields, alert colors, expiry parsing, backend selection, session-token signing/verification) are each centralized in one definition and reused throughout. v2.11.1's fix is a good example of the project's testing philosophy catching a real gap: the original mocks were too synchronous to model a real browser, so a more faithful harness was built specifically to reproduce and then verify the fix for this class of bug, rather than patching the symptom without understanding the mechanism.
- **Testing**: 121/121 tests passing as of the v2.2.1 release; every release since has been verified by direct execution or a semantics-accurate simulation instead (see Current Test Status), pending a real `pytest` run.
- **Documentation**: `CHANGELOG.md` records every module and fix with version bumps and verification notes going back to v1.0.0; `PROJECT_MEMORY.md`, `AI_RULES.md`, and `NEXT_TASK.md` have been kept in sync with the current codebase (`NEXT_TASK.md` itself is currently empty of an active task, per project convention).
- **Overall Stability**: Stable at the current MVP scope - all eight implemented modules are functionally complete with no open bug. The Supabase migration is fully implemented and verified via mocks (real-project verification pending network access); Persistent Login is now believed correct at the mechanism level, pending real-device confirmation. Three modules (Billing, Notifications, Super Admin) remain entirely unbuilt.

## Required Documents

- **PROJECT_MEMORY.md** - The permanent, detailed record of EasyStock's architecture, folder structure, coding/UI/business rules, completed features, fixed bugs, roadmap, and testing/development conventions.
- **AI_RULES.md** - The permanent set of engineering rules (architecture, layering, validation, testing, release conventions) that any AI working on this codebase must follow.
- **NEXT_TASK.md** - The single source of truth for whatever work is currently active (task, bug, hypothesis, investigation state); empty of content when no task is in progress.
- **CHANGELOG.md** - The chronological, versioned history of every module delivered and every bug fixed, with test-verification notes for each entry.
- **PROJECT_STATUS.md** - This one-page snapshot of EasyStock's current version, module status, test results, and overall health, meant to orient a new session in under a minute.
