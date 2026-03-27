import json
from fastapi import APIRouter, File, UploadFile, Request, HTTPException
from database import get_db
from services.import_handler import route_import
from services.rating_logic import compute_suggested_rating, compute_upside
from services.undo import handle_undo

router = APIRouter(prefix="/api")


@router.post("/import")
async def import_data(request: Request, file: UploadFile = File(None)):
    if file:
        content = await file.read()
        data = json.loads(content)
    else:
        data = await request.json()

    db = await get_db()
    try:
        result = await route_import(db, data)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    finally:
        await db.close()


@router.get("/companies")
async def list_companies():
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT * FROM companies ORDER BY name")
        companies = []
        for row in rows:
            c = dict(row)
            suggested = compute_suggested_rating(c["current_price"], c["blended_price_target"])
            upside = compute_upside(c["current_price"], c["blended_price_target"])

            # Alert counts
            alert_rows = await db.execute_fetchall(
                "SELECT tier, COUNT(*) as cnt FROM alerts WHERE company_id = ? AND is_active = 1 GROUP BY tier",
                (c["id"],),
            )
            alert_counts = {r["tier"]: r["cnt"] for r in alert_rows}

            c["suggested_rating"] = suggested
            c["upside_pct"] = round(upside * 100, 2) if upside is not None else None
            c["alert_counts"] = alert_counts
            companies.append(c)
        return companies
    finally:
        await db.close()


@router.get("/companies/{ticker}")
async def get_company(ticker: str):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM companies WHERE ticker = ?", (ticker,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
        company = dict(rows[0])
        company_id = company["id"]

        company["suggested_rating"] = compute_suggested_rating(
            company["current_price"], company["blended_price_target"]
        )
        company["upside_pct"] = round(
            compute_upside(company["current_price"], company["blended_price_target"]) * 100, 2
        ) if company["current_price"] else None

        # Scenarios
        scenarios = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM scenarios WHERE company_id = ? ORDER BY sort_order",
                (company_id,),
            )
        ]

        # Indicators with latest reading
        ind_rows = await db.execute_fetchall(
            "SELECT * FROM indicators WHERE company_id = ?", (company_id,)
        )
        indicators = []
        for ind in ind_rows:
            ind_dict = dict(ind)
            reading = await db.execute_fetchall(
                """SELECT * FROM indicator_readings
                   WHERE indicator_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (ind_dict["id"],),
            )
            ind_dict["latest_reading"] = dict(reading[0]) if reading else None
            indicators.append(ind_dict)

        # Key events
        key_events = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM key_events WHERE company_id = ?", (company_id,)
            )
        ]

        # Active alerts
        alerts = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM alerts WHERE company_id = ? AND is_active = 1 ORDER BY id DESC",
                (company_id,),
            )
        ]

        # Change log
        change_log = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM change_log WHERE company_id = ? ORDER BY id DESC",
                (company_id,),
            )
        ]

        return {
            "company": company,
            "scenarios": scenarios,
            "indicators": indicators,
            "key_events": key_events,
            "alerts": alerts,
            "change_log": change_log,
        }
    finally:
        await db.close()


@router.get("/indicators/{indicator_id}/readings")
async def get_indicator_readings(indicator_id: int):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM indicators WHERE id = ?", (indicator_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Indicator not found.")
        readings = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM indicator_readings WHERE indicator_id = ? ORDER BY sweep_date DESC",
                (indicator_id,),
            )
        ]
        return readings
    finally:
        await db.close()


@router.delete("/companies/{ticker}")
async def delete_company(ticker: str):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
        company_id = rows[0]["id"]
        await db.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        await db.commit()
        return {"status": "ok", "deleted": ticker}
    finally:
        await db.close()


@router.post("/companies/{ticker}/key-events")
async def create_key_event(ticker: str, request: Request):
    data = await request.json()
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
        company_id = rows[0]["id"]
        indicators_affected = data.get("indicators_affected")
        if isinstance(indicators_affected, list):
            indicators_affected = json.dumps(indicators_affected)
        await db.execute(
            """INSERT INTO key_events (company_id, event, expected_date, why_it_matters,
               indicators_affected)
               VALUES (?, ?, ?, ?, ?)""",
            (
                company_id, data["event"], data.get("expected_date"),
                data.get("why_it_matters"), indicators_affected,
            ),
        )
        await db.commit()
        return {"status": "ok", "event": data["event"]}
    finally:
        await db.close()


@router.post("/companies/{ticker}/indicators")
async def create_indicator(ticker: str, request: Request):
    data = await request.json()
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
        company_id = rows[0]["id"]
        await db.execute(
            """INSERT INTO indicators (company_id, name, current_value, current_value_numeric,
               bear_threshold, bull_threshold, check_frequency, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id, data["name"], data.get("current_value"),
                data.get("current_value_numeric"), data.get("bear_threshold"),
                data.get("bull_threshold"), data.get("check_frequency", "Weekly"),
                data.get("data_source", ""),
            ),
        )
        await db.commit()
        return {"status": "ok", "indicator": data["name"]}
    finally:
        await db.close()


@router.put("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM alerts WHERE id = ?", (alert_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Alert not found.")
        await db.execute(
            "UPDATE alerts SET is_active = 0, acknowledged_at = datetime('now') WHERE id = ?",
            (alert_id,),
        )
        await db.commit()
        return {"status": "ok", "alert_id": alert_id, "acknowledged": True}
    finally:
        await db.close()


@router.post("/undo/{change_log_id}")
async def undo_change(change_log_id: int):
    db = await get_db()
    try:
        result = await handle_undo(db, change_log_id)
        if "error" in result:
            status = 404 if "not found" in result["error"].lower() else 400
            raise HTTPException(status_code=status, detail=result["error"])
        return result
    finally:
        await db.close()


@router.get("/change-log/{ticker}")
async def get_change_log(ticker: str):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
        company_id = rows[0]["id"]
        log = [
            dict(r) for r in await db.execute_fetchall(
                "SELECT * FROM change_log WHERE company_id = ? ORDER BY id DESC",
                (company_id,),
            )
        ]
        return log
    finally:
        await db.close()
