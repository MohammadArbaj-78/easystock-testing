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
