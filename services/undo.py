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
        return {"error": "Already undone"}

    # Check it's the most recent non-undone entry for this company (excluding undo entries)
    latest = await db.execute_fetchall(
        """SELECT id FROM change_log
           WHERE company_id = ? AND is_undone = 0 AND action != 'undo'
           ORDER BY id DESC LIMIT 1""",
        (entry["company_id"],),
    )
    if not latest or latest[0]["id"] != change_log_id:
        most_recent_id = latest[0]["id"] if latest else None
        return {"error": f"Can only undo the most recent import. Undo ID {most_recent_id} first."}

    action = entry["action"]
    company_id = entry["company_id"]
    before_state = json.loads(entry["before_state"]) if entry["before_state"] else None

    # Get company name for summary
    company_rows = await db.execute_fetchall(
        "SELECT name FROM companies WHERE id = ?", (company_id,)
    )
    company_name = company_rows[0]["name"] if company_rows else "Unknown"

    if action == "onboard":
        # Delete the company — CASCADE handles everything (including change_log entries)
        await db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        await db.commit()
        return {
            "status": "ok",
            "summary": f"Undid onboard for {company_name}. Company and all data deleted.",
        }

    elif action == "sweep":
        if not before_state:
            return {"error": "No before_state to restore from."}

        details = json.loads(entry["details"]) if entry["details"] else {}
        sweep_date = details.get("sweep_date")

        # Restore price
        await db.execute(
            "UPDATE companies SET current_price = ?, updated_at = datetime('now') WHERE id = ?",
            (before_state["current_price"], company_id),
        )

        # Restore indicators to before_state values
        for ind_snap in before_state.get("indicators", []):
            await db.execute(
                """UPDATE indicators SET current_value = ?, current_value_numeric = ?,
                   status = ?, last_checked_at = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    ind_snap["current_value"],
                    ind_snap["current_value_numeric"],
                    ind_snap["status"],
                    ind_snap.get("last_checked_at"),
                    ind_snap["id"],
                ),
            )

        # Delete indicator_readings created by this sweep
        # Use readings where created_at >= change_log entry's created_at for this company's indicators
        ind_rows = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE company_id = ?", (company_id,)
        )
        ind_ids = [r["id"] for r in ind_rows]
        if ind_ids:
            placeholders = ",".join("?" * len(ind_ids))
            await db.execute(
                f"""DELETE FROM indicator_readings
                    WHERE indicator_id IN ({placeholders}) AND created_at >= ?""",
                ind_ids + [entry["created_at"]],
            )

        # Delete alerts created after this change_log entry for this company
        # (sweep-related: material change, threshold watch alerts)
        await db.execute(
            """UPDATE alerts SET is_active = 0
               WHERE company_id = ? AND created_at >= ?
               AND (title LIKE 'Material change:%' OR title LIKE 'Threshold watch:%')""",
            (company_id, entry["created_at"]),
        )

        # Delete price_history entries created at or after this change_log entry
        await db.execute(
            "DELETE FROM price_history WHERE company_id = ? AND recorded_at >= ?",
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

        # Mark as undone
        await db.execute(
            "UPDATE change_log SET is_undone = 1 WHERE id = ?", (change_log_id,)
        )

        # Write undo log entry
        summary = f"Undid sweep from {sweep_date}." if sweep_date else f"Undid sweep from {entry['created_at']}."
        await db.execute(
            """INSERT INTO change_log (company_id, action, summary, details, before_state)
               VALUES (?, ?, ?, ?, ?)""",
            (company_id, "undo", summary, json.dumps({"undone_entry_id": change_log_id}), None),
        )

        await db.commit()

        # Run alert engine to recalculate alerts based on restored state
        await run_alerts(db, company_id)

        return {"status": "ok", "summary": summary}

    elif action == "update":
        if not before_state:
            return {"error": "No before_state to restore from."}

        details = json.loads(entry["details"]) if entry["details"] else {}
        update_date = details.get("update_date", entry["created_at"])

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

        # Replace scenarios — safe to delete and re-insert
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

        # Handle indicators carefully to preserve readings on pre-existing indicators
        before_indicators = before_state.get("indicators", [])
        before_names = {ind["name"].strip().lower(): ind for ind in before_indicators}

        # Get current indicators
        current_inds = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM indicators WHERE company_id = ?", (company_id,)
            )
        ]
        current_names = {ind["name"].strip().lower(): ind for ind in current_inds}

        # Delete indicators ADDED by the update (exist now but not in before_state)
        for name_lower, ind in current_names.items():
            if name_lower not in before_names:
                await db.execute("DELETE FROM indicators WHERE id = ?", (ind["id"],))

        # Re-create indicators REMOVED by the update (in before_state but not current)
        for name_lower, ind_snap in before_names.items():
            if name_lower not in current_names:
                await db.execute(
                    """INSERT INTO indicators (company_id, name, current_value, current_value_numeric,
                       bear_threshold, bull_threshold, check_frequency, data_source, status, last_checked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        company_id, ind_snap["name"], ind_snap.get("current_value"),
                        ind_snap.get("current_value_numeric"), ind_snap.get("bear_threshold"),
                        ind_snap.get("bull_threshold"), ind_snap["check_frequency"],
                        ind_snap["data_source"], ind_snap.get("status", "all_clear"),
                        ind_snap.get("last_checked_at"),
                    ),
                )

        # Restore MODIFIED indicators to their before_state values
        for name_lower, ind_snap in before_names.items():
            if name_lower in current_names:
                cur = current_names[name_lower]
                await db.execute(
                    """UPDATE indicators SET current_value = ?, current_value_numeric = ?,
                       bear_threshold = ?, bull_threshold = ?, check_frequency = ?,
                       data_source = ?, status = ?, last_checked_at = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (
                        ind_snap.get("current_value"), ind_snap.get("current_value_numeric"),
                        ind_snap.get("bear_threshold"), ind_snap.get("bull_threshold"),
                        ind_snap["check_frequency"], ind_snap["data_source"],
                        ind_snap.get("status", "all_clear"), ind_snap.get("last_checked_at"),
                        cur["id"],
                    ),
                )

        # Undo recommendation_history changes from this update
        details = json.loads(entry["details"]) if entry["details"] else {}
        update_date = details.get("update_date", entry["created_at"])
        # Delete any recommendation_history entry started on the update_date
        await db.execute(
            "DELETE FROM recommendation_history WHERE company_id = ? AND started_at = ?",
            (company_id, update_date),
        )
        # Reopen the previous entry by clearing ended_at and price_at_end
        await db.execute(
            """UPDATE recommendation_history
               SET ended_at = NULL, price_at_end = NULL
               WHERE company_id = ? AND ended_at = ?""",
            (company_id, update_date),
        )

        # Handle key_events: delete added, re-create removed
        before_events = before_state.get("key_events", [])
        before_event_names = {ev["event"].strip().lower(): ev for ev in before_events}

        current_events = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM key_events WHERE company_id = ?", (company_id,)
            )
        ]
        current_event_names = {ev["event"].strip().lower(): ev for ev in current_events}

        # Delete events ADDED by the update
        for name_lower, ev in current_event_names.items():
            if name_lower not in before_event_names:
                await db.execute("DELETE FROM key_events WHERE id = ?", (ev["id"],))

        # Re-create events REMOVED by the update
        for name_lower, ev_snap in before_event_names.items():
            if name_lower not in current_event_names:
                await db.execute(
                    """INSERT INTO key_events (company_id, event, expected_date, why_it_matters,
                       indicators_affected, occurred, outcome_summary, occurred_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        company_id, ev_snap["event"], ev_snap.get("expected_date"),
                        ev_snap.get("why_it_matters"), ev_snap.get("indicators_affected"),
                        ev_snap.get("occurred", 0), ev_snap.get("outcome_summary"),
                        ev_snap.get("occurred_date"),
                    ),
                )

        # Mark as undone
        await db.execute(
            "UPDATE change_log SET is_undone = 1 WHERE id = ?", (change_log_id,)
        )

        # Write undo log entry
        summary = f"Undid update from {update_date}."
        await db.execute(
            """INSERT INTO change_log (company_id, action, summary, details, before_state)
               VALUES (?, ?, ?, ?, ?)""",
            (company_id, "undo", summary, json.dumps({"undone_entry_id": change_log_id}), None),
        )

        await db.commit()

        # Run alert engine to recalculate
        await run_alerts(db, company_id)

        return {"status": "ok", "summary": summary}

    else:
        return {"error": f"Cannot undo action type '{action}'."}
