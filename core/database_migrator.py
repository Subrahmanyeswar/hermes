# core/database_migrator.py
"""
Deterministic SQLite Schema Inspector, Safe Migrator & Readiness Verifier for HERMES 2.x.
Solves:
1. SQLite PRAGMA table_info inspection of actual on-disk databases.
2. Comparison against backend expected CREATE TABLE schemas.
3. Safe versioned column additions (ALTER TABLE ADD COLUMN) without dropping tables.
4. Preserving 100% of existing user/seed records during schema evolution.
5. Verification of asynchronous database initialization before server readiness.
6. Verification that tests configure test DB isolation before importing application servers.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

logger = logging.getLogger("hermes.database_migrator")


@dataclass
class ColumnInfo:
    cid: int
    name: str
    data_type: str
    not_null: bool
    default_value: Optional[str]
    primary_key: bool


@dataclass
class MigrationReport:
    success: bool
    db_path: str
    added_columns: List[str] = field(default_factory=list)
    migrated_values_count: int = 0
    preserved_rows_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.success and len(self.errors) == 0


class DatabaseMigrator:
    """Inspects and safely migrates existing SQLite schemas without dropping tables or losing data."""

    COMMON_COLUMN_SYNONYMS = {
        "products": {
            "classification": ["type", "trade_type", "product_type"],
            "type": ["classification", "trade_type", "product_type"],
            "availability": ["status", "stock_status", "in_stock"],
            "status": ["availability", "stock_status", "in_stock"],
            "origin": ["origin_country", "country_of_origin"],
            "origin_country": ["origin", "country_of_origin"],
            "image": ["image_url", "photo", "img"],
            "image_url": ["image", "photo", "img"],
            "price": ["indicative_price", "unit_price"],
            "indicative_price": ["price", "unit_price"],
            "moq": ["min_order_quantity", "min_order_qty", "minimum_order"],
            "min_order_quantity": ["moq", "min_order_qty", "minimum_order"],
            "min_order_qty": ["moq", "min_order_quantity", "minimum_order"],
        },
        "enquiries": {
            "destinationCountry": ["destinationOrOriginCountry", "country", "destination"],
            "country": ["destinationCountry", "destinationOrOriginCountry"],
            "destinationOrOriginCountry": ["destinationCountry", "country"],
            "tradeDirection": ["direction", "type"],
            "direction": ["tradeDirection", "type"],
            "companyName": ["company_name", "company"],
            "company": ["companyName", "company_name"],
            "contactPerson": ["contact_person", "contact", "name"],
            "contact": ["contactPerson", "contact_person", "name"],
        },
        "shipments": {
            "reference": ["tracking_ref", "trackingReference", "tracking_number"],
            "tracking_ref": ["reference", "trackingReference"],
            "estimatedDelivery": ["estimated_delivery", "eta", "delivery_date"],
            "eta": ["estimatedDelivery", "estimated_delivery"],
        },
    }

    @classmethod
    def inspect_sqlite_schema(cls, db_path: Path | str) -> Dict[str, Dict[str, ColumnInfo]]:
        """
        Inspect actual existing schemas using SQLite metadata via PRAGMA table_info.
        Returns: {table_name: {column_name: ColumnInfo}}
        """
        p = Path(db_path).resolve()
        if not p.exists() or p.stat().st_size == 0:
            return {}

        schema: Dict[str, Dict[str, ColumnInfo]] = {}
        try:
            conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [r[0] for r in cursor.fetchall()]

            for t in tables:
                cursor.execute(f"PRAGMA table_info({t});")
                cols = {}
                for row in cursor.fetchall():
                    # (cid, name, type, notnull, dflt_value, pk)
                    col_info = ColumnInfo(
                        cid=row[0],
                        name=row[1],
                        data_type=(row[2] or "TEXT").upper(),
                        not_null=bool(row[3]),
                        default_value=row[4],
                        primary_key=bool(row[5]),
                    )
                    cols[row[1]] = col_info
                schema[t] = cols

            conn.close()
        except Exception as e:
            logger.warning(f"DatabaseMigrator: notice during PRAGMA table_info inspection: {e}")

        return schema

    @classmethod
    def extract_expected_schema_from_code(cls, code: str) -> Dict[str, Dict[str, str]]:
        """
        Extract CREATE TABLE definitions and their column specifications from backend code.
        Returns: {table_name: {column_name: data_type}}
        """
        schema: Dict[str, Dict[str, str]] = {}
        # Match CREATE TABLE [IF NOT EXISTS] <table> (...)
        matches = re.finditer(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\)(?:\s*;|\s*`|\s*"\s*\)|\s*\'\s*\))',
            code,
            re.DOTALL | re.IGNORECASE
        )

        for m in matches:
            table_name = m.group(1).strip()
            body = m.group(2)
            cols: Dict[str, str] = {}

            # Parse lines/entries
            lines = [l.strip() for l in body.split(",") if l.strip()]
            for l in lines:
                l_upper = l.upper()
                if l_upper.startswith(("PRIMARY", "FOREIGN", "CHECK", "UNIQUE", "CONSTRAINT")):
                    continue
                tokens = l.split()
                if len(tokens) >= 1:
                    c_name = tokens[0].strip("`'\"")
                    c_type = tokens[1].upper() if len(tokens) > 1 else "TEXT"
                    if re.match(r'^[a-zA-Z0-9_]+$', c_name):
                        cols[c_name] = c_type

            if cols:
                schema[table_name] = cols

        return schema

    @classmethod
    def detect_schema_discrepancies(
        cls,
        actual_schema: Dict[str, Dict[str, ColumnInfo]],
        expected_schema: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """
        Compare the actual database schema with the expected application schema.
        Detects stale or incompatible database schemas.
        """
        discrepancies: List[Dict[str, Any]] = []

        for exp_table, exp_cols in expected_schema.items():
            if exp_table not in actual_schema:
                discrepancies.append({
                    "type": "MISSING_TABLE",
                    "table": exp_table,
                    "expected_columns": list(exp_cols.keys()),
                    "message": f"Expected SQLite table '{exp_table}' is missing from database file.",
                })
                continue

            actual_table_cols = actual_schema[exp_table]
            missing_cols = [c for c in exp_cols.keys() if c not in actual_table_cols]

            if missing_cols:
                # Check if old synonyms exist
                stale_synonyms: Dict[str, str] = {}
                synonyms_for_table = cls.COMMON_COLUMN_SYNONYMS.get(exp_table, {})
                for mc in missing_cols:
                    for syn in synonyms_for_table.get(mc, []):
                        if syn in actual_table_cols:
                            stale_synonyms[mc] = syn
                            break

                discrepancies.append({
                    "type": "STALE_SCHEMA_COLUMNS",
                    "table": exp_table,
                    "missing_columns": missing_cols,
                    "actual_columns": list(actual_table_cols.keys()),
                    "stale_synonyms": stale_synonyms,
                    "message": (
                        f"SQLite table '{exp_table}' schema is STALE: missing expected columns {missing_cols}. "
                        f"Existing columns on disk: {list(actual_table_cols.keys())}."
                    ),
                })

        return discrepancies

    @classmethod
    def apply_safe_schema_migration(
        cls,
        db_path: Path | str,
        expected_schema: Dict[str, Dict[str, str]],
        custom_mappings: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> MigrationReport:
        """
        Generate and apply explicit, safe, non-destructive schema migrations:
        1. Inspects existing schema.
        2. Applies ALTER TABLE ADD COLUMN for missing fields.
        3. Migrates existing values from synonym columns where applicable.
        4. Preserves 100% of existing rows without dropping tables.
        """
        p = Path(db_path).resolve()
        if not p.exists():
            return MigrationReport(success=False, db_path=str(p), errors=["Database file does not exist."])

        actual = cls.inspect_sqlite_schema(p)
        discrepancies = cls.detect_schema_discrepancies(actual, expected_schema)
        if not discrepancies:
            # Already clean and up to date
            return MigrationReport(success=True, db_path=str(p))

        report = MigrationReport(success=True, db_path=str(p))

        try:
            conn = sqlite3.connect(str(p))
            cursor = conn.cursor()

            # Record initial row counts across tables to verify data preservation
            row_counts_before: Dict[str, int] = {}
            for t in actual.keys():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {t};")
                    row_counts_before[t] = cursor.fetchone()[0]
                except Exception:
                    pass

            for disc in discrepancies:
                if disc["type"] == "STALE_SCHEMA_COLUMNS":
                    tbl = disc["table"]
                    missing = disc["missing_columns"]
                    synonyms = disc.get("stale_synonyms", {})
                    if custom_mappings and tbl in custom_mappings:
                        synonyms.update(custom_mappings[tbl])

                    for col in missing:
                        col_type = expected_schema[tbl].get(col, "TEXT")
                        # SQLite ADD COLUMN
                        try:
                            alter_sql = f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type};"
                            cursor.execute(alter_sql)
                            report.added_columns.append(f"{tbl}.{col}")
                            logger.info(f"DatabaseMigrator: safely added column '{col}' to table '{tbl}'")
                        except Exception as add_err:
                            report.errors.append(f"Failed to add column {tbl}.{col}: {add_err}")

                        # Copy values from synonym if old column existed
                        if col in synonyms:
                            old_col = synonyms[col]
                            try:
                                copy_sql = f"UPDATE {tbl} SET {col} = {old_col} WHERE ({col} IS NULL OR {col} = '') AND {old_col} IS NOT NULL;"
                                cursor.execute(copy_sql)
                                report.migrated_values_count += cursor.rowcount
                                logger.info(f"DatabaseMigrator: migrated {cursor.rowcount} row(s) from '{old_col}' to '{col}' in '{tbl}'")
                            except Exception as copy_err:
                                report.warnings.append(f"Could not copy from {old_col} to {col}: {copy_err}")

            conn.commit()

            # Verify row preservation
            for t, count_before in row_counts_before.items():
                cursor.execute(f"SELECT COUNT(*) FROM {t};")
                count_after = cursor.fetchone()[0]
                if count_after < count_before:
                    report.errors.append(f"Data loss detected in table '{t}': went from {count_before} to {count_after} rows!")
                else:
                    report.preserved_rows_count += count_after

            conn.close()
        except Exception as exc:
            report.success = False
            report.errors.append(f"Migration transaction failed: {exc}")

        return report

    @classmethod
    def verify_async_db_initialization(cls, backend_content: str) -> Tuple[bool, Optional[str]]:
        """
        Verify that the application does not report readiness or accept requests
        before required tables, migrations and seed data have completed.
        Returns: (is_safe, error_or_warning_message)
        """
        b_txt = backend_content

        # Check for synchronous app.listen outside db callback
        has_listen = "app.listen(" in b_txt or "server.listen(" in b_txt
        has_sqlite_init = ("db.serialize" in b_txt or "CREATE TABLE" in b_txt or "initDb" in b_txt or "init_db" in b_txt)

        if has_listen and has_sqlite_init:
            # Top-level callback readiness race check
            if "new sqlite3.Database" in b_txt and "initDb" in b_txt:
                if not re.search(r"initDb\([^)]*\)\s*\{[^}]*(?:app|server)\.listen", b_txt) and "await initDb" not in b_txt and "initDb().then" not in b_txt:
                    return False, (
                        "ASYNC_DB_READINESS_RACE: 'app.listen()' is invoked synchronously before asynchronous sqlite3 database initialization (initDb) finishes. "
                        "Incoming requests and tests will encounter uninitialized or unseeded tables."
                    )

            # Check if listen is called inside completion callback or after await
            listen_pos = b_txt.find("app.listen(")
            if listen_pos == -1:
                listen_pos = b_txt.find("server.listen(")

            # If there's an async initDb() function, check if listen awaits it
            if "async function initDb" in b_txt or "const initDb = async" in b_txt:
                if "await initDb()" not in b_txt and "initDb().then(" not in b_txt:
                    return False, (
                        "ASYNC_DB_READINESS_RACE: 'initDb()' is asynchronous, but 'app.listen()' does not await its completion. "
                        "Incoming requests will hit uninitialized tables."
                    )

            # Check if app.listen is at top-level while db.serialize is asynchronous callback
            if "db.serialize(" in b_txt:
                # If listen is called top-level before seed completion
                serialize_pos = b_txt.find("db.serialize(")
                if 0 <= serialize_pos < listen_pos:
                    # Check if listen is INSIDE serialize or at outer scope
                    sub_txt = b_txt[serialize_pos:listen_pos]
                    open_braces = sub_txt.count("{")
                    close_braces = sub_txt.count("}")
                    if open_braces <= close_braces and "initDb" not in b_txt:
                        # Top-level listen after serialize started
                        return False, (
                            "ASYNC_DB_READINESS_RACE: 'app.listen()' is invoked synchronously at top-level "
                            "while SQLite 'db.serialize(...)' runs asynchronously. Server must wait for database readiness."
                        )

        return True, None

    @classmethod
    def verify_test_db_isolation(cls, test_content: str, server_module_name: str = "server") -> Tuple[bool, Optional[str]]:
        """
        Verify that database test paths are configured before the server module is imported.
        """
        t_txt = test_content

        # Check for require('../server') or require('./server')
        server_import_match = re.search(rf'require\s*\(\s*[\'"`][^\'"`]*{re.escape(server_module_name)}[\'"`]\s*\)', t_txt)
        if not server_import_match:
            return True, None

        import_pos = server_import_match.start()

        # Check for test DB env assignment: process.env.GLOBALTRADE_TEST_DB_PATH or process.env.TEST_DB_PATH
        env_match = re.search(r'process\.env\.(?:[A-Z0-9_]*TEST_DB[A-Z0-9_]*|DATABASE_URL|DB_PATH)\s*=', t_txt)
        if not env_match:
            return False, (
                "TEST_DB_ISOLATION_FAILURE: Test suite imports server module without configuring a dedicated test database path. "
                "Set 'process.env.GLOBALTRADE_TEST_DB_PATH' before require('../server') to avoid mutating demo database."
            )

        env_pos = env_match.start()
        if env_pos > import_pos:
            return False, (
                "TEST_DB_ISOLATION_RACE: Test suite imports server module BEFORE setting 'process.env.GLOBALTRADE_TEST_DB_PATH'. "
                "The server will connect to the production/demo database on load. Move environment configuration above the require statement."
            )

        return True, None
