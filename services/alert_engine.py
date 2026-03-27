import json
from datetime import datetime, timedelta
from services.rating_logic import compute_suggested_rating, rating_divergence


async def run_alerts(db, company_id):
    company = await db.execute_fetchall(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    )
    if not company:
        return
    company = dict(company[0])

    # 1. Rating divergence
    suggested = compute_suggested_rating(
        company["current_price"], company["blended_price_target"]
    )
    div = rating_divergence(company["current_rating"], suggested)
    if div:
        await _upsert_alert(
            db,
            company_id,
            indicator_id=None,
            tier=div["tier"],
            title=div["title"],
            description=div["description"],
        )
    else:
        # Deactivate any existing rating divergence alerts
        await db.execute(
            """UPDATE alerts SET is_active = 0
               WHERE company_id = ? AND is_active = 1
               AND (title LIKE 'Rating divergence:%' OR title LIKE 'Rating drift:%')""",
            (company_id,),
        )

    # 2. Sweep-driven alerts for indicators with status 'action_required'
    indicators = await db.execute_fetchall(
        "SELECT * FROM indicators WHERE company_id = ? AND status = 'action_required'",
        (company_id,),
    )
    for ind in indicators:
        ind = dict(ind)
        # Get latest reading for rationale/sources
        reading = await db.execute_fetchall(
            """SELECT * FROM indicator_readings
               WHERE indicator_id = ?
               ORDER BY id DESC LIMIT 1""",
            (ind["id"],),
        )
        change_rationale = None
        sources = None
        if reading:
            reading = dict(reading[0])
            change_rationale = reading.get("change_rationale")
            sources = reading.get("sources")

        await _upsert_alert(
            db,
            company_id,
            indicator_id=ind["id"],
            tier="action_required",
            title=f"Material change: {ind['name']}",
            description=f"Indicator '{ind['name']}' flagged as material change.",
            change_rationale=change_rationale,
            sources=sources,
        )

    # 3. Staleness checks
    now = datetime.utcnow()

    if company["last_sweep_at"]:
        last_sweep = datetime.fromisoformat(company["last_sweep_at"])
        if (now - last_sweep) > timedelta(days=7):
            await _upsert_alert(
                db,
                company_id,
                indicator_id=None,
                tier="watch",
                title=f"Sweep overdue for {company['name']}",
                description=f"Last sweep was {company['last_sweep_at']}. Consider running a new sweep.",
            )
    else:
        # No sweep ever done — could alert
        await _upsert_alert(
            db,
            company_id,
            indicator_id=None,
            tier="watch",
            title=f"Sweep overdue for {company['name']}",
            description="No sweep has been recorded yet for this company.",
        )

    if company["materials_as_of"]:
        materials_date = datetime.fromisoformat(company["materials_as_of"])
        if (now - materials_date) > timedelta(days=90):
            await _upsert_alert(
                db,
                company_id,
                indicator_id=None,
                tier="watch",
                title=f"Materials may be stale for {company['name']}",
                description=f"Materials as of {company['materials_as_of']} — over 90 days old.",
            )

    await db.commit()


async def _upsert_alert(
    db,
    company_id,
    indicator_id,
    tier,
    title,
    description,
    change_rationale=None,
    sources=None,
):
    existing = await db.execute_fetchall(
        "SELECT id FROM alerts WHERE company_id = ? AND title = ? AND is_active = 1",
        (company_id, title),
    )
    if existing:
        await db.execute(
            """UPDATE alerts SET tier = ?, description = ?, change_rationale = ?, sources = ?
               WHERE id = ?""",
            (tier, description, change_rationale, sources, existing[0]["id"]),
        )
    else:
        await db.execute(
            """INSERT INTO alerts (company_id, indicator_id, tier, title, description, change_rationale, sources)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (company_id, indicator_id, tier, title, description, change_rationale, sources),
        )
