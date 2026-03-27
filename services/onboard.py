import json
from datetime import date
from services.alert_engine import run_alerts


async def handle_onboard(db, data):
    company_data = data["company"]
    ticker = company_data["ticker"]

    # Check if ticker already exists
    existing = await db.execute_fetchall(
        "SELECT id FROM companies WHERE ticker = ?", (ticker,)
    )
    if existing:
        return {"error": f"Company with ticker {ticker} already exists."}

    # Insert company
    materials_as_of = company_data.get("materials_date") or date.today().isoformat()
    cursor = await db.execute(
        """INSERT INTO companies (name, ticker, exchange, currency, current_rating,
           current_price, blended_price_target, materials_as_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_data["name"],
            company_data["ticker"],
            company_data.get("exchange"),
            company_data["currency"],
            company_data["current_rating"],
            company_data.get("current_price"),
            company_data["blended_price_target"],
            materials_as_of,
        ),
    )
    company_id = cursor.lastrowid

    # Insert scenarios
    for i, scenario in enumerate(data.get("scenarios", [])):
        await db.execute(
            """INSERT INTO scenarios (company_id, name, raw_weight, effective_weight,
               implied_price, summary, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                scenario["name"],
                scenario.get("raw_weight"),
                scenario.get("effective_weight"),
                scenario["implied_price"],
                scenario.get("summary"),
                i,
            ),
        )

    # Insert indicators
    for indicator in data.get("indicators", []):
        await db.execute(
            """INSERT INTO indicators (company_id, name, current_value, current_value_numeric,
               bear_threshold, bull_threshold, check_frequency, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                indicator["name"],
                indicator.get("current_value"),
                indicator.get("current_value_numeric"),
                indicator.get("bear_threshold"),
                indicator.get("bull_threshold"),
                indicator["check_frequency"],
                indicator["data_source"],
            ),
        )

    # Insert key events
    for event in data.get("key_events", []):
        indicators_affected = event.get("indicators_affected")
        if isinstance(indicators_affected, list):
            indicators_affected = json.dumps(indicators_affected)
        await db.execute(
            """INSERT INTO key_events (company_id, event, expected_date, why_it_matters,
               indicators_affected)
               VALUES (?, ?, ?, ?, ?)""",
            (
                company_id,
                event["event"],
                event.get("expected_date"),
                event.get("why_it_matters"),
                indicators_affected,
            ),
        )

    # Insert initial price into price_history
    if company_data.get("current_price") is not None:
        await db.execute(
            """INSERT INTO price_history (company_id, price, source, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (company_id, company_data["current_price"], "onboard", materials_as_of),
        )

    await db.commit()

    # Run alert engine
    await run_alerts(db, company_id)

    # Build summary
    n_scenarios = len(data.get("scenarios", []))
    n_indicators = len(data.get("indicators", []))
    n_events = len(data.get("key_events", []))
    summary = (
        f"Initiated coverage on {company_data['name']}. "
        f"Rating: {company_data['current_rating']}. "
        f"PT: ${company_data['blended_price_target']:.2f}. "
        f"{n_scenarios} scenarios, {n_indicators} indicators, {n_events} key events."
    )

    # Write change log
    await db.execute(
        """INSERT INTO change_log (company_id, action, summary, details, before_state)
           VALUES (?, ?, ?, ?, ?)""",
        (company_id, "onboard", summary, json.dumps(data), None),
    )
    await db.commit()

    return {
        "status": "ok",
        "action": "onboard",
        "company_id": company_id,
        "summary": summary,
    }
