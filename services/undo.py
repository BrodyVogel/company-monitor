import json
from services.alert_engine import run_alerts


async def handle_undo(db, change_log_id):
    # Get entry
    rows = await db.execute_fetchall(
        "SELECT * FROM change_log WHERE id = ?", (change_log_id,)
    )
    if not rows:
        return {"error": f"Change log entry {change_log_id} not found."}
    entry = dict(rows[0])

    if entry["is_undone"]:
        return {"error": "This entry has already been undone."}

    # Check it's the most recent non-undone entry for this company
    latest = await db.execute_fetchall(
        """SELECT id FROM change_log
           WHERE company_id = ? AND is_undone = 0
           ORDER BY id DESC LIMIT 1""",
        (entry["company_id"],),
    )
    if not latest or latest[0]["id"] != change_log_id:
        return {"error": "Can only undo the most recent non-undone entry for this company."}

    action = entry["action"]
    company_id = entry["company_id"]
    before_state = json.loads(entry["before_state"]) if entry["before_state"] else None

    if action == "onboard":
        # Delete the company — CASCADE handles everything
        await db.execute("DELETE FROM companies WHERE id = ?", (company_id,))

    elif action == "sweep":
        if not before_state:
            return {"error": "No before_state to restore from."}

        # Restore price
        await db.execute(
            "UPDATE companies SET current_price = ?, updated_at = datetime('now') WHERE id = ?",
            (before_state["current_price"], company_id),
        )

        # Restore indicators
        for ind_snap in before_state.get("indicators", []):
            await db.execute(
                """UPDATE indicators SET current_value = ?, current_value_numeric = ?,
                   status = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    ind_snap["current_value"],
                    ind_snap["current_value_numeric"],
                    ind_snap["status"],
                    ind_snap["id"],
                ),
            )

        # Delete readings from this sweep
        details = json.loads(entry["details"]) if entry["details"] else {}
        sweep_date = details.get("sweep_date")
        if sweep_date:
            # Get indicator IDs for this company
            ind_rows = await db.execute_fetchall(
                "SELECT id FROM indicators WHERE company_id = ?", (company_id,)
            )
            ind_ids = [r["id"] for r in ind_rows]
            if ind_ids:
                placeholders = ",".join("?" * len(ind_ids))
                await db.execute(
                    f"""DELETE FROM indicator_readings
                        WHERE indicator_id IN ({placeholders}) AND sweep_date = ?""",
                    ind_ids + [sweep_date],
                )

        # Deactivate alerts created after this change_log entry
        await db.execute(
            "UPDATE alerts SET is_active = 0 WHERE company_id = ? AND created_at >= ?",
            (company_id, entry["created_at"]),
        )

        # Reset last_sweep_at — find previous sweep log
        prev_sweep = await db.execute_fetchall(
            """SELECT details FROM change_log
               WHERE company_id = ? AND action = 'sweep' AND is_undone = 0 AND id < ?
               ORDER BY id DESC LIMIT 1""",
            (company_id, change_log_id),
        )
        if prev_sweep:
            prev_details = json.loads(prev_sweep[0]["details"])
            await db.execute(
                "UPDATE companies SET last_sweep_at = ?, updated_at = datetime('now') WHERE id = ?",
                (prev_details.get("sweep_date"), company_id),
            )
        else:
            await db.execute(
                "UPDATE companies SET last_sweep_at = NULL, updated_at = datetime('now') WHERE id = ?",
                (company_id,),
            )

    elif action == "update":
        if not before_state:
            return {"error": "No before_state to restore from."}

        # Restore company fields
        c = before_state["company"]
        await db.execute(
            """UPDATE companies SET name = ?, ticker = ?, exchange = ?, currency = ?,
               current_rating = ?, current_price = ?, blended_price_target = ?,
               materials_as_of = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (
                c["name"], c["ticker"], c["exchange"], c["currency"],
                c["current_rating"], c["current_price"], c["blended_price_target"],
                c["materials_as_of"], company_id,
            ),
        )

        # Replace scenarios
        await db.execute("DELETE FROM scenarios WHERE company_id = ?", (company_id,))
        for s in before_state.get("scenarios", []):
            await db.execute(
                """INSERT INTO scenarios (company_id, name, raw_weight, effective_weight,
                   implied_price, summary, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id, s["name"], s.get("raw_weight"),
                    s.get("effective_weight"), s["implied_price"],
                    s.get("summary"), s.get("sort_order"),
                ),
            )

        # Replace indicators
        await db.execute("DELETE FROM indicators WHERE company_id = ?", (company_id,))
        for ind in before_state.get("indicators", []):
            await db.execute(
                """INSERT INTO indicators (company_id, name, current_value, current_value_numeric,
                   bear_threshold, bull_threshold, check_frequency, data_source, status, last_checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id, ind["name"], ind.get("current_value"),
                    ind.get("current_value_numeric"), ind.get("bear_threshold"),
                    ind.get("bull_threshold"), ind["check_frequency"],
                    ind["data_source"], ind.get("status", "all_clear"),
                    ind.get("last_checked_at"),
                ),
            )

        # Replace key events
        await db.execute("DELETE FROM key_events WHERE company_id = ?", (company_id,))
        for ev in before_state.get("key_events", []):
            await db.execute(
                """INSERT INTO key_events (company_id, event, expected_date, why_it_matters,
                   indicators_affected, occurred, outcome_summary, occurred_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id, ev["event"], ev.get("expected_date"),
                    ev.get("why_it_matters"), ev.get("indicators_affected"),
                    ev.get("occurred", 0), ev.get("outcome_summary"),
                    ev.get("occurred_date"),
                ),
            )

    # Mark as undone
    await db.execute(
        "UPDATE change_log SET is_undone = 1 WHERE id = ?", (change_log_id,)
    )

    # Write undo log entry
    await db.execute(
        """INSERT INTO change_log (company_id, action, summary, details, before_state)
           VALUES (?, ?, ?, ?, ?)""",
        (
            company_id,
            "undo",
            f"Undid {action} from {entry['created_at']}.",
            json.dumps({"undone_entry_id": change_log_id}),
            None,
        ),
    )

    await db.commit()

    return {
        "status": "ok",
        "summary": f"Undid {action} from {entry['created_at']}.",
    }
