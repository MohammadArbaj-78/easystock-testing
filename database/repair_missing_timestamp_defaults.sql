-- EasyStock: repair migration for missing timestamp column defaults
--
-- Root cause: database/supabase_schema.sql uses "create table if not
-- exists", so if any of the tables below already existed in this
-- Supabase project before that script was run (e.g. created earlier by
-- hand, via the Table Editor UI, or from an earlier draft of the
-- schema), the script silently skipped that table entirely - including
-- its column defaults. That is how a NOT NULL "created_at" column ended
-- up with no "DEFAULT now()": the application never sets
-- created_at/updated_at/sold_at itself on insert (by design, matching
-- SQLite's own reliance on its column defaults - see core/auth.py,
-- modules/products/repository.py, modules/sales/repository.py), so a
-- table missing its default fails every insert with:
--
--   null value in column "created_at" of relation "stores"
--   violates not-null constraint (23502)
--
-- This script only ever ADDS a default to a column that doesn't already
-- have the correct one; it does not drop, rename, or alter any existing
-- data, and it does not touch NOT NULL constraints (those are already
-- correct per the reported error - only the default was missing).
-- Re-running it is always safe: setting a default that's already
-- correct is a no-op.
--
-- Run once, manually, in the Supabase SQL editor for the affected
-- project. Covers every automatic timestamp column across all three
-- tables, not just the one that has surfaced in production so far, in
-- case others share the same root cause.

alter table stores
    alter column created_at set default now();

alter table products
    alter column created_at set default now();

alter table products
    alter column updated_at set default now();

alter table sales_history
    alter column sold_at set default now();
