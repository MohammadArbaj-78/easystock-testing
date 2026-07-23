-- EasyStock: Supabase (Postgres) schema
--
-- Mirrors core/database.py's SQLite schema exactly (table/column names,
-- nullability, defaults) so modules/products/repository.py,
-- modules/sales/repository.py, and core/auth.py's existing Supabase
-- implementations (written in v2.6.0-v2.9.0) work against this schema
-- with no code changes. This file does not exist anywhere in the
-- project yet - every phase from v2.6.0 onward noted it as a
-- prerequisite for real Supabase testing, never created it, since all
-- prior phases were Python-only. Run this once, manually, in the
-- Supabase SQL editor for the target project before setting
-- ACTIVE_DB_BACKEND=supabase against it.
--
-- NOT auto-applied by the application. There is no migration runner in
-- this codebase (see PROJECT_MEMORY.md - "no formal migration system"
-- is a documented MVP-stage limitation) and this phase does not add one.
--
-- IMPORTANT - "create table if not exists" caveat: if a table below
-- already existed in the target Supabase project before this script
-- runs (e.g. created by hand via the Table Editor, or from an earlier
-- draft of this schema), "if not exists" silently skips that table
-- entirely - including fixing any column default it's missing. The
-- application never sets created_at/updated_at/sold_at itself on
-- insert (by design - see core/auth.py, modules/products/repository.py,
-- modules/sales/repository.py, all of which rely entirely on each
-- table's own DEFAULT now()), so a pre-existing table missing that
-- default will fail every insert with a NOT NULL violation on that
-- column (Postgres error 23502) even though this script defines the
-- default correctly below. If that happens, run
-- database/repair_missing_timestamp_defaults.sql once against the
-- affected project - it only adds missing defaults and is always safe
-- to re-run.

-- =====================================================================
-- stores
-- =====================================================================
create table if not exists stores (
    store_id       bigint generated always as identity primary key,
    store_name     text not null,
    owner_name     text not null,
    mobile_number  text not null unique,
    password_hash  text not null,
    created_at     timestamptz not null default now()
);

-- =====================================================================
-- products
-- =====================================================================
create table if not exists products (
    product_id                bigint generated always as identity primary key,
    store_id                  bigint not null references stores (store_id),
    name                      text not null,
    batch_number              text not null,
    expiry_date               text not null,  -- stored as MM/YY text, exactly like SQLite (see core/database.py)
    quantity                  integer not null default 0,
    minimum_stock_threshold   integer,        -- NULL = use DEFAULT_LOW_STOCK_THRESHOLD (config/settings.py)
    mrp                       double precision not null,
    rate                      double precision,
    gst_percent               double precision,
    purchase_date             text,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

create index if not exists idx_products_store_id
    on products (store_id);
create index if not exists idx_products_store_expiry
    on products (store_id, expiry_date);

-- =====================================================================
-- sales_history (append-only - no update/delete policy needed by design;
-- see modules/sales/repository.py's module docstring)
-- =====================================================================
create table if not exists sales_history (
    sale_id        bigint generated always as identity primary key,
    store_id       bigint not null references stores (store_id),
    product_id     bigint not null,
    medicine_name  text not null,
    batch_number   text not null,
    sold_quantity  integer not null,
    sold_at        timestamptz not null default now()
);

create index if not exists idx_sales_history_store_id
    on sales_history (store_id);
create index if not exists idx_sales_history_store_sold_at
    on sales_history (store_id, sold_at);

-- =====================================================================
-- reduce_product_stock RPC function
--
-- modules/products/repository.py's _reduce_stock_supabase() calls this
-- by name (see that function's docstring, added v2.6.0). Required
-- because PostgREST's update() endpoint cannot express a value and a
-- guard condition that both depend on the row's current quantity in a
-- single call, the way SQLite's one guarded
-- "UPDATE ... SET quantity = quantity - ? WHERE quantity >= ?" does.
-- This function performs the same atomic guarded decrement server-side.
-- Returns the number of rows updated (0 or 1), which
-- _reduce_stock_supabase() checks exactly like SQLite's cursor.rowcount.
-- =====================================================================
create or replace function reduce_product_stock(
    p_store_id integer,
    p_product_id integer,
    p_quantity integer
) returns integer
language plpgsql
as $$
declare
    rows_updated integer;
begin
    update products
    set quantity = quantity - p_quantity,
        updated_at = now()
    where store_id = p_store_id
      and product_id = p_product_id
      and quantity >= p_quantity;

    get diagnostics rows_updated = row_count;
    return rows_updated;
end;
$$;
