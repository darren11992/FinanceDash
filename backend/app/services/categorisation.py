"""
Transaction categorisation — maps TrueLayer classification to user-facing categories.

TrueLayer provides a `transaction_classification` array on each transaction.
This module maps those values to our simplified category set defined in SPEC.md §3.2.

Sprint 3: Full implementation with merchant-name fallback heuristics.
"""

# TrueLayer classification → our user-facing category
CATEGORY_MAP: dict[str, str] = {
    # TrueLayer uses hierarchical categories like ["Shopping", "Groceries"]
    "Groceries": "Groceries",
    "Food & Groceries": "Groceries",
    "Eating Out": "Eating Out",
    "Restaurants": "Eating Out",
    "Takeaways": "Eating Out",
    "Transport": "Transport",
    "Public Transport": "Transport",
    "Taxi": "Transport",
    "Fuel": "Transport",
    "Shopping": "Shopping",
    "Clothing": "Shopping",
    "Electronics": "Shopping",
    "Bills": "Bills & Subscriptions",
    "Utilities": "Bills & Subscriptions",
    "Subscriptions": "Bills & Subscriptions",
    "Insurance": "Bills & Subscriptions",
    "Income": "Salary & Income",
    "Salary": "Salary & Income",
    "Wages": "Salary & Income",
    "Transfers": "Transfers",
    "Bank Transfer": "Transfers",
    "ATM": "Cash & ATM",
    "Cash": "Cash & ATM",
    "Entertainment": "Entertainment",
    "Leisure": "Entertainment",
    "Health": "Health & Fitness",
    "Fitness": "Health & Fitness",
    "Personal Care": "Health & Fitness",
}

DEFAULT_CATEGORY = "General"


def categorise_transaction(
    truelayer_classification: list[str] | None,
    merchant_name: str | None = None,
) -> str:
    """
    Determine the user-facing category for a transaction.

    Checks TrueLayer's classification array first (most specific → least),
    then falls back to DEFAULT_CATEGORY.

    Returns one of the categories defined in SPEC.md §3.2.
    """
    if truelayer_classification:
        # Walk from most specific to least specific
        for label in reversed(truelayer_classification):
            if label in CATEGORY_MAP:
                return CATEGORY_MAP[label]

    return DEFAULT_CATEGORY
