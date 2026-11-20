import tempfile
import unittest
from pathlib import Path

from community_feedback.feedback import build_case_views
from community_feedback.loading import load_dataset

from tests.helpers import minimal_periods, write_fixtures


def _case(cid, grid="G1", service="维修", closed="2026-06-02", outcome="completed"):
    return {"id": cid, "grid": grid, "service": service,
            "closed_at": closed, "outcome": outcome}


def _inv(iid, case, channel="phone", eligible="yes", delivered="yes", sent="2026-06-03"):
    return {"id": iid, "case": case, "channel": channel,
            "eligible": eligible, "delivered": delivered, "sent_at": sent}


def _resp(vid, inv, respondent, score, received, supersedes=""):
    return {"id": vid, "invitation": inv, "respondent": respondent,
            "score": score, "received_at": received, "supersedes": supersedes}


class FeedbackChainTests(unittest.TestCase):
    def _run(self, tmp, *, cases, invitations, responses):
        fixtures = write_fixtures(
            Path(tmp), cases=cases, invitations=invitations,
            responses=responses, periods=minimal_periods(),
        )
        dataset, _ = load_dataset(fixtures)
        return build_case_views(dataset)

    def test_supersession_keeps_only_latest_head_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, issues = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1"), _inv("I2", "C1", channel="paper", sent="2026-06-04")],
                responses=[
                    _resp("V1", "I1", "U1", 2, "2026-06-04"),
                    _resp("V2", "I2", "U1", 4, "2026-06-05", supersedes="V1"),
                ],
            )
            view = views[0]
            self.assertTrue(view.responded)
            self.assertEqual(view.current_response_id, "V2")
            self.assertEqual(view.current_score, 4)
            self.assertIn("V1", view.all_response_ids)
            self.assertTrue(any(i.code == "superseded_response" and "V1" in i.refs for i in issues))

    def test_no_response_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, _ = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1", delivered="no")],
                responses=[],
            )
            view = views[0]
            self.assertTrue(view.eligible)
            self.assertFalse(view.delivered)
            self.assertFalse(view.responded)
            self.assertIsNone(view.current_score)

    def test_multiple_independent_chains_count_one_vote_latest_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, issues = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1"), _inv("I2", "C1", channel="paper")],
                responses=[
                    _resp("V1", "I1", "U1", 3, "2026-06-04"),
                    _resp("V2", "I2", "U2", 5, "2026-06-06"),
                ],
            )
            view = views[0]
            self.assertEqual(view.current_score, 5)
            self.assertTrue(any(i.code == "multiple_response_chains" for i in issues))
            # 同一案件无论多少条链，回应状态只算一次
            self.assertTrue(view.responded)

    def test_cycle_invalidates_whole_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, issues = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1")],
                responses=[
                    _resp("V1", "I1", "U1", 2, "2026-06-04", supersedes="V2"),
                    _resp("V2", "I1", "U1", 4, "2026-06-05", supersedes="V1"),
                ],
            )
            view = views[0]
            self.assertFalse(view.responded)
            self.assertIsNone(view.current_score)
            self.assertTrue(any(i.code == "supersede_cycle" for i in issues))

    def test_response_on_undelivered_invitation_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, issues = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1", delivered="no")],
                responses=[_resp("V1", "I1", "U1", 5, "2026-06-04")],
            )
            view = views[0]
            self.assertFalse(view.delivered)
            self.assertFalse(view.responded)
            self.assertTrue(any(i.code == "response_on_undelivered_invitation" for i in issues))

    def test_response_on_ineligible_invitation_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, issues = self._run(
                tmp,
                cases=[_case("C1")],
                invitations=[_inv("I1", "C1", eligible="no", delivered="yes")],
                responses=[_resp("V1", "I1", "U1", 5, "2026-06-04")],
            )
            view = views[0]
            self.assertFalse(view.eligible)
            self.assertFalse(view.responded)
            self.assertTrue(any(i.code == "response_on_ineligible_invitation" for i in issues))

    def test_same_respondent_different_cases_count_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            views, _ = self._run(
                tmp,
                cases=[_case("C1"), _case("C2", closed="2026-06-03")],
                invitations=[_inv("I1", "C1"), _inv("I2", "C2", channel="paper")],
                responses=[
                    _resp("V1", "I1", "U1", 4, "2026-06-04"),
                    _resp("V2", "I2", "U1", 2, "2026-06-05"),
                ],
            )
            by_case = {v.case_id: v for v in views}
            self.assertEqual(by_case["C1"].current_score, 4)
            self.assertEqual(by_case["C2"].current_score, 2)
            self.assertEqual(sum(v.responded for v in views), 2)  # 两票，不合并


if __name__ == "__main__":
    unittest.main()
