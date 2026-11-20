import tempfile
import unittest
from pathlib import Path

from community_feedback.analysis import run_analysis
from community_feedback.feedback import build_case_views
from community_feedback.loading import load_dataset
from community_feedback.metrics import aggregate
from community_feedback.periods import UNASSIGNED_PERIOD

from tests.helpers import minimal_periods, write_fixtures


def _case(cid, grid="G1", service="维修", closed="2026-06-02", outcome="completed"):
    return {"id": cid, "grid": grid, "service": service,
            "closed_at": closed, "outcome": outcome}


def _inv(iid, case, channel="phone", eligible="yes", delivered="yes", sent="2026-06-03"):
    return {"id": iid, "case": case, "channel": channel,
            "eligible": eligible, "delivered": delivered, "sent_at": sent}


def _resp(vid, inv, respondent, score, received="2026-06-04", supersedes=""):
    return {"id": vid, "invitation": inv, "respondent": respondent,
            "score": score, "received_at": received, "supersedes": supersedes}


class FunnelAndMetricsTests(unittest.TestCase):
    def test_three_layer_denominators_and_unknown_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    _case("C1"),  # 符合+送达+评价
                    _case("C2", closed="2026-06-03"),  # 符合+未送达
                    _case("C3", closed="2026-06-04"),  # 符合+送达+未评价（未知）
                    _case("C4", closed="2026-06-05", outcome="open"),  # 未纳入邀请
                ],
                invitations=[
                    _inv("I1", "C1"),
                    _inv("I2", "C2", delivered="no"),
                    _inv("I3", "C3"),
                    _inv("I4", "C4", eligible="no", delivered="no"),
                ],
                responses=[_resp("V1", "I1", "U1", 5)],
                periods=minimal_periods(),
            )
            dataset, _ = load_dataset(fixtures)
            views, _ = build_case_views(dataset)
            groups = aggregate(views, "overall", dataset.periods)
            funnel = groups[0].funnel
            self.assertEqual(funnel.cases, 4)
            self.assertEqual(funnel.eligible, 3)
            self.assertEqual(funnel.delivered, 2)
            self.assertEqual(funnel.responded, 1)
            self.assertEqual(funnel.unknown, 1)       # C3：送达未评价
            self.assertEqual(funnel.not_invited, 1)   # C4
            self.assertAlmostEqual(funnel.delivery_rate, 2 / 3, places=4)
            self.assertAlmostEqual(funnel.response_rate_eligible, 1 / 3, places=4)
            self.assertEqual(funnel.response_rate_delivered, 0.5)
            self.assertEqual(funnel.coverage_rate, 0.25)

    def test_rating_distribution_excludes_unknown_and_uses_current_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[_case("C1"), _case("C2", closed="2026-06-03"),
                       _case("C3", closed="2026-06-04")],
                invitations=[_inv("I1", "C1"), _inv("I2", "C2"), _inv("I3", "C3")],
                responses=[
                    _resp("V1", "I1", "U1", 2),
                    _resp("V2", "I1", "U1", 5, supersedes="V1"),  # 更正后 5
                    _resp("V3", "I2", "U2", 1),
                    # C3 无评价
                ],
                periods=minimal_periods(),
            )
            dataset, _ = load_dataset(fixtures)
            views, _ = build_case_views(dataset)
            rating = aggregate(views, "overall", dataset.periods)[0].rating
            self.assertEqual(rating.rated_cases, 2)
            self.assertEqual(rating.mean, 3.0)  # (5+1)/2，V1 的 2 分已作废
            self.assertEqual(rating.distribution, {1: 1, 2: 0, 3: 0, 4: 0, 5: 1})
            self.assertEqual(rating.negative, 1)
            self.assertEqual(rating.positive, 1)

    def test_fulfillment_is_independent_of_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    _case("C1", outcome="completed"),
                    _case("C2", outcome="referred", closed="2026-06-03"),
                    _case("C3", outcome="open", closed=""),
                ],
                invitations=[_inv("I1", "C1")],
                responses=[_resp("V1", "I1", "U1", 5)],
                periods=minimal_periods(),
            )
            dataset, _ = load_dataset(fixtures)
            views, _ = build_case_views(dataset)
            fulfillment = aggregate(views, "overall", dataset.periods)[0].fulfillment
            self.assertEqual(fulfillment.total, 3)
            self.assertEqual(fulfillment.closed, 2)
            self.assertEqual(fulfillment.open, 1)
            self.assertEqual(fulfillment.outcome_counts,
                             {"completed": 1, "open": 1, "referred": 1})
            self.assertEqual(fulfillment.completion_rate, 0.5)

    def test_period_assignment_uses_closed_at_and_marks_unassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    _case("C1", closed="2026-06-10"),
                    _case("C2", closed="2026-07-10"),
                    _case("C3", closed="", outcome="open"),
                ],
                invitations=[],
                responses=[],
                periods=minimal_periods(),
            )
            dataset, _ = load_dataset(fixtures)
            views, _ = build_case_views(dataset)
            groups = {g.key: g for g in aggregate(views, "period", dataset.periods)}
            self.assertEqual(groups["P1"].funnel.cases, 1)
            self.assertEqual(groups["P2"].funnel.cases, 1)
            self.assertEqual(groups[UNASSIGNED_PERIOD].funnel.cases, 1)


class GuardAndRankingTests(unittest.TestCase):
    def _eligible_completed_dataset(self, tmp: str, scores: list[int], *, extra_out_of_frame=0):
        """构造全部属于 eligible_completed_cases 框架且回应完整的案件集。"""

        cases, invitations, responses = [], [], []
        for index, score in enumerate(scores, start=1):
            cid, iid, vid = f"C{index}", f"I{index}", f"V{index}"
            cases.append(_case(cid, closed=f"2026-06-{index:02d}"))
            invitations.append(_inv(iid, cid))
            responses.append(_resp(vid, iid, f"U{index}", score))
        for index in range(extra_out_of_frame):
            cid = f"X{index}"
            cases.append(_case(cid, closed="", outcome="open"))
            invitations.append(_inv(f"IX{index}", cid, eligible="no", delivered="no"))
        return write_fixtures(
            Path(tmp), cases=cases, invitations=invitations,
            responses=responses, periods=minimal_periods(),
        )

    def test_ranking_allowed_when_frame_covers_group_and_thresholds_met(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._eligible_completed_dataset(tmp, [5, 4, 3, 4, 5, 2])
            analysis = run_analysis(fixtures, min_responses=5, min_response_rate=0.5)
            verdict = analysis.verdict_for("overall", "全体")
            self.assertTrue(verdict.rank_allowed)
            self.assertEqual(analysis.rankings["overall"][0]["mean"], 3.83)

    def test_ranking_blocked_by_small_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = self._eligible_completed_dataset(tmp, [5, 4])
            analysis = run_analysis(fixtures, min_responses=5)
            verdict = analysis.verdict_for("overall", "全体")
            self.assertFalse(verdict.rank_allowed)
            self.assertTrue(any("样本不足" in r for r in verdict.reasons))
            self.assertEqual(analysis.rankings["overall"], [])

    def test_ranking_blocked_when_frame_does_not_cover_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 5 票达标，但组内有框架外（未办结/未邀请）案件
            fixtures = self._eligible_completed_dataset(tmp, [5, 4, 3, 4, 5], extra_out_of_frame=1)
            analysis = run_analysis(fixtures)
            verdict = analysis.verdict_for("overall", "全体")
            self.assertFalse(verdict.rank_allowed)
            self.assertTrue(any("框架外案件" in r for r in verdict.reasons))

    def test_ranking_blocked_by_low_response_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 6 个符合条件案件，只有 2 个评价，回收率 1/3
            cases = [_case(f"C{i}", closed=f"2026-06-{i:02d}") for i in range(1, 7)]
            invitations = [_inv(f"I{i}", f"C{i}") for i in range(1, 7)]
            responses = [
                _resp("V1", "I1", "U1", 5),
                _resp("V2", "I2", "U2", 4),
            ]
            fixtures = write_fixtures(
                Path(tmp), cases=cases, invitations=invitations,
                responses=responses, periods=minimal_periods(),
            )
            analysis = run_analysis(fixtures, min_responses=2, min_response_rate=0.5)
            verdict = analysis.verdict_for("overall", "全体")
            self.assertFalse(verdict.rank_allowed)
            self.assertTrue(any("回收率不足" in r for r in verdict.reasons))

    def test_unregistered_sampling_frame_blocks_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            periods = [{**minimal_periods()[0], "sampling": "mystery_frame"}]
            fixtures = self._eligible_completed_dataset(tmp, [5, 4, 3, 4, 5])
            # 覆写 periods
            import json
            (Path(fixtures) / "periods.json").write_text(
                json.dumps(periods, ensure_ascii=False), encoding="utf-8"
            )
            analysis = run_analysis(fixtures)
            verdict = analysis.verdict_for("overall", "全体")
            self.assertFalse(verdict.rank_allowed)
            self.assertTrue(any("未在框架登记表中注册" in r for r in verdict.reasons))

    def test_frame_drift_and_channel_change_detected_across_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    _case("C1", closed="2026-06-05"),
                    _case("C2", closed="2026-07-05"),
                ],
                invitations=[
                    _inv("I1", "C1", channel="phone"),
                    _inv("I2", "C2", channel="paper"),
                ],
                responses=[
                    _resp("V1", "I1", "U1", 4),
                    _resp("V2", "I2", "U2", 5),
                ],
                periods=minimal_periods(),
            )
            analysis = run_analysis(fixtures)
            kinds = {drift.kind for drift in analysis.drifts}
            self.assertIn("frame_drift", kinds)
            self.assertIn("channel_change", kinds)
            self.assertEqual(analysis.period_sampling["P1"], "eligible_completed_cases")
            self.assertEqual(analysis.period_sampling["P2"], "all_closed_cases")

    def test_mixed_sampling_group_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 同一网格跨两个框架不同的时期
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    _case("C1", grid="G1", closed="2026-06-05"),
                    _case("C2", grid="G1", closed="2026-07-05"),
                ],
                invitations=[
                    _inv("I1", "C1"),
                    _inv("I2", "C2"),
                ],
                responses=[
                    _resp("V1", "I1", "U1", 4),
                    _resp("V2", "I2", "U2", 5),
                ],
                periods=minimal_periods(),
            )
            analysis = run_analysis(fixtures)
            verdict = analysis.verdict_for("grid", "G1")
            self.assertFalse(verdict.rank_allowed)
            self.assertTrue(any("混合了不同抽样框架" in r for r in verdict.reasons))


if __name__ == "__main__":
    unittest.main()
