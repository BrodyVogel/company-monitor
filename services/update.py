import json
from services.alert_engine import run_alerts


async def handle_update(db, data):
    ticker = data["ticker"]

    # Look up company
    rows = await db.execute_fetchall(
        "SELECT * FROM companies WHERE ticker = ?", (ticker,)
    )
    if not rows:
        return {"error": f"Company with ticker {ticker} not found."}
    company = dict(rows[0])
    company_id = company["id"]

    # Snapshot before_state
    scenarios_snap = [
        dict(r) for r in await db.execute_fetchall(
            "SELECT * FROM scenarios WHERE company_id = ?", (company_id,)
        )
    ]
    indicators_snap = [
        dict(r) for r in await db.execute_fetchall(
            "SELECT * FROM indicators WHERE company_id = ?", (company_id,)
        )
    ]
    events_snap = [
        dict(r) for r in await db.execute_fetchall(
            "SELECT * FROM key_events WHERE company_id = ?", (company_id,)
        )
    ]
    before_state = {
        "company": company,
        "scenarios": scenarios_snap,
        "indicators": indicators_snap,
        "key_events": events_snap,
    }

    changes_made = []

    # Apply company_changes
    if data.get("company_changes"):
        cc = data["company_changes"]
        allowed = [
            "name", "exchange", "currency", "current_rating", "current_price",
            "blended_price_target",
        ]
        sets = []
        vals = []
        for key in allowed:
            if key in cc:
                sets.append(f"{key} = ?")
                vals.append(cc[key])
        if sets:
            sets.append("updated_at = datetime('now')")
            vals.append(company_id)
            await db.execute(
                f"UPDATE companies SET {', '.join(sets)} WHERE id = ?", vals
            )
            changes_made.append(f"Updated company fields: {', '.join(cc.keys())}")

    # Replace scenarios
    if data.get("scenarios_replace") is not None:
        await db.execute("DELETE FROM scenarios WHERE company_id = ?", (company_id,))
        for i, s in enumerate(data["scenarios_replace"]):
            await db.execute(
                """INSERT INTO scenarios (company_id, name, raw_weight, effective_weight,
                   implied_price, summary, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id, s["name"], s.get("raw_weight"),
                    s.get("effective_weight"), s["implied_price"],
                    s.get("summary"), i,
                ),
            )
        changes_made.append(f"Replaced scenarios ({len(data['scenarios_replace'])} new)")

    # Add indicators
    for ind in data.get("indicators_add", []):
        await db.execute(
            """INSERT INTO indicators (company_id, name, current_value, current_value_numeric,
               bear_threshold, bull_threshold, check_frequency, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id, ind["name"], ind.get("current_value"),
                ind.get("current_value_numeric"), ind.get("bear_threshold"),
                ind.get("bull_threshold"), ind["check_frequency"], ind["data_source"],
            ),
        )
        changes_made.append(f"Added indicator: {ind['name']}")

    # Remove indicators
    for ind in data.get("indicators_remove", []):
        name = ind if isinstance(ind, str) else ind.get("name", "")
        await db.execute(
            "DELETE FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, name.strip()),
        )
        changes_made.append(f"Removed indicator: {name}")

    # Modify indicators
    for ind in data.get("indicators_modify", []):
        name = ind["name"].strip()
        db_ind = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, name),
        )
        if db_ind:
            ind_id = db_ind[0]["id"]
            updatable = [
                "current_value", "current_value_numeric", "bear_threshold",
                "bull_threshold", "check_frequency", "data_source", "status",
            ]
            sets = []
            vals = []
            for key in updatable:
                if key in ind:
                    sets.append(f"{key} = ?")
                    vals.append(ind[key])
            if sets:
                sets.append("updated_at = datetime('now')")
                vals.append(ind_id)
                await db.execute(
                    f"UPDATE indicators SET {', '.join(sets)} WHERE id = ?", vals
                )
            changes_made.append(f"Modified indicator: {name}")

    # Add key events
    for ev in data.get("key_events_add", []):
        indicators_affected = ev.get("indicators_affected")
        if isinstance(indicators_affected, list):
            indicators_affected = json.dumps(indicators_affected)
        await db.execute(
            """INSERT INTO key_events (company_id, event, expected_date, why_it_matters,
               indicators_affected)
               VALUES (?, ?, ?, ?, ?)""",
            (
                company_id, ev["event"], ev.get("expected_date"),
                ev.get("why_it_matters"), indicators_affected,
            ),
        )
        changes_made.append(f"Added event: {ev['event']}")

    # Remove key events
    for ev in data.get("key_events_remove", []):
        name = ev if isinstance(ev, str) else ev.get("event", "")
        await db.execute(
            "DELETE FROM key_events WHERE company_id = ? AND LOWER(TRIM(event)) = LOWER(?)",
            (company_id, name.strip()),
        )
        changes_made.append(f"Removed event: {name}")

    # Update materials_as_of
    update_date = data.get("update_date")
    if update_date:
        await db.execute(
            "UPDATE companies SET materials_as_of = ?, updated_at = datetime('now') WHERE id = ?",
            (update_date, company_id),
        )

    # Recalculate blended_price_target
    scenario_rows = await db.execute_fetchall(
        "SELECT effective_weight, implied_price FROM scenarios WHERE company_id = ?",
        (company_id,),
    )
    if scenario_rows:
        bpt = sum(
            (r["effective_weight"] or 0) * r["implied_price"] for r in scenario_rows
        )
        await db.execute(
            "UPDATE companies SET blended_price_target = ?, updated_at = datetime('now') WHERE id = ?",
            (bpt, company_id),
        )

    await db.commit()

    # Run alert engine
    await run_alerts(db, company_id)

    # Build summary
    summary = f"Update for {ticker}. " + " ".join(changes_made) if changes_made else f"Update for {ticker}. No changes applied."

    # Write change log
    await db.execute(
        """INSERT INTO change_log (company_id, action, summary, details, before_state)
           VALUES (?, ?, ?, ?, ?)""",
        (company_id, "update", summary, json.dumps(data), json.dumps(before_state)),
    )
    await db.commit()

    return {
        "status": "ok",
        "action": "update",
        "summary": summary,
        "changes": changes_made,
    }
