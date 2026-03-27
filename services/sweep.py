import json
from services.alert_engine import run_alerts


async def handle_sweep(db, data):
    ticker = data["ticker"]
    sweep_date = data["sweep_date"]

    # Look up company
    rows = await db.execute_fetchall(
        "SELECT * FROM companies WHERE ticker = ?", (ticker,)
    )
    if not rows:
        return {"error": f"Company with ticker {ticker} not found."}
    company = dict(rows[0])
    company_id = company["id"]

    # Snapshot before_state
    indicators_snap = []
    ind_rows = await db.execute_fetchall(
        "SELECT id, name, current_value, current_value_numeric, status FROM indicators WHERE company_id = ?",
        (company_id,),
    )
    for row in ind_rows:
        indicators_snap.append(dict(row))

    active_alert_rows = await db.execute_fetchall(
        "SELECT id FROM alerts WHERE company_id = ? AND is_active = 1",
        (company_id,),
    )
    active_alert_ids = [r["id"] for r in active_alert_rows]

    before_state = {
        "current_price": company["current_price"],
        "indicators": indicators_snap,
        "active_alert_ids": active_alert_ids,
    }

    # Update price
    new_price = data.get("current_price")
    price_source = data.get("price_source")
    if new_price is not None:
        await db.execute(
            "UPDATE companies SET current_price = ?, price_updated_at = ?, updated_at = datetime('now') WHERE id = ?",
            (new_price, sweep_date, company_id),
        )
        await db.execute(
            "INSERT INTO price_history (company_id, price, source, recorded_at) VALUES (?, ?, ?, ?)",
            (company_id, new_price, price_source, sweep_date),
        )

    # Process indicators
    unmatched = []
    matched_count = 0
    material_changes = []

    for ind_data in data.get("indicators", []):
        ind_name = ind_data["name"].strip()
        # Match by name, case-insensitive
        db_ind = await db.execute_fetchall(
            "SELECT * FROM indicators WHERE company_id = ? AND LOWER(TRIM(name)) = LOWER(?)",
            (company_id, ind_name),
        )
        if not db_ind:
            unmatched.append(ind_name)
            continue

        db_ind = dict(db_ind[0])
        matched_count += 1

        # Insert reading
        sources_str = json.dumps(ind_data.get("sources")) if ind_data.get("sources") else None
        await db.execute(
            """INSERT INTO indicator_readings
               (indicator_id, value_text, value_numeric, prior_value_in_materials,
                material_change, change_rationale, sources, context, confidence, sweep_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                db_ind["id"],
                ind_data["value"],
                ind_data.get("value_numeric"),
                ind_data.get("prior_value_in_materials"),
                1 if ind_data.get("material_change") else 0,
                ind_data.get("change_rationale"),
                sources_str,
                ind_data.get("context"),
                ind_data.get("confidence"),
                sweep_date,
            ),
        )

        # Update indicator status and value
        new_status = "action_required" if ind_data.get("material_change") else "all_clear"
        await db.execute(
            """UPDATE indicators SET current_value = ?, current_value_numeric = ?,
               status = ?, last_checked_at = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (
                ind_data["value"],
                ind_data.get("value_numeric"),
                new_status,
                sweep_date,
                db_ind["id"],
            ),
        )

        if ind_data.get("material_change"):
            material_changes.append(ind_name)

    # Process tracked events
    events_updated = []
    for ev in data.get("events", {}).get("tracked", []):
        if ev.get("occurred"):
            await db.execute(
                """UPDATE key_events SET occurred = 1, outcome_summary = ?,
                   occurred_date = ?, updated_at = datetime('now')
                   WHERE company_id = ? AND LOWER(TRIM(event)) = LOWER(?)""",
                (
                    ev.get("outcome_summary"),
                    ev.get("occurred_date", sweep_date),
                    company_id,
                    ev["event"].strip(),
                ),
            )
            events_updated.append(ev["event"])

    # Discovered events (include in response only)
    discovered_events = data.get("events", {}).get("discovered", [])

    # Update last_sweep_at
    await db.execute(
        "UPDATE companies SET last_sweep_at = ?, updated_at = datetime('now') WHERE id = ?",
        (sweep_date, company_id),
    )

    await db.commit()

    # Run alert engine
    await run_alerts(db, company_id)

    # Build summary
    parts = [f"Sweep for {ticker} on {sweep_date}."]
    if new_price is not None:
        parts.append(f"Price updated to ${new_price:.2f}.")
    parts.append(f"{matched_count} indicators checked.")
    if material_changes:
        parts.append(f"Material changes: {', '.join(material_changes)}.")
    if unmatched:
        parts.append(f"Unmatched indicators: {', '.join(unmatched)}.")
    if events_updated:
        parts.append(f"Events occurred: {', '.join(events_updated)}.")
    summary = " ".join(parts)

    # Write change log
    await db.execute(
        """INSERT INTO change_log (company_id, action, summary, details, before_state)
           VALUES (?, ?, ?, ?, ?)""",
        (company_id, "sweep", summary, json.dumps(data), json.dumps(before_state)),
    )
    await db.commit()

    result = {
        "status": "ok",
        "action": "sweep",
        "summary": summary,
        "matched": matched_count,
        "unmatched": unmatched,
        "material_changes": material_changes,
    }
    if discovered_events:
        result["discovered_events"] = discovered_events

    return result
