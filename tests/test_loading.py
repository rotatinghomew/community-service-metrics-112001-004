import unittest
from pathlib import Path

from community_feedback.loading import load_dataset
from community_feedback.models import DataValidationError

from tests.helpers import minimal_periods, write_fixtures

ROOT = Path(__file__).resolve().parents[1]


class FixtureLoadingTests(unittest.TestCase):
    def test_bundled_fixtures_load_and_coerce_empty_strings(self):
        dataset, warnings = load_dataset(ROOT / "fixtures")
        self.assertEqual({c.id for c in dataset.cases}, {"A-1", "A-2", "A-3", "A-4", "A-5"})
        open_case = dataset.case_by_id("A-4")
        self.assertIsNone(open_case.closed_at)  # 空字符串 -> None，而非业务终态
        self.assertFalse(any(inv.eligible for inv in dataset.invitations if inv.id == "I-5"))
        self.assertTrue(any(issue.code == "ineligible_but_delivered" for issue in warnings))

    def test_missing_file_is_blocking_error(self):
        fixtures = ROOT / "fixtures"
        # 直接构造一个缺失文件的目录场景
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixtures"
            target.mkdir()
            for name in ("cases", "invitations", "responses"):
                (target / f"{name}.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(DataValidationError) as ctx:
                load_dataset(target)
            self.assertTrue(any(i.code == "missing_file" for i in ctx.exception.issues))

    def test_bad_enum_and_bad_score_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[{"id": "C1", "grid": "G1", "service": "维修",
                        "closed_at": "2026-06-02", "outcome": "completed"}],
                invitations=[{"id": "I1", "case": "C1", "channel": "phone",
                              "eligible": "maybe", "delivered": "yes", "sent_at": ""}],
                responses=[{"id": "V1", "invitation": "I1", "respondent": "U1",
                            "score": 9, "received_at": "", "supersedes": ""}],
                periods=minimal_periods(),
            )
            with self.assertRaises(DataValidationError) as ctx:
                load_dataset(fixtures)
            codes = {i.code for i in ctx.exception.issues}
            self.assertIn("bad_enum", codes)
            self.assertIn("bad_score", codes)

    def test_dangling_reference_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[],
                invitations=[{"id": "I1", "case": "GHOST", "channel": "phone",
                              "eligible": "yes", "delivered": "yes", "sent_at": ""}],
                responses=[],
                periods=minimal_periods(),
            )
            with self.assertRaises(DataValidationError) as ctx:
                load_dataset(fixtures)
            self.assertTrue(any(i.code == "dangling_ref" for i in ctx.exception.issues))

    def test_duplicate_ids_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fixtures = write_fixtures(
                Path(tmp),
                cases=[
                    {"id": "C1", "grid": "G1", "service": "维修",
                     "closed_at": "2026-06-02", "outcome": "completed"},
                    {"id": "C1", "grid": "G1", "service": "维修",
                     "closed_at": "2026-06-03", "outcome": "completed"},
                ],
                invitations=[],
                responses=[],
                periods=minimal_periods(),
            )
            with self.assertRaises(DataValidationError) as ctx:
                load_dataset(fixtures)
            self.assertTrue(any(i.code == "duplicate_id" for i in ctx.exception.issues))


if __name__ == "__main__":
    unittest.main()
