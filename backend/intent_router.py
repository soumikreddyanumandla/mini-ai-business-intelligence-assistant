"""
Intent Router Module
--------------------
Provides a robust, deterministic rule-and-pattern based intent classifier
that acts as:
1. The primary intent router in offline / test / demonstration mode.
2. The reliable fallback safety net whenever external LLM APIs fail or time out.

Implements the four-category taxonomy:
- Category 1: Supported business questions (mapped to approved tools)
- Category 2: Related but unsupported business questions (profit, cost, churn, inventory)
- Category 3: Ambiguous questions requiring parameter clarification
- Category 4: Unrelated questions outside the sales analytics domain.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from backend.schemas import QuestionCategory, IntentInterpretation

# ----------------------------------------------------------------------
# Keywords and Regex Patterns
# ----------------------------------------------------------------------

# Category 4: Unrelated domains
UNRELATED_PATTERNS = [
    r"\b(prime minister|president|capital of|who is|weather|recipe|cook|poem|joke|song|movie|football|cricket|fifa|olympics)\b",
    r"\b(quantum|gravity|einstein|biology|philosophy|history of|translate|write code|python script to download)\b",
]

# Category 2: Related but unsupported business concepts
UNSUPPORTED_BUSINESS_PATTERNS = [
    (r"\b(profit|margin|net profit|gross margin|ebitda)\b", "The supplied sales dataset contains sales transactions and discount amounts, but lacks product cost or operational expenditure data. Therefore, profit margins cannot be calculated. You can analyze realized net revenue, discounts, or top-performing products instead."),
    (r"\b(churn|retention|customer lifetime|cac|clv|ltv)\b", "The dataset does not track individual customer identities or subscriptions over time, so churn and customer retention rates cannot be determined. You can review overall order volume or regional sales trends instead."),
    (r"\b(inventory|stock|warehouse|reorder|supplier)\b", "The dataset records sales transactions rather than inventory levels or warehouse balances. You can examine units sold per product to see demand trends."),
    (r"\b(ad spend|marketing spend|roas|campaign)\b", "Marketing expenditure is not captured in this dataset. You can compare sales performance across Online and Retail channels instead."),
]

# Month name mapping for parameter extraction
MONTH_NAMES = {
    "january": "2026-01", "jan": "2026-01",
    "february": "2026-02", "feb": "2026-02",
    "march": "2026-03", "mar": "2026-03",
    "april": "2026-04", "apr": "2026-04",
    "may": "2026-05",
    "june": "2026-06", "jun": "2026-06",
    "july": "2026-07", "jul": "2026-07",
    "august": "2026-08", "aug": "2026-08",
    "september": "2026-09", "sep": "2026-09",
    "october": "2026-10", "oct": "2026-10",
    "november": "2026-11", "nov": "2026-11",
    "december": "2026-12", "dec": "2026-12",
}

KNOWN_PRODUCTS = ["laptop stand", "wireless mouse", "office chair", "monitor", "keyboard", "desk", "usb-c hub"]


def extract_months_from_text(text: str) -> List[str]:
    """Extracts month tokens in the exact order they appear in the query."""
    matches = []
    # 1. ISO matches (YYYY-MM or YYYY/MM)
    for m in re.finditer(r"\b(202\d[-/](?:0[1-9]|1[0-2]))\b", text, re.IGNORECASE):
        norm = m.group(1).replace("/", "-")
        matches.append((m.start(), norm))

    # 2. Named months
    lowered = text.lower()
    for name, iso in MONTH_NAMES.items():
        for m in re.finditer(rf"\b{name}\b", lowered):
            matches.append((m.start(), iso))

    # Sort matches chronologically by character position in sentence
    matches.sort(key=lambda x: x[0])

    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for pos, iso in matches:
        if iso not in seen:
            seen.add(iso)
            ordered.append(iso)
    return ordered


def extract_products_from_text(text: str) -> List[str]:
    """Finds known product names mentioned in text."""
    lowered = text.lower()
    found = []
    for p in KNOWN_PRODUCTS:
        if p in lowered:
            found.append(p.title())
    return found


def fallback_classify_intent(query: str) -> IntentInterpretation:
    """
    Classifies user question into one of the 4 categories and extracts parameters deterministically.
    """
    clean = query.strip()
    lowered = clean.lower()

    if not clean:
        return IntentInterpretation(
            intent="empty_query",
            category=QuestionCategory.AMBIGUOUS,
            needs_clarification=True,
            clarification_prompt="Please ask a question about your sales data.",
            confidence=1.0,
        )

    # 1. Check Category 4: Unrelated Queries
    for pat in UNRELATED_PATTERNS:
        if re.search(pat, lowered, re.IGNORECASE):
            return IntentInterpretation(
                intent="unrelated_query",
                category=QuestionCategory.UNRELATED,
                confidence=0.95,
                needs_clarification=False,
                clarification_prompt="I am a Business Intelligence Assistant designed to analyze your sales data. I can help with revenue, product performance, regional analysis and other sales-related questions.",
                suggested_alternatives=[
                    "What is the total revenue?",
                    "Which product generated the highest revenue?",
                    "What is the monthly revenue trend?",
                    "Which region generated the highest revenue?",
                ],
            )

    # 2. Check Category 2: Related but Unsupported Business Questions
    for pat, explanation in UNSUPPORTED_BUSINESS_PATTERNS:
        if re.search(pat, lowered, re.IGNORECASE):
            return IntentInterpretation(
                intent="unsupported_business_metric",
                category=QuestionCategory.RELATED_UNSUPPORTED,
                confidence=0.95,
                unsupported_reason=explanation,
                suggested_alternatives=[
                    "What is our total net sales revenue?",
                    "Show category-wise revenue contribution.",
                    "Compare Online vs Retail sales channels.",
                    "What is our average order value?",
                ],
            )

    # 3. Check Category 3: Ambiguity in Comparison
    is_comparison_word = any(w in lowered for w in ["compare", "comparison", "difference between", "versus", "vs", "change between", "growth between"])
    months = extract_months_from_text(lowered)
    products = extract_products_from_text(lowered)

    if is_comparison_word:
        # Check if comparing channels
        if "channel" in lowered:
            return IntentInterpretation(
                intent="channel_comparison",
                category=QuestionCategory.SUPPORTED,
                confidence=0.95,
            )

        # Check if comparing across regions
        if "region" in lowered:
            return IntentInterpretation(
                intent="top_revenue_region",
                category=QuestionCategory.SUPPORTED,
                parameters={"limit": 10},
                confidence=0.95,
            )

        # Check if comparing specific regions
        found_regions = [r.title() for r in ["north", "south", "east", "west"] if re.search(rf"\b{r}\b", lowered)]
        if len(found_regions) >= 2:
            return IntentInterpretation(
                intent="compare_regions",
                category=QuestionCategory.SUPPORTED,
                parameters={"region_1": found_regions[0], "region_2": found_regions[1]},
                confidence=0.95,
            )

        # Check if comparing products
        if len(products) >= 2:
            return IntentInterpretation(
                intent="product_comparison",
                category=QuestionCategory.SUPPORTED,
                parameters={"product_1": products[0], "product_2": products[1]},
                confidence=0.9,
            )
        # Check if comparing months
        if len(months) >= 2:
            return IntentInterpretation(
                intent="monthly_comparison",
                category=QuestionCategory.SUPPORTED,
                parameters={"month_1": months[0], "month_2": months[1]},
                confidence=0.95,
            )
        elif len(months) == 1:
            return IntentInterpretation(
                intent="monthly_comparison",
                category=QuestionCategory.AMBIGUOUS,
                needs_clarification=True,
                clarification_prompt=f"You specified {months[0]}. Which second month would you like to compare it with? (e.g., February 2026)",
                parameters={"month_1": months[0]},
                confidence=0.85,
            )
        else:
            # Comparison word but no months or products specified!
            return IntentInterpretation(
                intent="ambiguous_comparison",
                category=QuestionCategory.AMBIGUOUS,
                needs_clarification=True,
                clarification_prompt="Which two months would you like me to compare? (For example: 'Compare January and February')",
                confidence=0.85,
            )

    # 4. Check Mandatory Five Questions
    # Check Region-specific queries first to prevent generic keyword misrouting
    if ("region" in lowered or "territory" in lowered or "regional" in lowered):
        if any(w in lowered for w in ["highest", "sales", "revenue", "best", "top", "rank", "compare", "perform"]):
            return IntentInterpretation(
                intent="top_revenue_region",
                category=QuestionCategory.SUPPORTED,
                parameters={"limit": 1},
                confidence=0.95,
            )

    # Check Product-specific queries
    is_product_phrase = any(k in lowered for k in ["product", "item", "selling", "goods"])
    is_revenue_phrase = any(k in lowered for k in ["revenue", "money", "sales", "made the most", "rank", "highest", "top"])
    if (is_product_phrase and is_revenue_phrase) and not any(w in lowered for w in ["quantity", "units", "volume"]):
        return IntentInterpretation(
            intent="top_revenue_product",
            category=QuestionCategory.SUPPORTED,
            parameters={"limit": 1},
            confidence=0.95,
        )

    # Check Lowest Revenue/Quantity Product
    if any(w in lowered for w in ["lowest", "least", "worst"]) and any(k in lowered for k in ["product", "selling", "item", "revenue", "quantity"]):
        if any(v in lowered for v in ["quantity", "units", "volume"]):
            return IntentInterpretation(
                intent="lowest_quantity_product",
                category=QuestionCategory.SUPPORTED,
                confidence=0.95,
            )
        return IntentInterpretation(
            intent="lowest_performing_product",
            category=QuestionCategory.SUPPORTED,
            confidence=0.95,
        )

    # Check Monthly Trend
    if any(p in lowered for p in [
        "monthly revenue trend", "revenue month by month", "monthly trend", "month by month",
        "which month performed best", "best performing month", "revenue by month", "sales by month",
        "monthly sales trend", "its monthly trend", "its trend"
    ]):
        params = {}
        for r in ["north", "south", "east", "west"]:
            if re.search(rf"\b{r}\b", lowered):
                params["region"] = r.title()
                break
        if not params and products:
            params["product"] = products[0]

        return IntentInterpretation(
            intent="monthly_revenue_trend",
            category=QuestionCategory.SUPPORTED,
            parameters=params,
            confidence=0.95,
        )

    # Check Total Revenue
    if any(p in lowered for p in [
        "total revenue", "net sales", "total sales", "how much money did we earn",
        "how much money did we make", "overall sales", "total net revenue", "overall revenue",
        "calculate our total net sales", "calculate overall sales", "how much revenue"
    ]):
        return IntentInterpretation(
            intent="total_revenue",
            category=QuestionCategory.SUPPORTED,
            confidence=0.95,
        )

    # E. Month to Month Comparison with explicit mention (e.g. "did sales increase in June compared with May?")
    if len(months) >= 2 and any(w in lowered for w in ["increase", "decrease", "change", "diff", "between"]):
        return IntentInterpretation(
            intent="monthly_comparison",
            category=QuestionCategory.SUPPORTED,
            parameters={"month_1": months[0], "month_2": months[1]},
            confidence=0.95,
        )

    # 5. Additional Approved Tools
    if any(p in lowered for p in ["highest quantity", "most units", "most popular by volume", "sold the highest quantity", "highest volume"]):
        return IntentInterpretation(intent="top_quantity_product", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["lowest quantity", "least units", "least sold", "lowest volume"]):
        return IntentInterpretation(intent="lowest_quantity_product", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["category", "categories", "category-wise", "category revenue"]):
        return IntentInterpretation(intent="category_revenue", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["channel", "channels", "online vs retail", "sales channel", "retail vs online"]):
        return IntentInterpretation(intent="channel_comparison", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["average transaction", "average order", "aov", "average spending", "order value"]):
        return IntentInterpretation(intent="average_transaction_value", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["discount", "discounts", "discount amount", "discount rate"]):
        return IntentInterpretation(intent="discount_analysis", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["status", "returned vs completed", "orders returned", "order status"]):
        return IntentInterpretation(intent="status_breakdown", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in ["top 5", "top five"]):
        return IntentInterpretation(intent="top_5_products", category=QuestionCategory.SUPPORTED, confidence=0.9)

    if any(p in lowered for p in [
        "data quality", "data-quality", "cleanliness", "data issue", "data issues",
        "quality issue", "quality issues", "excluded record", "excluded records",
        "what records were excluded", "data audit", "audit issues"
    ]):
        return IntentInterpretation(intent="data_quality_audit", category=QuestionCategory.SUPPORTED, confidence=0.95)

    # Phase 2 – Package B Tools
    if any(p in lowered for p in ["anomaly", "anomalies", "outlier", "outliers", "unusual transaction", "irregular sales"]):
        return IntentInterpretation(intent="anomaly_detection", category=QuestionCategory.SUPPORTED, confidence=0.95)

    if any(p in lowered for p in ["pareto", "80/20", "80-20", "revenue concentration", "vital few", "80% of revenue"]):
        return IntentInterpretation(intent="revenue_concentration", category=QuestionCategory.SUPPORTED, confidence=0.95)

    if any(p in lowered for p in ["what if", "what-if", "simulate", "scenario", "price elasticity"]):
        params = {}
        pct_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", clean)
        if pct_match:
            pct_val = float(pct_match.group(1))
            if "price" in lowered:
                params["price_change_pct"] = pct_val
            elif "volume" in lowered or "unit" in lowered or "quantity" in lowered:
                params["volume_change_pct"] = pct_val
            elif "discount" in lowered:
                params["discount_adjustment_pct"] = pct_val
        return IntentInterpretation(intent="what_if_simulation", category=QuestionCategory.SUPPORTED, parameters=params, confidence=0.95)

    if any(p in lowered for p in ["quota", "pacing", "sales target", "target pacing", "quota pacing", "run-rate"]):
        params = {}
        target_num = re.search(r"\b(\d{4,9})\b", clean)
        if target_num:
            params["monthly_target"] = float(target_num.group(1))
        return IntentInterpretation(intent="quota_pacing", category=QuestionCategory.SUPPORTED, parameters=params, confidence=0.95)

    # 6. Fallback if general sales query
    if any(w in lowered for w in ["revenue", "sales", "money", "earn"]):
        return IntentInterpretation(
            intent="total_revenue",
            category=QuestionCategory.SUPPORTED,
            confidence=0.7,
        )

    # Otherwise ambiguous question
    return IntentInterpretation(
        intent="unclear_question",
        category=QuestionCategory.AMBIGUOUS,
        needs_clarification=True,
        clarification_prompt="I couldn't quite understand your query. Could you please rephrase or choose one of the suggested sales questions?",
        suggested_alternatives=[
            "What is the total revenue?",
            "Which product generated the highest revenue?",
            "What is the monthly revenue trend?",
            "Which region generated the highest revenue?",
            "Compare January and February.",
        ],
        confidence=0.5,
    )
