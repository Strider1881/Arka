"""SQLite schema, connection helpers, and deterministic seed data for AcmeCorp Procure."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "portal.db"

# 8 vendors — Pied Piper is BLOCKED; Northwind has an alias used by INV-1007.
VENDORS: list[dict[str, object]] = [
    {"name": "Northwind Supplies", "status": "ACTIVE", "aliases": ["Northwind Supply Co"]},
    {"name": "Globex Industrial", "status": "ACTIVE", "aliases": []},
    {"name": "Initech Systems", "status": "ACTIVE", "aliases": []},
    {"name": "Hooli Logistics", "status": "ACTIVE", "aliases": []},
    {"name": "Soylent Foods", "status": "ACTIVE", "aliases": []},
    {"name": "Umbrella Corp", "status": "ACTIVE", "aliases": []},
    {"name": "Pied Piper Cloud", "status": "BLOCKED", "aliases": []},
    {"name": "Wayne Enterprises", "status": "ACTIVE", "aliases": []},
]

# 12 POs (PO-501…512) aligned with SPEC invoice outcomes.
PURCHASE_ORDERS: list[dict[str, object]] = [
    {
        "po_number": "PO-501",
        "vendor": "Northwind Supplies",
        "amount": 1240.00,
        "description": "Office supplies Q1",
    },
    {
        "po_number": "PO-502",
        "vendor": "Globex Industrial",
        "amount": 3980.00,
        "description": "Industrial parts lot A",
    },
    {
        "po_number": "PO-503",
        "vendor": "Initech Systems",
        "amount": 12400.00,
        "description": "Systems integration retainer",
    },
    {
        "po_number": "PO-504",
        "vendor": "Northwind Supplies",
        "amount": 500.00,
        "description": "Misc consumables (unused by demo invoices)",
    },
    {
        "po_number": "PO-505",
        "vendor": "Hooli Logistics",
        "amount": 2000.00,
        "description": "Freight services March",
    },
    {
        "po_number": "PO-506",
        "vendor": "Wayne Enterprises",
        "amount": 1500.00,
        "description": "Security assessment (no Soylent match)",
    },
    {
        "po_number": "PO-507",
        "vendor": "Northwind Supplies",
        "amount": 2300.00,
        "description": "Warehouse restock",
    },
    {
        "po_number": "PO-508",
        "vendor": "Umbrella Corp",
        "amount": 4999.00,
        "description": "Lab equipment under threshold",
    },
    {
        "po_number": "PO-509",
        "vendor": "Pied Piper Cloud",
        "amount": 1775.00,
        "description": "Cloud credits (blocked vendor)",
    },
    {
        "po_number": "PO-510",
        "vendor": "Globex Industrial",
        "amount": 640.00,
        "description": "Small parts reorder",
    },
    {
        "po_number": "PO-511",
        "vendor": "Hooli Logistics",
        "amount": 1500.00,
        "description": "Session-expiry fault scenario PO",
    },
    {
        "po_number": "PO-512",
        "vendor": "Initech Systems",
        "amount": 2980.00,
        "description": "UI-rename fault scenario PO",
    },
]


def db_path() -> Path:
    raw = os.environ.get("PORTAL_DB_PATH", str(DEFAULT_DB_PATH))
    return Path(raw)


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY,
            po_number TEXT NOT NULL UNIQUE,
            vendor_id INTEGER NOT NULL REFERENCES vendors(id),
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN'
        );

        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY,
            invoice_number TEXT NOT NULL,
            vendor_id INTEGER NOT NULL REFERENCES vendors(id),
            po_id INTEGER REFERENCES purchase_orders(id),
            amount REAL NOT NULL,
            invoice_date TEXT NOT NULL,
            attachment_name TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(vendor_id, invoice_number)
        );

        CREATE TABLE IF NOT EXISTS approval_queue (
            id INTEGER PRIMARY KEY,
            invoice_id INTEGER NOT NULL UNIQUE REFERENCES invoices(id),
            requested_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            decided_by TEXT,
            decided_at TEXT,
            notes TEXT
        );
        """
    )


def seed(conn: sqlite3.Connection, *, operator_password: str, manager_password: str) -> None:
    """Idempotent seed: wipe transactional tables and re-insert demo master data."""
    from company_world.portal.passwords import hash_password

    conn.executescript(
        """
        DELETE FROM approval_queue;
        DELETE FROM invoices;
        DELETE FROM purchase_orders;
        DELETE FROM vendors;
        DELETE FROM users;
        """
    )
    conn.execute(
        "INSERT INTO users (email, password, display_name, role) VALUES (?, ?, ?, ?)",
        (
            "operator@acmecorp.test",
            hash_password(operator_password),
            "Portal Operator",
            "operator",
        ),
    )
    conn.execute(
        "INSERT INTO users (email, password, display_name, role) VALUES (?, ?, ?, ?)",
        (
            "priya.nair@acmecorp.test",
            hash_password(manager_password),
            "Priya Nair",
            "manager",
        ),
    )

    vendor_ids: dict[str, int] = {}
    for v in VENDORS:
        cur = conn.execute(
            "INSERT INTO vendors (name, status, aliases_json) VALUES (?, ?, ?)",
            (v["name"], v["status"], json.dumps(v["aliases"])),
        )
        vendor_ids[str(v["name"])] = int(cur.lastrowid)

    for po in PURCHASE_ORDERS:
        conn.execute(
            """
            INSERT INTO purchase_orders (po_number, vendor_id, amount, description, status)
            VALUES (?, ?, ?, ?, 'OPEN')
            """,
            (
                po["po_number"],
                vendor_ids[str(po["vendor"])],
                po["amount"],
                po["description"],
            ),
        )


def reset_database(
    path: Path | None = None,
    *,
    operator_password: str | None = None,
    manager_password: str | None = None,
) -> Path:
    """Create schema and seed. Used by app startup and tests."""
    p = path or db_path()
    if p.exists():
        p.unlink()
    op_pw = operator_password or os.environ.get("PORTAL_OPERATOR_PASSWORD", "change-me")
    mg_pw = manager_password or os.environ.get("PORTAL_MANAGER_PASSWORD", "priya-approve")
    with get_conn(p) as conn:
        init_schema(conn)
        seed(conn, operator_password=op_pw, manager_password=mg_pw)
    return p
