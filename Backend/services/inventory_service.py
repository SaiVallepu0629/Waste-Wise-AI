from datetime import date, timedelta

from Backend.models import InventoryItem
from Backend.schemas import RuleBasedRecommendation


def risk_level_for(score: int) -> str:
    if score >= 65:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


def inventory_status_for(item: InventoryItem, today: date | None = None) -> str:
    today = today or date.today()
    if item.expiry_date < today:
        return "expired"
    if item.quantity == 0:
        return "out_of_stock"
    if item.expiry_date <= today + timedelta(days=3):
        return "expiring_soon"
    if item.quantity <= 5:
        return "low_stock"
    return "in_stock"


def recommendation_for(
    item: InventoryItem, today: date | None = None
) -> RuleBasedRecommendation:
    today = today or date.today()
    days_to_expiry = (item.expiry_date - today).days
    basis = (
        "Rule-based estimate using stock, expiry date, and user-entered daily demand."
    )

    if item.quantity == 0:
        return RuleBasedRecommendation(
            item_id=item.id,
            product_name=item.product_name,
            quantity=0,
            days_to_expiry=days_to_expiry,
            rule_based_risk_score=0,
            risk_level="Low",
            likely_to_expire_unsold=False,
            quantity_at_risk=0,
            recommended_discount_pct=0,
            estimated_surplus_units=0,
            basis="No stock is available to discount.",
        )

    if days_to_expiry < 0:
        return RuleBasedRecommendation(
            item_id=item.id,
            product_name=item.product_name,
            quantity=item.quantity,
            days_to_expiry=days_to_expiry,
            rule_based_risk_score=100,
            risk_level="High",
            likely_to_expire_unsold=True,
            quantity_at_risk=float(item.quantity),
            recommended_discount_pct=None,
            estimated_surplus_units=None,
            basis="Expired stock must not be discounted for sale.",
        )

    urgency_score = max(0, round((7 - days_to_expiry) / 7 * 35))
    if item.estimated_daily_demand is None:
        return RuleBasedRecommendation(
            item_id=item.id,
            product_name=item.product_name,
            quantity=item.quantity,
            days_to_expiry=days_to_expiry,
            rule_based_risk_score=min(100, urgency_score),
            risk_level=risk_level_for(min(100, urgency_score)),
            likely_to_expire_unsold=None,
            quantity_at_risk=None,
            recommended_discount_pct=None,
            estimated_surplus_units=None,
            basis="Enter expected daily demand to estimate surplus or a discount.",
        )

    expected_demand = item.estimated_daily_demand * days_to_expiry
    estimated_surplus = max(0.0, item.quantity - expected_demand)
    surplus_score = estimated_surplus / item.quantity * 65
    risk_score = min(100, round(surplus_score + urgency_score))
    discount = (
        0
        if risk_score < 25
        else 10
        if risk_score < 45
        else 20
        if risk_score < 65
        else 30
        if risk_score < 85
        else 40
    )

    return RuleBasedRecommendation(
        item_id=item.id,
        product_name=item.product_name,
        quantity=item.quantity,
        days_to_expiry=days_to_expiry,
        rule_based_risk_score=risk_score,
        risk_level=risk_level_for(risk_score),
        likely_to_expire_unsold=estimated_surplus > 0,
        quantity_at_risk=round(estimated_surplus, 1),
        recommended_discount_pct=discount,
        estimated_surplus_units=round(estimated_surplus, 1),
        basis=(
            f"{basis} Estimated demand before expiry is "
            f"{expected_demand:.1f} units, leaving "
            f"{estimated_surplus:.1f} units at risk. The {discount}% tier is "
            "based on the rule score, not measured price elasticity or margin."
        ),
    )
