"""
Tests for the categorisation service.

Covers:
- Tier 1: TrueLayer classification → user-facing category mapping
- Tier 2: Description-based keyword matching (primary for real UK banks)
- Most-specific-first resolution (reversed list)
- Unknown classifications → fallback to DEFAULT_CATEGORY
- Empty / None inputs
"""

from app.services.categorisation import (
    CATEGORY_MAP,
    CLASSIFICATION_MAP,
    DEFAULT_CATEGORY,
    categorise_transaction,
)


class TestTier1Classification:
    """Tests for TrueLayer classification array matching."""

    def test_single_known_classification(self):
        assert categorise_transaction(["Groceries"]) == "Groceries"

    def test_eating_out_variants(self):
        assert categorise_transaction(["Restaurants"]) == "Eating Out"
        assert categorise_transaction(["Takeaways"]) == "Eating Out"
        assert categorise_transaction(["Eating Out"]) == "Eating Out"

    def test_transport_variants(self):
        assert categorise_transaction(["Public Transport"]) == "Transport"
        assert categorise_transaction(["Taxi"]) == "Transport"
        assert categorise_transaction(["Fuel"]) == "Transport"

    def test_bills_and_subscriptions(self):
        assert categorise_transaction(["Bills"]) == "Bills & Subscriptions"
        assert categorise_transaction(["Utilities"]) == "Bills & Subscriptions"
        assert categorise_transaction(["Subscriptions"]) == "Bills & Subscriptions"
        assert categorise_transaction(["Insurance"]) == "Bills & Subscriptions"

    def test_income(self):
        assert categorise_transaction(["Salary"]) == "Salary & Income"
        assert categorise_transaction(["Income"]) == "Salary & Income"
        assert categorise_transaction(["Wages"]) == "Salary & Income"

    def test_transfers(self):
        assert categorise_transaction(["Transfers"]) == "Transfers"
        assert categorise_transaction(["Bank Transfer"]) == "Transfers"

    def test_cash_and_atm(self):
        assert categorise_transaction(["ATM"]) == "Cash & ATM"
        assert categorise_transaction(["Cash"]) == "Cash & ATM"

    def test_entertainment(self):
        assert categorise_transaction(["Entertainment"]) == "Entertainment"
        assert categorise_transaction(["Leisure"]) == "Entertainment"

    def test_health_and_fitness(self):
        assert categorise_transaction(["Health"]) == "Health & Fitness"
        assert categorise_transaction(["Fitness"]) == "Health & Fitness"
        assert categorise_transaction(["Personal Care"]) == "Health & Fitness"

    def test_shopping(self):
        assert categorise_transaction(["Shopping"]) == "Shopping"
        assert categorise_transaction(["Clothing"]) == "Shopping"
        assert categorise_transaction(["Electronics"]) == "Shopping"

    def test_hierarchical_most_specific_wins(self):
        assert categorise_transaction(["Shopping", "Groceries"]) == "Groceries"

    def test_hierarchical_with_unknown_specific(self):
        assert categorise_transaction(["Shopping", "SomeUnknownSubcategory"]) == "Shopping"

    def test_hierarchical_all_unknown(self):
        assert categorise_transaction(["Unknown1", "Unknown2"]) == DEFAULT_CATEGORY

    def test_empty_classification_returns_default(self):
        assert categorise_transaction([]) == DEFAULT_CATEGORY

    def test_none_classification_returns_default(self):
        assert categorise_transaction(None) == DEFAULT_CATEGORY

    def test_unknown_classification_returns_default(self):
        assert categorise_transaction(["CryptoInvestment"]) == DEFAULT_CATEGORY

    def test_classification_takes_priority_over_description(self):
        """Tier 1 (classification) should win over Tier 2 (description)."""
        result = categorise_transaction(
            ["Groceries"],
            description="NETFLIX SUBSCRIPTION",
        )
        assert result == "Groceries"

    def test_all_map_entries_are_reachable(self):
        for tl_label, expected_category in CLASSIFICATION_MAP.items():
            result = categorise_transaction([tl_label])
            assert result == expected_category, (
                f"CLASSIFICATION_MAP[{tl_label!r}] = {expected_category!r}, "
                f"but categorise_transaction returned {result!r}"
            )

    def test_category_map_alias_exists(self):
        """CATEGORY_MAP is a backwards-compatible alias for CLASSIFICATION_MAP."""
        assert CATEGORY_MAP is CLASSIFICATION_MAP


class TestTier2DescriptionMatching:
    """Tests for description-based keyword matching (real UK bank data)."""

    # ── Groceries ─────────────────────────────────────────────────────────

    def test_tesco(self):
        assert categorise_transaction(
            None, description="TESCO STORES 2345 (VIA APPLE PAY), ON 10-03-2026"
        ) == "Groceries"

    def test_sainsburys(self):
        assert categorise_transaction(
            None, description="SAINSBURYS S/MKTS"
        ) == "Groceries"

    def test_aldi(self):
        assert categorise_transaction(
            None, description="ALDI STORES LTD, ON 05-03-2026"
        ) == "Groceries"

    def test_lidl(self):
        assert categorise_transaction(
            None, description="LIDL GB CARDIFF"
        ) == "Groceries"

    def test_coop(self):
        assert categorise_transaction(
            None, description="CO-OP GROUP FOOD"
        ) == "Groceries"

    # ── Eating Out ────────────────────────────────────────────────────────

    def test_mcdonalds(self):
        assert categorise_transaction(
            None, description="MCDONALDS 1234"
        ) == "Eating Out"

    def test_greggs(self):
        assert categorise_transaction(
            None, description="GREGGS PLC"
        ) == "Eating Out"

    def test_deliveroo(self):
        assert categorise_transaction(
            None, description="DELIVEROO.COM"
        ) == "Eating Out"

    def test_brewhouse_and_kitchen(self):
        assert categorise_transaction(
            None, description="BREWHOUSE & KITCHEN (VIA APPLE PAY), ON 01-01-2026"
        ) == "Eating Out"

    def test_bru_coffee(self):
        assert categorise_transaction(
            None, description="BRU COFFEE - QUEEN ST (VIA APPLE PAY), ON 19-03-2026"
        ) == "Eating Out"

    def test_chopstix(self):
        assert categorise_transaction(
            None, description="CHOPSTIX O2 (VIA APPLE PAY), ON 27-02-2026"
        ) == "Eating Out"

    def test_kfc_in_reference(self):
        assert categorise_transaction(
            None,
            description="BILL PAYMENT VIA FASTER PAYMENT TO LEE ROGERS REFERENCE MONDAY KFC , MANDATE NO 0027",
        ) == "Transfers"  # "BILL PAYMENT" matches Transfers first

    # ── Transport ─────────────────────────────────────────────────────────

    def test_tfl(self):
        assert categorise_transaction(
            None, description="TFL.GOV.UK/CP"
        ) == "Transport"

    def test_uber_not_eats(self):
        assert categorise_transaction(
            None, description="UBER *TRIP HELP.UBER.COM"
        ) == "Transport"

    def test_petrol_in_reference(self):
        assert categorise_transaction(
            None,
            description="BILL PAYMENT VIA FASTER PAYMENT TO ELLEN OCALLAGHAN REFERENCE PETROL MONEY , MANDATE NO 0026",
        ) == "Transfers"  # "BILL PAYMENT" matches Transfers first

    # ── Bills & Subscriptions ─────────────────────────────────────────────

    def test_netflix(self):
        assert categorise_transaction(
            None, description="NETFLIX.COM 866-579-7172"
        ) == "Bills & Subscriptions"

    def test_spotify(self):
        assert categorise_transaction(
            None, description="SPOTIFY P1234567"
        ) == "Bills & Subscriptions"

    def test_apple_bill(self):
        assert categorise_transaction(
            None, description="APPLE.COM/BILL (VIA APPLE PAY), ON 10-03-2026"
        ) == "Bills & Subscriptions"

    def test_amazon_prime(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO AMAZON PRIME*7254G7MU5 ON 21-03-2026"
        ) == "Bills & Subscriptions"

    def test_direct_debit(self):
        assert categorise_transaction(
            None, description="DIRECT DEBIT PAYMENT - SKY UK LIMITED"
        ) == "Bills & Subscriptions"

    def test_leisure_centre(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO WWW.LEISURECENTRE.LEGE ON 14-01-2026"
        ) == "Bills & Subscriptions"

    # ── Salary & Income ───────────────────────────────────────────────────

    def test_salary(self):
        assert categorise_transaction(
            None, description="ACME LTD SALARY"
        ) == "Salary & Income"

    def test_hmrc_refund(self):
        assert categorise_transaction(
            None, description="HMRC TAX REFUND"
        ) == "Salary & Income"

    # ── Transfers ─────────────────────────────────────────────────────────

    def test_bill_payment_to(self):
        assert categorise_transaction(
            None,
            description="BILL PAYMENT TO MEGAN RATCLIFFE REFERENCE AIRBNB, MANDATE NO00032",
        ) == "Transfers"

    def test_bill_payment_from(self):
        assert categorise_transaction(
            None,
            description="BILL PAYMENT FROM MISS MEGAN OLIVIA RATCLIFFE, REFERENCE HAMNET",
        ) == "Transfers"

    def test_faster_payment(self):
        assert categorise_transaction(
            None,
            description="BILL PAYMENT VIA FASTER PAYMENT TO MEG DARREN JOINT REFERENCE TEST , MANDATE NO 0034",
        ) == "Transfers"

    # ── Cash & ATM ────────────────────────────────────────────────────────

    def test_atm_withdrawal(self):
        assert categorise_transaction(
            None, description="ATM WITHDRAWAL - BARCLAYS BANK"
        ) == "Cash & ATM"

    def test_cash_withdrawal(self):
        assert categorise_transaction(
            None, description="CASH WITHDRAWAL"
        ) == "Cash & ATM"

    # ── Shopping ──────────────────────────────────────────────────────────

    def test_amazon_marketplace(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO AMAZON MKTPL*6G01A0ZS3 ON 04-02-2026"
        ) == "Shopping"

    def test_amznmktplace(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO AMZNMKTPLACE*0E65E1Z95 ON 08-03-2026"
        ) == "Shopping"

    def test_amazon_co_uk(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO AMAZON.CO.UK*5V58D0UB5 ON 25-01-2026"
        ) == "Shopping"

    def test_boots(self):
        assert categorise_transaction(
            None, description="BOOTS 0323 (VIA APPLE PAY), ON 03-03-2026"
        ) == "Shopping"

    def test_apple_store(self):
        assert categorise_transaction(
            None, description="APPLE.COM/UK (VIA APPLE PAY), ON 02-01-2026"
        ) == "Shopping"

    def test_crwys_electrics(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO CRWYS ELECTRICS ON 17-02-2026"
        ) == "Shopping"

    # ── Entertainment ─────────────────────────────────────────────────────

    def test_ticketmaster(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO TM *TICKETMASTERUK ON 13-02-2026"
        ) == "Entertainment"

    def test_tickets_with_ref(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO TICKETS 126305373 ON 26-03-2026"
        ) == "Entertainment"

    def test_steam_games(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO STEAMGAMES.COM 4259522 ON 02-01-2026"
        ) == "Entertainment"

    def test_cardiff_rugby(self):
        assert categorise_transaction(
            None, description="CARDIFF RUGBY (VIA APPLE PAY), ON 24-01-2026"
        ) == "Entertainment"

    # ── Health & Fitness ──────────────────────────────────────────────────

    def test_bluecrest_wellness(self):
        assert categorise_transaction(
            None, description="BLUECREST WELLNESS (VIA APPLE PAY), ON 21-03-2026"
        ) == "Health & Fitness"

    # ── Travel & Holidays ─────────────────────────────────────────────────

    def test_travelodge(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO TRAVELODG TRAVELODGE G ON 08-02-2026"
        ) == "Travel & Holidays"

    def test_luggage_storage(self):
        assert categorise_transaction(
            None, description="CARD PAYMENT TO LUGGAGE STORAGE KINGSX ON 26-03-2026"
        ) == "Travel & Holidays"

    # ── Fallback ──────────────────────────────────────────────────────────

    def test_no_classification_no_description(self):
        assert categorise_transaction(None) == DEFAULT_CATEGORY

    def test_empty_description(self):
        assert categorise_transaction(None, description="") == DEFAULT_CATEGORY

    def test_unrecognised_description(self):
        assert categorise_transaction(
            None, description="RANDOM VENDOR 12345"
        ) == DEFAULT_CATEGORY

    def test_description_used_when_classification_empty(self):
        """Empty classification falls through to description matching."""
        assert categorise_transaction(
            [], description="TESCO STORES 2345"
        ) == "Groceries"

    def test_merchant_name_param_accepted_but_unused(self):
        """merchant_name parameter is accepted for API compatibility."""
        result = categorise_transaction(
            None, merchant_name="Tesco", description="TESCO STORES"
        )
        assert result == "Groceries"
