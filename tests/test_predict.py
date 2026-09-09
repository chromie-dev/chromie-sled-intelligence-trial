"""Offline tests for the likely-bidder baseline. No network."""
import datetime as dt
import unittest

from sled_trial import predict


def award(sid="V1", name="ALPHA SUPPLY INC", dept="Department of Justice",
          category="IT Goods", date="01/15/2026", amt="$10,000.00",
          method="Formal - COMPETITIVE", cert=None, lpa=None, doc="D1"):
    return {"supplier_id": sid, "supplier_name": name, "department": dept,
            "category": category, "start_date": date, "awarded_amt": amt,
            "acq_method": method, "cert_type": cert, "lpa_contract": lpa,
            "purchase_doc": doc}


OPP = {"department": "Department of Justice", "category": "IT Goods",
       "amount": 12000.0, "event_ref": "2740/TEST"}


class LeakageTests(unittest.TestCase):
    def test_awards_on_or_after_the_cutoff_are_excluded(self) -> None:
        corpus = [award(date="01/15/2026"), award(date="06/01/2026", doc="FUTURE")]
        out = predict.rank_candidates(corpus, OPP, cutoff="03/01/2026")
        self.assertEqual(out["rows_excluded_as_future"], 1)
        self.assertEqual(out["predictions"][0]["evidence_counts"]["awards_before_cutoff"], 1)

    def test_a_vendor_known_only_after_the_cutoff_is_not_ranked(self) -> None:
        corpus = [award(sid="LATE", date="09/01/2026")]
        out = predict.rank_candidates(corpus, OPP, cutoff="03/01/2026")
        self.assertEqual(out["predictions"], [])

    def test_cutoff_accepts_both_date_formats(self) -> None:
        corpus = [award(date="01/15/2026")]
        for cutoff in ("03/01/2026", "2026-03-01"):
            with self.subTest(cutoff=cutoff):
                out = predict.rank_candidates(corpus, OPP, cutoff=cutoff)
                self.assertEqual(out["cutoff"], "2026-03-01")


class EligibilityGateTests(unittest.TestCase):
    def test_certification_alone_cannot_produce_a_prediction(self) -> None:
        # README forbids treating a certification as proof a vendor will bid.
        opp = {**OPP, "required_certifications": ["DVBE"]}
        corpus = [award(sid="CERTONLY", dept="Other Agency", category="Other",
                        cert="DVBE", amt=None, method=None)]
        out = predict.rank_candidates(corpus, opp, cutoff="06/01/2026")
        ranked = {p["supplier_id"] for p in out["predictions"]}
        self.assertNotIn("CERTONLY", ranked)

    def test_certification_amplifies_real_participation(self) -> None:
        opp = {**OPP, "required_certifications": ["DVBE"]}
        with_cert = predict.features_for_vendor(
            [award(cert="DVBE"), award(cert="DVBE", doc="D2")], opp, dt.date(2026, 6, 1))
        without = predict.features_for_vendor(
            [award(cert=None), award(cert=None, doc="D2")], opp, dt.date(2026, 6, 1))
        self.assertGreater(with_cert["score"], without["score"])

    def test_vehicle_presence_is_also_gated_on_history(self) -> None:
        opp = {**OPP, "vehicle": "1-22-70-31C"}
        f = predict.features_for_vendor(
            [award(dept="Elsewhere", category="Elsewhere", lpa="1-22-70-31C")],
            opp, dt.date(2026, 6, 1))
        self.assertEqual(f["feature_contributions"]["vehicle_presence"], 0.0)


class ExplainabilityTests(unittest.TestCase):
    def test_contributions_sum_to_the_score(self) -> None:
        f = predict.features_for_vendor([award(), award(doc="D2")], OPP, dt.date(2026, 6, 1))
        self.assertAlmostEqual(sum(f["feature_contributions"].values()), f["score"], places=3)

    def test_every_weighted_feature_is_reported(self) -> None:
        f = predict.features_for_vendor([award()], OPP, dt.date(2026, 6, 1))
        self.assertEqual(set(f["feature_contributions"]), set(predict.WEIGHTS))

    def test_weakening_factors_are_returned_alongside_support(self) -> None:
        f = predict.features_for_vendor(
            [award(dept="Elsewhere", category="Elsewhere", method=None, amt="$1.00")],
            OPP, dt.date(2026, 6, 1))
        self.assertIn("no prior award with this agency", f["weakening_factors"])
        self.assertIn("no competitively awarded history observed", f["weakening_factors"])

    def test_stale_history_is_flagged_and_scores_lower(self) -> None:
        fresh = predict.features_for_vendor([award(date="05/01/2026")], OPP, dt.date(2026, 6, 1))
        stale = predict.features_for_vendor([award(date="01/01/2020")], OPP, dt.date(2026, 6, 1))
        self.assertGreater(fresh["score"], stale["score"])
        self.assertIn("last observed award is stale", stale["weakening_factors"])

    def test_predictions_are_labelled_predicted_not_observed(self) -> None:
        out = predict.rank_candidates([award()], OPP, cutoff="06/01/2026")
        self.assertEqual(out["predictions"][0]["evidence_class"], "predicted")
        self.assertIn("never confirmed bidders", out["note"])


class EntityFilterTests(unittest.TestCase):
    def test_counties_and_departments_are_not_ranked_as_competitors(self) -> None:
        corpus = [award(sid="0000004178", name="CALAVERAS COUNTY"),
                  award(sid="DEPT542000", name="CA CORRECTIONAL TRNG REHAB AUTH"),
                  award(sid="V1", name="ALPHA SUPPLY INC")]
        out = predict.rank_candidates(corpus, OPP, cutoff="06/01/2026")
        ranked = {p["supplier_id"] for p in out["predictions"]}
        self.assertEqual(ranked, {"V1"})
        self.assertEqual(len(out["excluded_non_competitor_entities"]), 2)

    def test_exclusions_state_a_reason(self) -> None:
        out = predict.rank_candidates(
            [award(sid="0000004178", name="CALAVERAS COUNTY")], OPP, cutoff="06/01/2026")
        self.assertTrue(all(e["reason"] for e in out["excluded_non_competitor_entities"]))

    def test_ordinary_company_names_are_not_over_filtered(self) -> None:
        for name in ["GRANITE DATA SOLUTIONS", "WW GRAINGER INC", "AVIATE ENTERPRISES INC"]:
            with self.subTest(name=name):
                self.assertTrue(predict.is_biddable_entity("0000000001", name)[0])


class ObservedParticipantTests(unittest.TestCase):
    def test_observed_vendor_is_excluded_from_ranking_and_reported(self) -> None:
        # An observed participant is evidence, not a prediction; ranking it would flatter
        # the precision metrics.
        out = predict.rank_candidates([award(sid="V1")], OPP, cutoff="06/01/2026",
                                      observed_vendor_ids=["V1"])
        self.assertEqual(out["predictions"], [])
        self.assertEqual(out["observed_participants_excluded_from_ranking"], ["V1"])


class MetricTests(unittest.TestCase):
    def test_precision_and_coverage(self) -> None:
        self.assertEqual(predict.precision_at_k(["a", "b", "c"], ["b"], 3), round(1 / 3, 4))
        self.assertEqual(predict.coverage(["a", "b"], ["b", "z"]), 0.5)

    def test_no_ground_truth_returns_none_not_zero(self) -> None:
        # "We could not tell" must never be recorded as "the model was wrong".
        self.assertIsNone(predict.precision_at_k(["a"], [], 3))
        self.assertIsNone(predict.coverage(["a"], []))

    def test_empty_predictions_with_real_truth_is_zero(self) -> None:
        self.assertEqual(predict.precision_at_k([], ["a"], 3), 0.0)

    def test_short_prediction_list_is_divided_by_k_not_its_own_length(self) -> None:
        # One correct prediction out of one returned is precision@3 of 1/3, not 1.0.
        # Dividing by len(top) flattered the model against baselines, which always
        # return a full list.
        self.assertEqual(predict.precision_at_k(["a"], ["a"], 3), round(1 / 3, 4))
        self.assertEqual(predict.precision_at_k(["a", "b"], ["a", "b"], 5), 0.4)

    def test_evaluate_separates_unusable_events(self) -> None:
        results = [
            {"predictions": [{"supplier_id": "a"}], "actual_participant_ids": ["a"],
             "opportunity": {"event_ref": "E1"}},
            {"predictions": [{"supplier_id": "b"}], "actual_participant_ids": [],
             "opportunity": {"event_ref": "E2"}},
        ]
        out = predict.evaluate(results)
        self.assertEqual(out["events_evaluated"], 1)
        self.assertEqual(out["events_without_ground_truth"], 1)
        self.assertEqual(out["precision_at_3"], round(1 / 3, 4))


class HoldoutTests(unittest.TestCase):
    def test_split_holds_out_the_cutoff_day_and_keeps_every_pair(self) -> None:
        # Selecting only the pairs with the deepest history picks the most predictable
        # events; that bias is what produced the discarded 0.17 figure.
        awards = [award(sid="V1", date="09/01/2026"),
                  award(sid="V2", date="09/03/2026"),
                  award(sid="V3", date="09/03/2026", category="IT Services")]
        history, events = predict.holdout_events(awards, cutoff="09/03/2026")
        self.assertEqual(len(history), 1)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["actual_participant_ids"] for e in events))


if __name__ == "__main__":
    unittest.main()


class RelevanceGateTests(unittest.TestCase):
    """A vendor with no award at this agency and none in this category is not ranked.

    The first implementation scored recency over a vendor's whole history, so any vendor
    that sold anything to anyone recently appeared as a likely bidder.
    """

    def test_irrelevant_history_produces_no_prediction(self) -> None:
        corpus = [award(sid="ELSEWHERE", dept="Other Agency", category="Other",
                        date="05/01/2026")]
        out = predict.rank_candidates(corpus, OPP, cutoff="06/01/2026")
        self.assertEqual(out["predictions"], [])
        self.assertEqual(out["excluded_no_relevant_history"], 1)

    def test_same_agency_alone_is_relevant(self) -> None:
        corpus = [award(sid="AG", dept=OPP["department"], category="Other")]
        out = predict.rank_candidates(corpus, OPP, cutoff="06/01/2026")
        self.assertEqual([p["supplier_id"] for p in out["predictions"]], ["AG"])

    def test_same_category_alone_is_relevant(self) -> None:
        corpus = [award(sid="CAT", dept="Other Agency", category=OPP["category"])]
        out = predict.rank_candidates(corpus, OPP, cutoff="06/01/2026")
        self.assertEqual([p["supplier_id"] for p in out["predictions"]], ["CAT"])

    def test_recency_measured_on_relevant_history_only(self) -> None:
        # Fresh irrelevant activity must not make stale relevant activity look current.
        f = predict.features_for_vendor(
            [award(dept=OPP["department"], date="01/01/2021"),
             award(dept="Other Agency", category="Other", date="05/01/2026", doc="D2")],
            OPP, dt.date(2026, 6, 1))
        self.assertIn("last observed award is stale", f["weakening_factors"])

    def test_relevant_count_is_reported(self) -> None:
        f = predict.features_for_vendor(
            [award(), award(doc="D2"), award(dept="X", category="Y", doc="D3")],
            OPP, dt.date(2026, 6, 1))
        self.assertEqual(f["evidence_counts"]["awards_before_cutoff"], 3)
        self.assertEqual(f["evidence_counts"]["relevant_awards_before_cutoff"], 2)


class BaselineComparisonTests(unittest.TestCase):
    """A precision number without a baseline cannot be judged as good or bad."""

    def _events(self):
        return [{"opportunity": {"department": OPP["department"],
                                 "category": OPP["category"], "amount": None},
                 "actual_participant_ids": ["V1"]}]

    def test_every_baseline_is_scored_alongside_the_model(self) -> None:
        history = [award(sid="V1", doc="D1"), award(sid="V1", doc="D2"),
                   award(sid="V2", name="OTHER CO", doc="D3")]
        out = predict.compare_to_baselines(history, self._events(), cutoff="06/01/2026")
        self.assertEqual(set(out["results"]), set(predict.BASELINES) | {"model"})
        for name, scores in out["results"].items():
            with self.subTest(name=name):
                self.assertIn("precision_at_3", scores)

    def test_lift_is_reported_against_the_best_baseline(self) -> None:
        history = [award(sid="V1", doc=f"D{i}") for i in range(5)]
        out = predict.compare_to_baselines(history, self._events(), cutoff="06/01/2026")
        self.assertIsNotNone(out["model_precision_at_3"])
        self.assertIsNotNone(out["best_baseline_precision_at_3"])

    def test_baselines_exclude_government_sellers_too(self) -> None:
        # Otherwise the comparison would be unfair in the model's favour.
        history = [award(sid="0000004178", name="CALAVERAS COUNTY", doc=f"D{i}")
                   for i in range(9)]
        for name, fn in predict.BASELINES.items():
            with self.subTest(name=name):
                self.assertNotIn("0000004178", fn(history, OPP))

    def test_popularity_baseline_ignores_the_opportunity(self) -> None:
        history = [award(sid="BUSY", dept="Elsewhere", category="Elsewhere", doc=f"D{i}")
                   for i in range(9)]
        ranked = predict.BASELINES["most_awards_overall"](history, OPP)
        self.assertEqual(ranked[0], "BUSY")
        # ...whereas the model refuses to rank a vendor with no relevant history at all.
        out = predict.rank_candidates(history, OPP, cutoff="06/01/2026")
        self.assertEqual(out["predictions"], [])

    def test_interpretation_states_why_absolute_precision_is_low(self) -> None:
        out = predict.compare_to_baselines([award()], self._events(), cutoff="06/01/2026")
        self.assertIn("not which firms bid on a solicitation", out["interpretation"])


class CorpusProvenanceTests(unittest.TestCase):
    """How a corpus was built is declared, not inferred.

    Two heuristics were tried and discarded first: award-count skew (a national supplier
    legitimately held 36 awards against a median of 1 on a uniform window) and per-vendor
    date coverage (a short sweep gives nearly every vendor a zero-day span, leaving the
    statistic with no baseline). Assembly method is known at assembly time, so it is
    recorded rather than guessed.
    """

    def test_a_sweep_is_rankable_even_with_skewed_counts(self) -> None:
        corpus = [award(sid="BUSY", date=f"09/0{d}/2026", doc=f"B{d}{i}")
                  for d in range(1, 7) for i in range(6)]
        corpus += [award(sid=f"V{i}", date="09/03/2026", doc=f"V{i}") for i in range(50)]
        out = predict.describe_corpus(corpus, build_method=predict.SWEEP)
        self.assertTrue(out["rankable"])
        self.assertGreater(out["awards_per_vendor_max"], 20)

    def test_a_mixed_corpus_is_not_rankable(self) -> None:
        out = predict.describe_corpus([award()], build_method=predict.MIXED)
        self.assertFalse(out["rankable"])
        self.assertIn("which vendors were fetched", out["reason"])

    def test_uniform_per_vendor_backfill_is_rankable(self) -> None:
        # Legitimate for the prime task, whose eligible set is defined by relevance.
        out = predict.describe_corpus([award()], build_method=predict.PER_VENDOR)
        self.assertTrue(out["rankable"])
        self.assertIn("uniform within the set that can qualify", out["reason"])

    def test_an_unrecognised_method_is_named_rather_than_silently_accepted(self) -> None:
        out = predict.describe_corpus([award()], build_method="improvised")
        self.assertIn("unrecognised build method", out["reason"])

    def test_descriptive_statistics_are_reported(self) -> None:
        corpus = [award(sid="A", date="09/01/2026", doc="1"),
                  award(sid="A", date="09/03/2026", doc="2")]
        out = predict.describe_corpus(corpus)
        self.assertEqual(out["observation_span_days_max"], 2)
        self.assertEqual(out["awards_total"], 2)

    def test_guidance_names_the_remedy(self) -> None:
        out = predict.describe_corpus([award()])
        self.assertIn("never an arbitrary subset", out["guidance"])

    def test_counts_are_explicitly_not_the_signal(self) -> None:
        self.assertIn("award-count skew is not evidence",
                      predict.describe_corpus([award()])["note"])

    def test_empty_corpus_is_safe(self) -> None:
        out = predict.describe_corpus([])
        self.assertEqual(out["vendors"], 0)
        self.assertTrue(out["rankable"])

    def test_rows_without_a_supplier_id_are_ignored(self) -> None:
        self.assertEqual(
            predict.describe_corpus([award(sid=""), award(sid="V1")])["vendors"], 1)
