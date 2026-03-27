import aiosqlite
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "company_monitor.db")


async def find_company_by_ticker(db, ticker):
    """Fuzzy ticker lookup: exact → base prefix → case-insensitive."""
    # Exact match
    rows = await db.execute_fetchall(
        "SELECT * FROM companies WHERE ticker = ?", (ticker,)
    )
    if rows:
        return dict(rows[0])

    # Base ticker match (strip country suffix): "ASML" matches "ASML-NL"
    base = ticker.split("-")[0]
    rows = await db.execute_fetchall(
        "SELECT * FROM companies WHERE ticker LIKE ?", (base + "%",)
    )
    if rows:
        return dict(rows[0])

    # Case-insensitive match
    rows = await db.execute_fetchall(
        "SELECT * FROM companies WHERE UPPER(ticker) = UPPER(?)", (ticker,)
    )
    if rows:
        return dict(rows[0])

    return None

async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db

async def init_db():
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys = ON")

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ticker TEXT NOT NULL UNIQUE,
            exchange TEXT,
            currency TEXT NOT NULL,
            current_rating TEXT NOT NULL,
            current_price REAL,
            price_updated_at TEXT,
            blended_price_target REAL NOT NULL,
            materials_as_of TEXT,
            last_sweep_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            raw_weight REAL,
            effective_weight REAL,
            implied_price REAL NOT NULL,
            summary TEXT,
            sort_order INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            current_value TEXT,
            current_value_numeric REAL,
            bear_threshold TEXT,
            bull_threshold TEXT,
            check_frequency TEXT NOT NULL,
            data_source TEXT NOT NULL,
            last_checked_at TEXT,
            status TEXT DEFAULT 'all_clear',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS indicator_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator_id INTEGER NOT NULL REFERENCES indicators(id) ON DELETE CASCADE,
            value_text TEXT NOT NULL,
            value_numeric REAL,
            prior_value_in_materials TEXT,
            material_change INTEGER DEFAULT 0,
            change_rationale TEXT,
            sources TEXT,
            context TEXT,
            confidence TEXT,
            sweep_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS key_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            expected_date TEXT,
            why_it_matters TEXT,
            indicators_affected TEXT,
            occurred INTEGER DEFAULT 0,
            outcome_summary TEXT,
            occurred_date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            indicator_id INTEGER,
            tier TEXT NOT NULL CHECK(tier IN ('action_required', 'watch', 'all_clear')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            change_rationale TEXT,
            sources TEXT,
            is_active INTEGER DEFAULT 1,
            acknowledged_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            price REAL NOT NULL,
            source TEXT,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            summary TEXT NOT NULL,
            details TEXT,
            before_state TEXT,
            is_undone INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_scenarios_company_id ON scenarios(company_id);
        CREATE INDEX IF NOT EXISTS idx_indicators_company_id ON indicators(company_id);
        CREATE INDEX IF NOT EXISTS idx_indicator_readings_indicator_id ON indicator_readings(indicator_id);
        CREATE INDEX IF NOT EXISTS idx_key_events_company_id ON key_events(company_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_company_id ON alerts(company_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_is_active ON alerts(is_active);
        CREATE INDEX IF NOT EXISTS idx_price_history_company_id ON price_history(company_id);
        CREATE INDEX IF NOT EXISTS idx_change_log_company_id ON change_log(company_id);

        CREATE TABLE IF NOT EXISTS recommendation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            rating TEXT NOT NULL,
            price_at_start REAL NOT NULL,
            target_at_start REAL NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            price_at_end REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_recommendation_history_company_id ON recommendation_history(company_id);
    """)

    # Backfill recommendation_history for existing companies with zero entries
    rows = await db.execute_fetchall(
        """SELECT c.id, c.current_rating, c.current_price, c.blended_price_target, c.materials_as_of
           FROM companies c
           WHERE NOT EXISTS (
               SELECT 1 FROM recommendation_history rh WHERE rh.company_id = c.id
           )"""
    )
    for row in rows:
        if row[1] and row[2] is not None and row[3] is not None:
            await db.execute(
                """INSERT INTO recommendation_history
                   (company_id, rating, price_at_start, target_at_start, started_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (row[0], row[1], row[2], row[3], row[4] or datetime.now().strftime("%Y-%m-%d")),
            )

    await db.commit()
    await db.close()
