"""
Database connection management and schema initialization.

This is the only file in the application that should contain raw SQL for
schema creation, or know the SQLite connection details. Every other
module reaches the database through repository functions, and every
repository goes through get_connection() defined here - never through a
connection it opens itself. This keeps connection handling (timeouts,
foreign key enforcement, row factory) consistent everywhere and makes a
future swap to a different database engine a change in one file.

Schema is created idempotently (CREATE TABLE IF NOT EXISTS) so calling
initialize_database() on every app startup is safe and requires no
separate migration step for the MVP stage. A proper migration system can
be introduced later if the schema needs to evolve after stores are
already using the app in production.
"""

import sqlite3
from contextlib import contextmanager

from config.settings import DATABASE_PATH, DATA_DIR
from core.exceptions import DatabaseError

import os


def _ensure_data_directory_exists() -> None:
    """Create the data directory if it doesn't exist yet.

    Needed before the first connection attempt, since SQLite will not
    create missing parent directories on its own.
    """
    os.makedirs(DATA_DIR, exist_ok=True)


@contextmanager
def get_connection():
    """Provide a SQLite connection as a context manager.

    Using a context manager here (rather than every caller opening and
    closing connections manually) guarantees connections are always
    closed, even if an exception is raised mid-query - preventing
    connection leaks, which is a real risk in a long-running Streamlit
    process that handles many requests over its lifetime.

    Foreign key enforcement is turned on per-connection because SQLite
    disables it by default; without this, a bug that inserts a product
    row with a non-existent store_id would fail silently instead of
    raising an error.

    Yields:
        sqlite3.Connection: An open connection with row_factory set to
            sqlite3.Row, so query results can be accessed by column name
            (row["mobile_number"]) instead of positional index - this
            makes calling code far more readable and resilient to column
            reordering.

    Raises:
        DatabaseError: If the connection cannot be opened.
    """
    _ensure_data_directory_exists()
    connection = None
    try:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except sqlite3.Error as error:
        if connection:
            connection.rollback()
        raise DatabaseError(f"Database operation failed: {error}") from error
    finally:
        if connection:
            connection.close()


def initialize_database() -> None:
    """Create all required tables if they do not already exist.

    Called once at application startup (from app.py). Each table beyond
    'stores' carries a store_id foreign key referencing stores(store_id)
    to enforce multi-tenant data isolation at the database level, not
    just in application code - so even a bug in a repository's WHERE
    clause cannot insert or attach a row to the wrong store.

    Raises:
        DatabaseError: If schema creation fails.
    """
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stores (
                store_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                mobile_number TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Supabase Auth migration: stores.mobile_number/password_hash
        # above are the old custom-authentication columns - left in
        # place unchanged (existing rows, existing NOT NULL/UNIQUE
        # constraints) rather than dropped or altered, since removing
        # or loosening either is not required to add Supabase Auth
        # alongside the existing business schema. The one new column
        # actually needed is this one: it links a store's row to the
        # Supabase Auth user who owns it, which is the only way
        # store_id-based scoping (every repository in the app depends
        # on get_current_store_id()) can keep working once Supabase, not
        # this table, is the source of truth for "who is this". Added
        # via ALTER TABLE (checked first via PRAGMA table_info, since
        # SQLite's CREATE TABLE IF NOT EXISTS is a no-op against a
        # stores table that already exists from before this column was
        # introduced) so existing databases upgrade in place without a
        # separate migration step - this runs every startup, is a no-op
        # once the column exists, and touches no other table.
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(stores)").fetchall()
        }
        if "supabase_user_id" not in existing_columns:
            # Requirement 3 fix: the PRAGMA check above and this ALTER
            # TABLE are a classic check-then-act race, not protected by
            # any lock - if initialize_database() is entered twice in
            # close succession (Streamlit is known to sometimes execute
            # a script's top level more than once during a cold start),
            # both calls can see the column missing before either one's
            # ALTER TABLE commits, and the second one then fails with
            # "duplicate column name: supabase_user_id". That failure
            # was surfacing as a real (if harmless and self-healing on
            # the very next rerun) red error box under Login/Signup.
            # Only that exact, narrow race is handled here - any other
            # sqlite3.OperationalError (a genuine schema/database
            # problem) is re-raised unchanged and must still surface
            # normally, exactly as before this fix.
            try:
                connection.execute("ALTER TABLE stores ADD COLUMN supabase_user_id TEXT")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_supabase_user_id
            ON stores (supabase_user_id)
            """
        )

        # Column names here mirror config/product_schema.py's field keys
        # exactly, so repository code can map between dict rows and
        # schema-defined fields without a translation layer. minimum_stock
        # threshold is nullable - a NULL means "use the global default"
        # (handled in modules/products/repository.py), since most stores
        # won't want to set a per-product threshold for every single item
        # on day one.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                batch_number TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                minimum_stock_threshold INTEGER,
                mrp REAL NOT NULL,
                rate REAL,
                gst_percent REAL,
                purchase_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_id) REFERENCES stores (store_id)
            )
            """
        )

        # Every Dashboard/Alerts query filters by store_id, and most also
        # filter or sort by expiry_date - indexing both means those
        # queries stay fast as a store's product catalog grows, rather
        # than degrading once a store has thousands of rows.
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_products_store_id
            ON products (store_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_products_store_expiry
            ON products (store_id, expiry_date)
            """
        )

        # sales_history is intentionally append-only: no repository
        # function exists to update or delete a row here, so a sale
        # once recorded stays a permanent, unmodified fact. Kept
        # deliberately minimal for the MVP - name and batch_number are
        # snapshotted (not looked up live from products) so a sale
        # record still reads correctly even if the product is later
        # renamed, re-batched, or deleted. No price_per_unit or
        # total_amount yet - billing/analytics can add those later
        # without needing to touch this table's core shape.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_history (
                sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                medicine_name TEXT NOT NULL,
                batch_number TEXT NOT NULL,
                sold_quantity INTEGER NOT NULL,
                sold_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_id) REFERENCES stores (store_id)
            )
            """
        )

        # store_id alone for ownership-scoped lookups (matches every
        # other table); store_id + sold_at composite for
        # get_sales_history's ORDER BY sold_at DESC LIMIT query, so
        # that read stays fast as a store's sales history grows.
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sales_history_store_id
            ON sales_history (store_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sales_history_store_sold_at
            ON sales_history (store_id, sold_at)
            """
        )

        # Agencies (distributors/wholesalers a store buys from), and
        # their ledger: one row per scanned bill (agency_bills) and one
        # row per payment made to that agency (agency_payments). The
        # running balance owed is NEVER stored as a column - it is
        # always computed at read time as total_billed - total_paid
        # (see modules.agencies.repository), so it can never drift out
        # of sync with the bills/payments actually recorded. Both
        # bills and payments are append-only, same as sales_history.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agencies (
                agency_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                agency_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_id) REFERENCES stores (store_id)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agencies_store_normalized_name
            ON agencies (store_id, normalized_name)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agency_bills (
                bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                agency_id INTEGER NOT NULL,
                invoice_date TEXT,
                grand_total REAL NOT NULL,
                image_path TEXT,
                image_content_type TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_id) REFERENCES stores (store_id),
                FOREIGN KEY (agency_id) REFERENCES agencies (agency_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agency_bills_agency_id
            ON agency_bills (agency_id)
            """
        )

        existing_bill_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agency_bills)").fetchall()
        }
        for column_name in ("image_path", "image_content_type"):
            if column_name not in existing_bill_columns:
                try:
                    connection.execute(f"ALTER TABLE agency_bills ADD COLUMN {column_name} TEXT")
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agency_payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                agency_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                paid_on TEXT NOT NULL DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (store_id) REFERENCES stores (store_id),
                FOREIGN KEY (agency_id) REFERENCES agencies (agency_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agency_payments_agency_id
            ON agency_payments (agency_id)
            """
        )
