import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from community_feedback.cli import main
from community_feedback.reporting import render_html, render_json, render_text

from tests.helpers import minimal_periods, write_fixtures


def _case(cid, closed="2026-06-02"):
    return {"id": cid, "grid": "G1", "service": "维修",
            "closed_at": closed, "outcome": "completed"}


def _inv(iid, case, delivered="yes", eligible="yes"):
    return {"id": iid, "case": case, "channel": "phone",
            "eligible": eligible, "delivered": delivered, "sent_at": "2026-06-03"}


def _resp(vid, inv, score):
    return {"id": vid, "invitation": inv, "respondent": "U1",
            "score": score, "received_at": "2026-06-04", "supersedes": ""}


class CliAndRenderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixtures = write_fixtures(
            Path(self.tmp.name),
            cases=[_case("C1"), _case("C2", closed="2026-06-03")],
            invitations=[_inv("I1", "C1"), _inv("I2", "C2", delivered="no")],
            responses=[_resp("V1", "I1", 4)],
            periods=minimal_periods(),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_validate_command_exit_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["validate", "-f", str(self.fixtures)])
        self.assertEqual(code, 0)
        self.assertIn("结构校验通过", buf.getvalue())

    def test_text_report_contains_unknown_not_zero_and_limitations(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["report", "-f", str(self.fixtures), "--format", "text"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("未知", text)
        self.assertIn("不生成排名", text)
        self.assertIn("未回应", text)

    def test_json_report_roundtrips_and_keeps_funnel_layers(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["report", "-f", str(self.fixtures), "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        overall = next(g for g in data["grouped_metrics"]["overall"] if g["key"] == "全体")
        funnel = overall["funnel"]
        self.assertEqual((funnel["eligible"], funnel["delivered"], funnel["responded"]), (2, 1, 1))
        self.assertEqual(funnel["unknown"], 0)
        self.assertIn("frame_registry", data)

    def test_html_report_is_self_contained_and_escaped(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["report", "-f", str(self.fixtures), "--format", "html"])
        html_text = buf.getvalue()
        self.assertIn("<!DOCTYPE html>", html_text)
        self.assertNotIn("<script", html_text.lower())
        self.assertIn("受限", html_text)

    def test_output_to_file(self):
        out = Path(self.tmp.name) / "report.txt"
        with redirect_stdout(io.StringIO()):
            code = main(["report", "-f", str(self.fixtures), "-o", str(out)])
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        self.assertIn("居民反馈", out.read_text(encoding="utf-8"))

    def test_invalid_fixtures_exit_code_one(self):
        bad_dir = Path(self.tmp.name) / "bad"
        bad_dir.mkdir()
        (bad_dir / "cases.json").write_text("not-json", encoding="utf-8")
        for name in ("invitations", "responses", "periods"):
            (bad_dir / f"{name}.json").write_text("[]", encoding="utf-8")
        code = main(["validate", "-f", str(bad_dir)])
        self.assertEqual(code, 1)

    def test_invalid_thresholds_rejected(self):
        with self.assertRaises(SystemExit):
            main(["report", "-f", str(self.fixtures), "--min-responses", "0"])
        with self.assertRaises(SystemExit):
            main(["report", "-f", str(self.fixtures), "--min-response-rate", "1.5"])

    def test_renderers_share_consistent_numbers(self):
        from community_feedback.analysis import run_analysis
        analysis = run_analysis(self.fixtures)
        text = render_text(analysis)
        html_text = render_html(analysis)
        json_text = render_json(analysis)
        for marker in ("4.00", "50.0%"):
            self.assertIn(marker, text)
        self.assertIn("4.0", json_text)
        self.assertIn("50.0%", html_text)


if __name__ == "__main__":
    unittest.main()
