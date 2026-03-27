import json
import re
from datetime import datetime, timedelta
from services.rating_logic import compute_suggested_rating, rating_divergence


def parse_threshold(threshold_text):
    """Parse a threshold string like '<860K', '>6.5%', '>$120 4wk'.
    Returns (direction, numeric_value) or (None, None) if unparsable.
    Suffixes like K/M/B/T are stripped (not expanded), since value_numeric
    in readings already uses the same scale as the threshold number.
    """
    if not threshold_text or not isinstance(threshold_text, str):
        return None, None

    text = threshold_text.strip()
    if text.lower() in ("n/a", "na", ""):
        return None, None

    # Extract direction
    direction = None
    for op in (">=", "<=", ">", "<"):
        if text.startswith(op):
            direction = op
            text = text[len(op):]
            break

    if direction is None:
        return None, None

    # Strip currency symbols
    text = text.lstrip("$¥€£ ")

    # Try to extract the leading number (with optional decimal)
    # Suffixes (K, M, B, T, %) and trailing text are stripped
    m = re.match(r"([+\-]?\d+(?:\.\d+)?)", text)
    if not m:
        return None, None

    value = float(m.group(1))
    return direction, value


def check_threshold_breach(value_numeric, bear_threshold_text, bull_threshold_text):
    """Check if a numeric value breaches bear or bull thresholds.
    Returns 'action_required' if breached, 'all_clear' otherwise.
    """
    if value_numeric is None:
        return "all_clear"

    for threshold_text in (bear_threshold_text, bull_threshold_text):
        direction, threshold_val = parse_threshold(threshold_text)
        if direction is None:
            continue
        if direction in (">", ">=") and value_numeric > threshold_val:
            return "action_required"
        if direction in ("<", "<=") and value_numeric < threshold_val:
            return "action_required"

    return "all_clear"


def get_indicator_trend(readings, bear_threshold_text, bull_threshold_text):
    """Analyze trend from readings (most recent first).
    Returns dict with direction, velocity, projected_breach_readings.
    """
    result = {"direction": "unknown", "velocity": None, "projected_breach_readings": None}

    if len(readings) < 3:
        return result

    # Only use readings that have numeric values
    numeric_readings = [r for r in readings if r.get("value_numeric") is not None]
    if len(numeric_readings) < 3:
        return result

    values = [r["value_numeric"] for r in numeric_readings]
    # values[0] is most recent

    # Simple linear velocity: average change per reading
    changes = [values[i] - values[i + 1] for i in range(len(values) - 1)]
    velocity = sum(changes) / len(changes)
    result["velocity"] = velocity

    if abs(velocity) < 1e-9:
        result["direction"] = "stable"
        return result

    current = values[0]

    # Determine nearest threshold and direction
    bear_dir, bear_val = parse_threshold(bear_threshold_text)
    bull_dir, bull_val = parse_threshold(bull_threshold_text)

    # Check which threshold we're moving toward
    breach_readings = None
    moving_toward_threshold = False

    if bear_dir and bear_val is not None:
        if bear_dir in (">", ">=") and velocity > 0:
            # Moving up toward a ">" bear threshold
            gap = bear_val - current
            if gap > 0:
                breach_readings = gap / velocity
                moving_toward_threshold = True
        elif bear_dir in ("<", "<=") and velocity < 0:
            # Moving down toward a "<" bear threshold
            gap = current - bear_val
            if gap > 0:
                breach_readings = gap / abs(velocity)
                moving_toward_threshold = True

    if bull_dir and bull_val is not None:
        bull_breach = None
        if bull_dir in (">", ">=") and velocity > 0:
            gap = bull_val - current
            if gap > 0:
                bull_breach = gap / velocity
        elif bull_dir in ("<", "<=") and velocity < 0:
            gap = current - bull_val
            if gap > 0:
                bull_breach = gap / abs(velocity)

        if bull_breach is not None:
            if breach_readings is None or bull_breach < breach_readings:
                breach_readings = bull_breach
                moving_toward_threshold = True

    if moving_toward_threshold:
        result["direction"] = "worsening"
        result["projected_breach_readings"] = round(breach_readings, 1) if breach_readings else None
    elif abs(velocity) > 1e-9:
        result["direction"] = "improving"
    else:
        result["direction"] = "stable"

    return result


async def run_alerts(db, company_id):
    company = await db.execute_fetchall(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    )
    if not company:
        return
    company = dict(company[0])

    # 1. Rating divergence — create or clear
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
        await db.execute(
            """UPDATE alerts SET is_active = 0
               WHERE company_id = ? AND is_active = 1
               AND (title LIKE 'Rating divergence:%' OR title LIKE 'Rating drift:%')""",
            (company_id,),
        )

    # 2. Sweep-driven material change alerts (from sweep handler marking status)
    indicators = await db.execute_fetchall(
        "SELECT * FROM indicators WHERE company_id = ?",
        (company_id,),
    )

    for ind in indicators:
        ind = dict(ind)

        if ind["status"] == "action_required":
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
        # Material change alerts are NOT auto-cleared — they require manual dismissal

    # 3. Threshold sanity check
    for ind in indicators:
        ind = dict(ind) if not isinstance(ind, dict) else ind

        if ind["status"] == "action_required":
            continue  # already alerted above

        breach = check_threshold_breach(
            ind.get("current_value_numeric"),
            ind.get("bear_threshold"),
            ind.get("bull_threshold"),
        )
        if breach == "action_required":
            title = f"Threshold watch: {ind['name']}"
            # Don't duplicate if there's already an active material change alert
            existing_material = await db.execute_fetchall(
                "SELECT id FROM alerts WHERE company_id = ? AND title = ? AND is_active = 1",
                (company_id, f"Material change: {ind['name']}"),
            )
            if not existing_material:
                await _upsert_alert(
                    db,
                    company_id,
                    indicator_id=ind["id"],
                    tier="watch",
                    title=title,
                    description=f"Indicator may have crossed threshold — verify on next sweep. "
                                f"Value: {ind.get('current_value')}, "
                                f"Bear: {ind.get('bear_threshold')}, Bull: {ind.get('bull_threshold')}.",
                )
        else:
            # Clear threshold watch alerts if no longer breaching
            await db.execute(
                "UPDATE alerts SET is_active = 0 WHERE company_id = ? AND title = ? AND is_active = 1",
                (company_id, f"Threshold watch: {ind['name']}"),
            )

    # 4. Trend detection
    for ind in indicators:
        ind = dict(ind) if not isinstance(ind, dict) else ind

        all_readings = await db.execute_fetchall(
            """SELECT value_numeric, sweep_date FROM indicator_readings
               WHERE indicator_id = ?
               ORDER BY id DESC""",
            (ind["id"],),
        )
        all_readings = [dict(r) for r in all_readings]

        if len(all_readings) >= 3:
            trend = get_indicator_trend(
                all_readings, ind.get("bear_threshold"), ind.get("bull_threshold")
            )
            title = f"Trend alert: {ind['name']}"
            if (
                trend["direction"] == "worsening"
                and trend["projected_breach_readings"] is not None
                and trend["projected_breach_readings"] <= 3
            ):
                # Estimate days based on check frequency
                freq = (ind.get("check_frequency") or "").lower()
                days_per_reading = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}.get(freq, 30)
                est_days = round(trend["projected_breach_readings"] * days_per_reading)

                await _upsert_alert(
                    db,
                    company_id,
                    indicator_id=ind["id"],
                    tier="watch",
                    title=title,
                    description=f"Trending toward threshold: {ind['name']} may breach "
                                f"within ~{est_days} days at current pace.",
                )
            else:
                # Clear trend alert if no longer trending toward breach
                await db.execute(
                    "UPDATE alerts SET is_active = 0 WHERE company_id = ? AND title = ? AND is_active = 1",
                    (company_id, title),
                )

    # 5. Staleness checks — create or clear
    now = datetime.utcnow()

    sweep_overdue_title = f"Sweep overdue for {company['name']}"
    if company["last_sweep_at"]:
        last_sweep = datetime.fromisoformat(company["last_sweep_at"])
        if (now - last_sweep) > timedelta(days=7):
            await _upsert_alert(
                db,
                company_id,
                indicator_id=None,
                tier="watch",
                title=sweep_overdue_title,
                description=f"Last sweep was {company['last_sweep_at']}. Consider running a new sweep.",
            )
        else:
            # Sweep is recent — clear any overdue alerts
            await db.execute(
                "UPDATE alerts SET is_active = 0 WHERE company_id = ? AND title = ? AND is_active = 1",
                (company_id, sweep_overdue_title),
            )
    else:
        await _upsert_alert(
            db,
            company_id,
            indicator_id=None,
            tier="watch",
            title=sweep_overdue_title,
            description="No sweep has been recorded yet for this company.",
        )

    materials_stale_title = f"Materials may be stale for {company['name']}"
    if company["materials_as_of"]:
        materials_date = datetime.fromisoformat(company["materials_as_of"])
        if (now - materials_date) > timedelta(days=90):
            await _upsert_alert(
                db,
                company_id,
                indicator_id=None,
                tier="watch",
                title=materials_stale_title,
                description=f"Materials as of {company['materials_as_of']} — over 90 days old.",
            )
        else:
            # Materials are fresh — clear stale alerts
            await db.execute(
                "UPDATE alerts SET is_active = 0 WHERE company_id = ? AND title = ? AND is_active = 1",
                (company_id, materials_stale_title),
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
