"""
Transaction categorisation — maps transactions to user-facing categories.

Three-tier approach (highest priority first):
  1. TrueLayer `transaction_classification` array (when available)
  2. Description-based keyword matching (primary method for real UK banks)
  3. Default fallback to "General"

Real UK bank feeds rarely populate TrueLayer's classification array.
The description field is the primary categorisation signal, containing
merchant names and payment references in formats like:
  - "TESCO STORES (VIA APPLE PAY), ON 10-03-2026"
  - "CARD PAYMENT TO AMAZON MKTPL*6G01A0ZS3 ON 04-02-2026"
  - "BILL PAYMENT VIA FASTER PAYMENT TO NAME REFERENCE REASON"
  - "DIRECT DEBIT PAYMENT - NETFLIX"
"""

import re

# ---------------------------------------------------------------------------
# Tier 1: TrueLayer classification → user-facing category
# ---------------------------------------------------------------------------

CLASSIFICATION_MAP: dict[str, str] = {
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

# Backwards-compatible alias so existing imports still work.
CATEGORY_MAP = CLASSIFICATION_MAP

# ---------------------------------------------------------------------------
# Tier 2: Description keyword rules
# ---------------------------------------------------------------------------
# Each rule is (compiled_regex, category). First match wins.
# Patterns are tested against the UPPER-CASED description.
# Order matters — more specific rules should come before general ones.

_DESCRIPTION_RULES: list[tuple[re.Pattern[str], str]] = []


def _rule(pattern: str, category: str) -> None:
    """Register a case-insensitive description matching rule."""
    _DESCRIPTION_RULES.append((re.compile(pattern, re.IGNORECASE), category))


# ── Payment-type structural rules (highest priority) ─────────────────────
# These must come first because they identify the *type* of payment, which
# takes precedence over merchant keywords that may appear in the reference
# text.  E.g. "BILL PAYMENT VIA FASTER PAYMENT TO LEE ROGERS REFERENCE
# MONDAY KFC" is a person-to-person transfer, NOT an Eating Out purchase.
_rule(r"\bBILL PAYMENT VIA FASTER PAYMENT\b", "Transfers")
_rule(r"\bBILL PAYMENT FROM\b", "Transfers")
_rule(r"\bFASTER PAYMENT (?:TO|FROM)\b", "Transfers")
_rule(r"\bBANK TRANSFER\b", "Transfers")
_rule(r"\bINTERNAL TRANSFER\b", "Transfers")

# ── Groceries ─────────────────────────────────────────────────────────────
_rule(r"\bTESCO\b", "Groceries")
_rule(r"\bSAINSBURY", "Groceries")
_rule(r"\bASDA\b", "Groceries")
_rule(r"\bMORRISON", "Groceries")
_rule(r"\bALDI\b", "Groceries")
_rule(r"\bLIDL\b", "Groceries")
_rule(r"\bWAITROSE", "Groceries")
_rule(r"\bCO-OP\b", "Groceries")
_rule(r"\bCOOP\b", "Groceries")
_rule(r"\bM&S FOOD", "Groceries")
_rule(r"\bM &S\b", "Groceries")
_rule(r"\bICELAND\b", "Groceries")
_rule(r"\bOCADO\b", "Groceries")
_rule(r"\bFARMFOODS", "Groceries")
_rule(r"\bHERON FOODS", "Groceries")
_rule(r"\bJACK'?S\b", "Groceries")
_rule(r"\bBOOTH'?S\b", "Groceries")
_rule(r"\bSPAR\b", "Groceries")

# ── Eating Out ────────────────────────────────────────────────────────────
_rule(r"\bMCDONALD", "Eating Out")
_rule(r"\bBURGER KING", "Eating Out")
_rule(r"\bKFC\b", "Eating Out")
_rule(r"\bSUBWAY\b", "Eating Out")
_rule(r"\bGREGGS\b", "Eating Out")
_rule(r"\bCOSTA\b", "Eating Out")
_rule(r"\bSTARBUCKS", "Eating Out")
_rule(r"\bCAFFE NERO", "Eating Out")
_rule(r"\bPRET A MANGER", "Eating Out")
_rule(r"\bNANDO", "Eating Out")
_rule(r"\bDOMINO", "Eating Out")
_rule(r"\bPIZZA", "Eating Out")
_rule(r"\bJUST ?EAT", "Eating Out")
_rule(r"\bDELIVEROO", "Eating Out")
_rule(r"\bUBER ?EATS", "Eating Out")
_rule(r"\bWAGAMAMA", "Eating Out")
_rule(r"\bZIZZI\b", "Eating Out")
_rule(r"\bFIVE GUYS", "Eating Out")
_rule(r"\bLEON\b", "Eating Out")
_rule(r"\bITSU\b", "Eating Out")
_rule(r"\bTIM HORTONS", "Eating Out")
_rule(r"\bBREWHOUSE", "Eating Out")
_rule(r"\bCHOPSTIX", "Eating Out")
_rule(r"\bBRU COFFEE", "Eating Out")
_rule(r"\bCOFFEE", "Eating Out")
_rule(r"\bCAFE\b", "Eating Out")
_rule(r"\bRESTAURANT", "Eating Out")
_rule(r"\bBISTRO", "Eating Out")
_rule(r"\bKITCHEN\b", "Eating Out")
_rule(r"\bCHIPPY\b", "Eating Out")
_rule(r"\bFISH\s*(AND|&)\s*CHIP", "Eating Out")
_rule(r"\bWETHERSPOON", "Eating Out")
_rule(r"\bPUB\b", "Eating Out")

# ── Transport ─────────────────────────────────────────────────────────────
_rule(r"\bTFL\b", "Transport")
_rule(r"\bTRANSPORT FOR LONDON", "Transport")
_rule(r"\bUBER\b(?!\s*EAT)", "Transport")  # Uber but not Uber Eats
_rule(r"\bBOLT\b", "Transport")
_rule(r"\bTRAINLINE", "Transport")
_rule(r"\bNATIONAL RAIL", "Transport")
_rule(r"\bGWR\b", "Transport")
_rule(r"\bAVANTI", "Transport")
_rule(r"\bLNER\b", "Transport")
_rule(r"\bNORTHERN RAIL", "Transport")
_rule(r"\bSCOTRAIL", "Transport")
_rule(r"\bARRIVA\b", "Transport")
_rule(r"\bSTAGECOACH", "Transport")
_rule(r"\bFIRST BUS", "Transport")
_rule(r"\bBP\b.*\bFUEL", "Transport")
_rule(r"\bSHELL\b", "Transport")
_rule(r"\bESSO\b", "Transport")
_rule(r"\bJET\b.*\bPETROL", "Transport")
_rule(r"\bPETROL\b", "Transport")
_rule(r"\bFUEL\b", "Transport")
_rule(r"\bPARKING\b", "Transport")
_rule(r"\bNCP\b", "Transport")
_rule(r"\bRINGGO", "Transport")
_rule(r"\bDVLA\b", "Transport")
_rule(r"\bCONGESTION", "Transport")
_rule(r"\bDART ?CHARGE", "Transport")

# ── Bills & Subscriptions ─────────────────────────────────────────────────
_rule(r"\bNETFLIX", "Bills & Subscriptions")
_rule(r"\bSPOTIFY", "Bills & Subscriptions")
_rule(r"\bDISNEY\s*\+", "Bills & Subscriptions")
_rule(r"\bAMAZON PRIME", "Bills & Subscriptions")
_rule(r"\bAPPLE\.COM/BILL", "Bills & Subscriptions")
_rule(r"\bYOUTUBE", "Bills & Subscriptions")
_rule(r"\bNOW ?TV", "Bills & Subscriptions")
_rule(r"\bSKY\b", "Bills & Subscriptions")
_rule(r"\bBT\b.*\b(BROADBAND|GROUP|SPORT)", "Bills & Subscriptions")
_rule(r"\bVIRGIN\s*MEDIA", "Bills & Subscriptions")
_rule(r"\bVODAFONE", "Bills & Subscriptions")
_rule(r"\bTHREE\b.*\bMOBILE", "Bills & Subscriptions")
_rule(r"\bEE\b.*\b(MOBILE|LTD)", "Bills & Subscriptions")
_rule(r"\bO2\b.*\b(MOBILE|UK)", "Bills & Subscriptions")
_rule(r"\bGIFFGAFF", "Bills & Subscriptions")
_rule(r"\bTALKTALK", "Bills & Subscriptions")
_rule(r"\bPLUSNET", "Bills & Subscriptions")
_rule(r"\bCOUNCIL TAX", "Bills & Subscriptions")
_rule(r"\bWATER\b.*\b(PLUS|UTIL|SERV|BILL)", "Bills & Subscriptions")
_rule(r"\bBRITISH GAS", "Bills & Subscriptions")
_rule(r"\bOCTOPUS ENERGY", "Bills & Subscriptions")
_rule(r"\bOVO ENERGY", "Bills & Subscriptions")
_rule(r"\bE\.?ON\b", "Bills & Subscriptions")
_rule(r"\bEDF\b", "Bills & Subscriptions")
_rule(r"\bBULB\b", "Bills & Subscriptions")
_rule(r"\bSCOTTISH POWER", "Bills & Subscriptions")
_rule(r"\bSSE\b", "Bills & Subscriptions")
_rule(r"\bTV LICEN[CS]", "Bills & Subscriptions")
_rule(r"\bDIRECT DEBIT", "Bills & Subscriptions")
_rule(r"\bSTANDING ORDER", "Bills & Subscriptions")
_rule(r"\bGYM\b", "Bills & Subscriptions")
_rule(r"\bPURE ?GYM", "Bills & Subscriptions")
_rule(r"\bTHE ?GYM\b", "Bills & Subscriptions")
_rule(r"\bDAVID LLOYD", "Bills & Subscriptions")
_rule(r"\bLEISURE\s*CENTRE", "Bills & Subscriptions")

# ── Salary & Income ───────────────────────────────────────────────────────
_rule(r"\bSALARY\b", "Salary & Income")
_rule(r"\bWAGES?\b", "Salary & Income")
_rule(r"\bPAYROLL\b", "Salary & Income")
_rule(r"\bHMRC\b.*\b(TAX|REFUND|P800)", "Salary & Income")
_rule(r"\bTAX\s*REFUND", "Salary & Income")
_rule(r"\bDIVIDEND", "Salary & Income")

# ── Transfers (catch-all — structural patterns already handled above) ─────
_rule(r"\bBILL PAYMENT (TO|FROM)\b", "Transfers")  # e.g. "BILL PAYMENT TO ..."
_rule(r"\bSTANDING ORDER", "Transfers")  # also matches Bills above — first match wins

# ── Cash & ATM ────────────────────────────────────────────────────────────
_rule(r"\bATM\b", "Cash & ATM")
_rule(r"\bCASH\s*WITHDRAWAL", "Cash & ATM")
_rule(r"\bCASH\s*MACHINE", "Cash & ATM")
_rule(r"\bCASHPOINT", "Cash & ATM")

# ── Shopping ──────────────────────────────────────────────────────────────
_rule(r"\bAMAZON\b", "Shopping")  # After Amazon Prime (subscriptions)
_rule(r"\bAMZNMKTPLACE", "Shopping")
_rule(r"\bEBAY\b", "Shopping")
_rule(r"\bARGOS\b", "Shopping")
_rule(r"\bCURRYS\b", "Shopping")
_rule(r"\bJOHN LEWIS", "Shopping")
_rule(r"\bNEXT\b.*\b(RETAIL|ONLINE|PLC)", "Shopping")
_rule(r"\bPRIMARK", "Shopping")
_rule(r"\bTK\s*MAXX", "Shopping")
_rule(r"\bH\s*&\s*M\b", "Shopping")
_rule(r"\bZARA\b", "Shopping")
_rule(r"\bASOS\b", "Shopping")
_rule(r"\bBOOHOO", "Shopping")
_rule(r"\bIKEA\b", "Shopping")
_rule(r"\bB\s*&\s*Q\b", "Shopping")
_rule(r"\bSCREWFIX", "Shopping")
_rule(r"\bWILKO", "Shopping")
_rule(r"\bHOME\s*BARGAINS", "Shopping")
_rule(r"\bPOUND", "Shopping")
_rule(r"\bBOOTS\b", "Shopping")
_rule(r"\bSUPERDRUG", "Shopping")
_rule(r"\bWH\s*SMITH", "Shopping")
_rule(r"\bAPPLE\.COM/UK", "Shopping")  # Apple Store purchases (not /BILL)
_rule(r"\bAPPLE\s*STORE", "Shopping")
_rule(r"\bELECTRIC", "Shopping")  # e.g. "CRWYS ELECTRICS"

# ── Entertainment ─────────────────────────────────────────────────────────
_rule(r"\bCINEMA\b", "Entertainment")
_rule(r"\bODEON\b", "Entertainment")
_rule(r"\bCINEWORLD", "Entertainment")
_rule(r"\bVUE\b.*\bCINEMA", "Entertainment")
_rule(r"\bTICKETMASTER", "Entertainment")
_rule(r"\bTICKETS?\b.*\d{6,}", "Entertainment")  # "TICKETS 126305373"
_rule(r"\bSTEAMGAMES", "Entertainment")
_rule(r"\bPLAYSTATION", "Entertainment")
_rule(r"\bXBOX\b", "Entertainment")
_rule(r"\bNINTENDO", "Entertainment")
_rule(r"\bRUGBY\b", "Entertainment")
_rule(r"\bFOOTBALL\b", "Entertainment")
_rule(r"\bCRICKET\b", "Entertainment")

# ── Health & Fitness ──────────────────────────────────────────────────────
_rule(r"\bBOOTS\b.*\bPHARMA", "Health & Fitness")
_rule(r"\bPHARMACY", "Health & Fitness")
_rule(r"\bDENTIST", "Health & Fitness")
_rule(r"\bOPTICIAN", "Health & Fitness")
_rule(r"\bSPECSAVER", "Health & Fitness")
_rule(r"\bBLUECREST", "Health & Fitness")
_rule(r"\bWELLNESS", "Health & Fitness")
_rule(r"\bFITNESS", "Health & Fitness")

# ── Travel & Holidays ────────────────────────────────────────────────────
_rule(r"\bAIRBNB", "Travel & Holidays")
_rule(r"\bBOOKING\.COM", "Travel & Holidays")
_rule(r"\bHOTEL", "Travel & Holidays")
_rule(r"\bTRAVELODG", "Travel & Holidays")
_rule(r"\bPREMIER INN", "Travel & Holidays")
_rule(r"\bRYANAIR", "Travel & Holidays")
_rule(r"\bEASYJET", "Travel & Holidays")
_rule(r"\bBRITISH AIRWAYS", "Travel & Holidays")
_rule(r"\bJET2\b", "Travel & Holidays")
_rule(r"\bTUI\b", "Travel & Holidays")
_rule(r"\bLUGGAGE", "Travel & Holidays")
_rule(r"\bTRAVEL\s*LODGE", "Travel & Holidays")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_CATEGORY = "General"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def categorise_transaction(
    truelayer_classification: list[str] | None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> str:
    """
    Determine the user-facing category for a transaction.

    Resolution order:
      1. TrueLayer classification array (most specific → least specific)
      2. Description keyword matching (primary method for real UK banks)
      3. Default: "General"

    Returns one of the categories defined in SPEC.md §3.2.
    """
    # Tier 1: TrueLayer classification (when providers populate it)
    if truelayer_classification:
        for label in reversed(truelayer_classification):
            if label in CLASSIFICATION_MAP:
                return CLASSIFICATION_MAP[label]

    # Tier 2: Description-based keyword matching
    if description:
        for pattern, category in _DESCRIPTION_RULES:
            if pattern.search(description):
                return category

    return DEFAULT_CATEGORY
