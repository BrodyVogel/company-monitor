RATING_TIERS = ["Strong Buy", "Outperform", "Inline", "Underperform", "Sell"]


def compute_upside(current_price, blended_price_target):
    if not current_price or current_price == 0:
        return None
    return (blended_price_target - current_price) / current_price


def compute_suggested_rating(current_price, blended_price_target):
    upside = compute_upside(current_price, blended_price_target)
    if upside is None:
        return "Inline"
    if upside >= 0.35:
        return "Strong Buy"
    if upside >= 0.20:
        return "Outperform"
    if upside >= -0.10:
        return "Inline"
    if upside >= -0.20:
        return "Underperform"
    return "Sell"


def rating_divergence(current_rating, suggested_rating):
    if current_rating == suggested_rating:
        return None
    if current_rating not in RATING_TIERS or suggested_rating not in RATING_TIERS:
        return None
    current_idx = RATING_TIERS.index(current_rating)
    suggested_idx = RATING_TIERS.index(suggested_rating)
    gap = abs(current_idx - suggested_idx)
    if gap >= 2:
        return {
            "tier": "action_required",
            "title": f"Rating divergence: {current_rating} vs suggested {suggested_rating}",
            "description": (
                f"Current rating is {current_rating} but price implies {suggested_rating} "
                f"({gap} tier gap). Review needed."
            ),
        }
    if gap == 1:
        return {
            "tier": "watch",
            "title": f"Rating drift: {current_rating} vs suggested {suggested_rating}",
            "description": (
                f"Current rating is {current_rating} but price implies {suggested_rating} "
                f"(1 tier gap). Monitor for further movement."
            ),
        }
    return None
