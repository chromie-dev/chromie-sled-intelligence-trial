"""Offline tests for prime-contractor recommendations. No network."""
import datetime as dt
import unittest

from sled_trial import predict, primes


def award(sid="P1", name="BIG SERVICES INC", dept="CAL FIRE", category="NON-IT Services",
          date="01/15/2026", amt="$500,000.00", method="Formal - COMPETITIVE",
          cert=None, lpa=None, doc="D1"):
    return {"supplier_id": sid, "supplier_name": name, "department": dept,
            "category": category, "start_date": date, "awarded_amt": amt,
            "acq_method": method, "cert_type": cert, "lpa_contract": lpa,
            "purchase_doc": doc}


OPP = {"department": "CAL FIRE", "category": "NON-IT Services", "amount": 600000.0}
CLIENT = {"categories": ["IT Services"], "certifications": ["DVBE"]}
CUTOFF = dt.date(2026, 6, 1)


class QualificationTests(unittest.TestCase):
    def test_a_vendor_with_only_tiny_orders_is_not_a_prime(self) -> None:
        # Reach is not credibility: 50 small commodity orders do not qualify a company to
        # prime a 600k services contract.
        history = [award(amt="$120.00", doc=f"D{i}") for i in range(50)]
        self.assertIsNone(
            primes.assess_prime("P1", "SMALL CO", history, OPP, CLIENT, CUTOFF))

    def test_two_comparable_awards_qualify(self) -> None:
        history = [award(doc="D1"), award(doc="D2")]
        got = primes.assess_prime("P1", "BIG SERVICES INC", history, OPP, CLIENT, CUTOFF)
        self.assertIsNotNone(got)
        self.assertEqual(got["credibility_case"]["awards_at_or_above_value_floor"], 2)

    def test_one_comparable_award_is_not_enough(self) -> None:
        history = [award(doc="D1"), award(amt="$50.00", doc="D2")]
        self.assertIsNone(
            primes.assess_prime("P1", "BIG SERVICES INC", history, OPP, CLIENT, CUTOFF))

    def test_government_sellers_are_never_primes(self) -> None:
        history = [award(sid="0000004178", name="CALAVERAS COUNTY", doc=f"D{i}")
                   for i in range(5)]
        self.assertIsNone(primes.assess_prime(
            "0000004178", "CALAVERAS COUNTY", history, OPP, CLIENT, CUTOFF))

    def test_unqualified_vendors_are_omitted_from_the_ranked_list(self) -> None:
        corpus = ([award(sid="BIG", doc="A1"), award(sid="BIG", doc="A2")]
                  + [award(sid="TINY", name="TINY CO", amt="$10.00", doc=f"T{i}")
                     for i in range(20)])
        out = primes.recommend_primes(corpus, OPP, CLIENT, cutoff="06/01/2026")
        self.assertEqual([c["supplier_id"] for c in out["prime_candidates"]], ["BIG"])


class BothCasesTests(unittest.TestCase):
    def test_credibility_case_is_counted_evidence(self) -> None:
        got = primes.assess_prime(
            "P1", "BIG SERVICES INC", [award(doc="D1"), award(doc="D2")],
            OPP, CLIENT, CUTOFF)
        case = got["credibility_case"]
        self.assertEqual(case["awards_with_this_agency"], 2)
        self.assertEqual(case["awards_in_this_category"], 2)
        self.assertIsNotNone(case["median_award_above_floor"])
        self.assertIn("evidences acting as a prime", case["basis"])

    def test_teaming_case_names_the_client_scope_gap(self) -> None:
        # The client sells IT Services; this prime has no IT Services record.
        got = primes.assess_prime(
            "P1", "BIG SERVICES INC", [award(doc="D1"), award(doc="D2")],
            OPP, CLIENT, CUTOFF)
        self.assertIn("IT Services", got["teaming_case"]["client_scope_gap_filled"])
        self.assertTrue(got["teaming_case"]["sufficient"])

    def test_required_certification_the_client_holds_is_called_out(self) -> None:
        opp = {**OPP, "required_certifications": ["DVBE"]}
        got = primes.assess_prime(
            "P1", "BIG SERVICES INC", [award(doc="D1"), award(doc="D2")],
            opp, CLIENT, CUTOFF)
        self.assertTrue(any("DVBE" in r for r in got["teaming_case"]["reasons"]))

    def test_willingness_to_team_is_never_claimed(self) -> None:
        got = primes.assess_prime(
            "P1", "BIG SERVICES INC", [award(doc="D1"), award(doc="D2")],
            OPP, CLIENT, CUTOFF)
        self.assertIn("willingness to team is not observable", got["note"])
        self.assertEqual(got["evidence_class"], "derived")

    def test_no_relevance_is_now_a_hard_disqualification(self) -> None:
        # Previously this returned a candidate carrying a soft disqualifier. Reading real
        # output showed such candidates reaching the ranked list, so it is now exclusion.
        history = [award(dept="Elsewhere", category="Elsewhere", doc="D1"),
                   award(dept="Elsewhere", category="Elsewhere", doc="D2")]
        self.assertIsNone(
            primes.assess_prime("P1", "OTHER CO", history, OPP, CLIENT, CUTOFF))

    def test_soft_disqualifiers_are_still_reported_on_qualifying_candidates(self) -> None:
        # Relevant scope, but the vendor has not been active recently.
        history = [award(date="01/01/2020", doc="D1"), award(date="01/02/2020", doc="D2")]
        got = primes.assess_prime("P1", "STALE CO", history, OPP, CLIENT, CUTOFF)
        self.assertIsNotNone(got)
        self.assertTrue(got["disqualifiers"])

    def test_stale_prime_is_flagged(self) -> None:
        history = [award(date="01/01/2020", doc="D1"), award(date="01/02/2020", doc="D2")]
        got = primes.assess_prime("P1", "STALE CO", history, OPP, CLIENT, CUTOFF)
        self.assertIn("no observed award in the last two years", got["disqualifiers"])


class DualRoleTests(unittest.TestCase):
    def test_a_likely_competitor_that_is_also_a_prime_is_flagged(self) -> None:
        # README asks for exactly this case to be identified rather than hidden.
        corpus = [award(sid="BOTH", doc="D1"), award(sid="BOTH", doc="D2")]
        out = primes.recommend_primes(corpus, OPP, CLIENT, cutoff="06/01/2026",
                                      likely_bidder_ids=["BOTH"])
        candidate = out["prime_candidates"][0]
        self.assertTrue(candidate["also_likely_competitor"])
        self.assertIn("approaching a competitor", candidate["dual_role_note"])
        self.assertEqual(out["dual_role_candidates"], ["BOTH"])

    def test_non_competitor_prime_is_not_flagged(self) -> None:
        corpus = [award(sid="ONLYPRIME", doc="D1"), award(sid="ONLYPRIME", doc="D2")]
        out = primes.recommend_primes(corpus, OPP, CLIENT, cutoff="06/01/2026",
                                      likely_bidder_ids=["SOMEONE_ELSE"])
        self.assertFalse(out["prime_candidates"][0]["also_likely_competitor"])
        self.assertEqual(out["dual_role_candidates"], [])


class LeakageTests(unittest.TestCase):
    def test_awards_after_the_cutoff_are_ignored(self) -> None:
        corpus = [award(doc="D1"), award(doc="D2"), award(date="09/01/2026", doc="FUTURE")]
        out = primes.recommend_primes(corpus, OPP, CLIENT, cutoff="06/01/2026")
        self.assertEqual(
            out["prime_candidates"][0]["evidence"]["awards_considered"], 2)

    def test_qualification_rule_is_published_in_the_output(self) -> None:
        # A reader must be able to see the bar without reading the source.
        out = primes.recommend_primes([award(doc="D1"), award(doc="D2")], OPP, CLIENT,
                                      cutoff="06/01/2026")
        rule = out["qualification_rule"]
        self.assertIn("at or above one decade below", rule)
        self.assertIn("agency or in this category", rule)


if __name__ == "__main__":
    unittest.main()


class ComparableValueTests(unittest.TestCase):
    """Both rules below were tightened after reading real output."""

    def test_a_vendor_an_order_of_magnitude_too_small_does_not_qualify(self) -> None:
        # At the previous 1.5-decade tolerance a $38,870 top award qualified a vendor to
        # prime a $437,862 contract.
        history = [award(amt="$38,870.00", doc="D1"), award(amt="$20,000.00", doc="D2")]
        self.assertIsNone(primes.assess_prime(
            "P1", "SMALLISH CO", history, {**OPP, "amount": 437862.48}, CLIENT, CUTOFF))

    def test_a_vendor_within_a_decade_qualifies(self) -> None:
        history = [award(amt="$80,000.00", doc="D1"), award(amt="$90,000.00", doc="D2")]
        got = primes.assess_prime("P1", "MID CO", history,
                                  {**OPP, "amount": 437862.48}, CLIENT, CUTOFF)
        self.assertIsNotNone(got)

    def test_no_agency_and_no_category_history_disqualifies(self) -> None:
        history = [award(dept="Elsewhere", category="Elsewhere", doc="D1"),
                   award(dept="Elsewhere", category="Elsewhere", doc="D2")]
        self.assertIsNone(
            primes.assess_prime("P1", "OTHER CO", history, OPP, CLIENT, CUTOFF))

    def test_category_relevance_alone_is_enough(self) -> None:
        history = [award(dept="Elsewhere", doc="D1"), award(dept="Elsewhere", doc="D2")]
        self.assertIsNotNone(
            primes.assess_prime("P1", "SCOPE CO", history, OPP, CLIENT, CUTOFF))

    def test_ratio_to_opportunity_value_is_reported(self) -> None:
        got = primes.assess_prime("P1", "BIG SERVICES INC",
                                  [award(doc="D1"), award(doc="D2")], OPP, CLIENT, CUTOFF)
        self.assertIsNotNone(got["credibility_case"]["largest_award_to_opportunity_ratio"])
        self.assertEqual(got["credibility_case"]["opportunity_value"], OPP["amount"])


class CorpusProvenanceTests(unittest.TestCase):
    def test_output_declares_how_its_corpus_was_built_and_who_could_qualify(self) -> None:
        # The report has branches for all three, and analyze shipped an empty prime list
        # with no way for a reader to tell the corpus was the reason.
        out = primes.recommend_primes(
            [award(sid="V1"), award(sid="V1", doc="D2")], OPP, CLIENT,
            cutoff="09/03/2026", build_method=predict.PER_VENDOR)
        self.assertEqual(out["corpus_provenance"]["build_method"], predict.PER_VENDOR)
        self.assertEqual(out["corpus_provenance"]["eligible_vendor_count"], 1)
        self.assertIn("why_this_corpus", out["corpus_provenance"])
        self.assertTrue(out["qualification_note"])

    def test_ineligible_corpus_says_so_instead_of_implying_a_market_finding(self) -> None:
        out = primes.recommend_primes(
            [award(sid="V9", dept="Elsewhere", category="Other")], OPP, CLIENT,
            cutoff="09/03/2026")
        self.assertEqual(out["corpus_provenance"]["eligible_vendor_count"], 0)
        self.assertIn("corpus limit", out["qualification_note"])
