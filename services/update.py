import json
from datetime import date
from database import find_company_by_ticker
from services.alert_engine import run_alerts


async def handle_update(db, data):
    ticker = data["ticker"]

    # Look up company (fuzzy matching)
    company = await find_company_by_ticker(db, ticker)
    if not company:
        return {"error": f"Company with ticker {ticker} not found."}
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

    summary_parts = []
    company_changes_applied = []
    scenarios_replaced = 0
    indicators_added = 0
    indicators_removed = 0
    indicators_modified = 0
    indicators_skipped = []
    indicators_unmatched = []
    key_events_added = 0
    key_events_removed = 0

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
                company_changes_applied.append(key)
        if sets:
            sets.append("updated_at = datetime('now')")
            vals.append(company_id)
            await db.execute(
                f"UPDATE companies SET {', '.join(sets)} WHERE id = ?", vals
            )
            # Build readable change descriptions
            for key in company_changes_applied:
                old_val = company.get(key)
                new_val = cc[key]
                if key == "current_rating":
                    summary_parts.append(f"Rating: {old_val} → {new_val}")
                elif key == "blended_price_target":
                    summary_parts.append(f"PT: ${old_val} → ${new_val}")
                elif key == "current_price":
                    summary_parts.append(f"Price: ${old_val} → ${new_val}")

    # Replace scenarios
    if data.get("scenarios_replace") is not None:
        await db.execute("DELETE FROM scenarios WHERE company_id = ?", (company_id,))
        new_scenarios = data["scenarios_replace"]
        for i, s in enumerate(new_scenarios):
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
        scenarios_replaced = len(new_scenarios)
        summary_parts.append(f"Scenarios replaced ({scenarios_replaced} new)")

        # Recalculate blended_price_target from the new scenarios
        bpt = sum(
            (s.get("effective_weight") or 0) * s["implied_price"]
            for s in new_scenarios
        )
        await db.execute(
            "UPDATE companies SET blended_price_target = ?, updated_at = datetime('now') WHERE id = ?",
            (bpt, company_id),
        )

    # Add indicators (skip duplicates by case-insensitive name)
    for ind in data.get("indicators_add", []):
        ind_name = ind["name"].strip()
        existing = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, ind_name),
        )
        if existing:
            indicators_skipped.append(ind_name)
            continue
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
        indicators_added += 1

    # Remove indicators (track unmatched)
    for ind in data.get("indicators_remove", []):
        name = ind if isinstance(ind, str) else ind.get("name", "")
        name_stripped = name.strip()
        existing = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, name_stripped),
        )
        if not existing:
            indicators_unmatched.append(name_stripped)
            continue
        # Deactivate alerts referencing this indicator before deleting it
        for row in existing:
            await db.execute(
                "UPDATE alerts SET is_active = 0 WHERE indicator_id = ? AND is_active = 1",
                (row["id"],),
            )
        await db.execute(
            "DELETE FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, name_stripped),
        )
        indicators_removed += 1

    # Modify indicators (track unmatched)
    for ind in data.get("indicators_modify", []):
        name = ind["name"].strip()
        db_ind = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, name),
        )
        if not db_ind:
            indicators_unmatched.append(name)
            continue
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
        indicators_modified += 1

    # Add key events (skip duplicates by case-insensitive name)
    for ev in data.get("key_events_add", []):
        ev_name = ev["event"].strip()
        existing = await db.execute_fetchall(
            "SELECT id FROM key_events WHERE company_id = ? AND LOWER(TRIM(event)) = LOWER(?)",
            (company_id, ev_name),
        )
        if existing:
            continue
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
        key_events_added += 1

    # Remove key events
    for ev in data.get("key_events_remove", []):
        name = ev if isinstance(ev, str) else ev.get("event", "")
        name_stripped = name.strip()
        await db.execute(
            "DELETE FROM key_events WHERE company_id = ? AND LOWER(TRIM(event)) = LOWER(?)",
            (company_id, name_stripped),
        )
        key_events_removed += 1

    # Update materials_as_of
    update_date = data.get("update_date")
    if update_date:
        await db.execute(
            "UPDATE companies SET materials_as_of = ?, updated_at = datetime('now') WHERE id = ?",
            (update_date, company_id),
        )

    # Recommendation history tracking
    cc = data.get("company_changes", {})
    old_rating = company.get("current_rating")
    new_rating = cc.get("current_rating")
    rating_changed = new_rating is not None and new_rating != old_rating
    effective_date = update_date or date.today().isoformat()

    # Fetch updated company state for current values
    updated_company = await db.execute_fetchall(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    )
    updated_company = dict(updated_company[0]) if updated_company else company

    if rating_changed:
        # Close the current open entry
        await db.execute(
            """UPDATE recommendation_history
               SET ended_at = ?, price_at_end = ?
               WHERE company_id = ? AND ended_at IS NULL""",
            (effective_date, updated_company["current_price"], company_id),
        )
        # Open a new entry
        await db.execute(
            """INSERT INTO recommendation_history
               (company_id, rating, price_at_start, target_at_start, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                company_id,
                new_rating,
                updated_company["current_price"],
                updated_company["blended_price_target"],
                effective_date,
            ),
        )
    elif "blended_price_target" in cc:
        # Target changed but rating didn't — update current open entry
        await db.execute(
            """UPDATE recommendation_history
               SET target_at_start = ?
               WHERE company_id = ? AND ended_at IS NULL""",
            (updated_company["blended_price_target"], company_id),
        )

    await db.commit()

    # Run alert engine
    await run_alerts(db, company_id)

    # Build summary
    if indicators_added:
        summary_parts.append(f"{indicators_added} indicator added")
    if indicators_removed:
        summary_parts.append(f"{indicators_removed} removed")
    if indicators_modified:
        summary_parts.append(f"{indicators_modified} modified")
    if key_events_added:
        summary_parts.append(f"{key_events_added} event added")
    if key_events_removed:
        summary_parts.append(f"{key_events_removed} event removed")

    summary = f"Materials updated. " + ". ".join(summary_parts) + "." if summary_parts else f"Update for {ticker}. No changes applied."

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
        "company_changes_applied": company_changes_applied,
        "scenarios_replaced": scenarios_replaced,
        "indicators_added": indicators_added,
        "indicators_removed": indicators_removed,
        "indicators_modified": indicators_modified,
        "indicators_skipped": indicators_skipped,
        "indicators_unmatched": indicators_unmatched,
        "key_events_added": key_events_added,
        "key_events_removed": key_events_removed,
    }
