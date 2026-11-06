"""核心逻辑的单元测试。

运行：
    python -m unittest discover -s tests -v

这些测试不调用模型：对比、投票、解析、归一化、网页转义都是纯逻辑，
用假数据就能覆盖。真正调用模型的部分（裁判、Agent）由校准集负责验证。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import calibrate  # noqa: E402
import demo_agent  # noqa: E402
import judge  # noqa: E402
import pages  # noqa: E402
import provenance  # noqa: E402
import recorder  # noqa: E402
import report  # noqa: E402
import tape  # noqa: E402
import toolreplay  # noqa: E402


class TestVerdictNormalization(unittest.TestCase):
    def test_plain_verdicts(self):
        for value in ("等价", "变好", "漂移"):
            self.assertEqual(judge._normalize_verdict(value), value)

    def test_aliases(self):
        self.assertEqual(judge._normalize_verdict("行为等价"), "等价")
        self.assertEqual(judge._normalize_verdict("跑偏了"), "漂移")

    def test_negations_are_not_positive(self):
        # 否定句里包含判定词，不能判成肯定结论
        for value in ("不等价", "没有漂移", "不是变好", "未变好"):
            self.assertIsNone(judge._normalize_verdict(value))

    def test_garbage(self):
        self.assertIsNone(judge._normalize_verdict(""))
        self.assertIsNone(judge._normalize_verdict("不知道"))


class TestTape(unittest.TestCase):
    def test_walk_diff_nested(self):
        a = {"keywords": ["a", "b"], "meta": {"x": 1}}
        b = {"keywords": ["a", "c"], "meta": {"x": 1}}
        diffs = tape.walk_diff(a, b)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0][0], "keywords[1]")

    def test_walk_diff_length_change(self):
        diffs = tape.walk_diff({"a": [1]}, {"a": [1, 2]})
        self.assertEqual(diffs, [("a[1]", None, 2)])

    def test_final_output_text(self):
        self.assertEqual(tape.final_output_text({"output": {"summary": "s"}}), "s")
        self.assertEqual(tape.final_output_text({"output": {"final": "f"}}), "f")
        self.assertEqual(tape.final_output_text({"output": {}}), "")


class TestProvenance(unittest.TestCase):
    def test_same_prompt_no_change(self):
        a = provenance.build("x", "m", {"p": "hello"}, {"t": 1}, ["tool"])
        b = provenance.build("x", "m", {"p": "hello"}, {"t": 1}, ["tool"])
        self.assertFalse(provenance.diff(a, b)["changed"])

    def test_prompt_change_has_similarity(self):
        a = provenance.build("x", "m", {"p": "hello world"})
        b = provenance.build("x", "m", {"p": "hello there"})
        items = provenance.diff(a, b)["items"]
        self.assertEqual(items[0]["kind"], "prompt")
        self.assertGreater(items[0]["similarity"], 0)
        self.assertLess(items[0]["similarity"], 1)

    def test_missing_provenance(self):
        result = provenance.diff(None, {"prompts": []})
        self.assertFalse(result["available"])


class TestConsensus(unittest.TestCase):
    def test_majority_and_agreement(self):
        verdicts = iter(
            [
                ("等价", "a"),
                ("漂移", "b"),
                ("等价", "c"),
            ]
        )

        def fake_judge(tape_a, tape_b, max_attempts=2):
            verdict, reason = next(verdicts)
            return {
                "verdict": verdict,
                "reason": reason,
                "model": "fake",
                "attempts": 1,
                "elapsed_ms": 1,
                "raw": "",
            }

        original = judge.judge
        judge.judge = fake_judge
        try:
            result = judge.judge_consensus({"steps": []}, {"steps": []}, runs=3)
        finally:
            judge.judge = original

        self.assertEqual(result["verdict"], "等价")
        self.assertEqual(result["agreement"], "2:1")
        self.assertEqual(len(result["runs"]), 3)

    def test_failed_runs_are_skipped(self):
        calls = {"n": 0}

        def flaky(tape_a, tape_b, max_attempts=2):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {
                "verdict": "漂移",
                "reason": "ok",
                "model": "fake",
                "attempts": 1,
                "elapsed_ms": 1,
                "raw": "",
            }

        original = judge.judge
        judge.judge = flaky
        try:
            result = judge.judge_consensus({"steps": []}, {"steps": []}, runs=2)
        finally:
            judge.judge = original

        self.assertEqual(result["verdict"], "漂移")
        self.assertEqual(result["failures"].__len__(), 1)
        self.assertEqual(result["runs_succeeded"], 1)


class TestKappa(unittest.TestCase):
    def test_perfect(self):
        results = [
            {"ok": True, "label": "等价", "predicted": "等价", "correct": True},
            {"ok": True, "label": "漂移", "predicted": "漂移", "correct": True},
        ]
        self.assertEqual(calibrate.cohen_kappa(results), 1.0)

    def test_single_class_is_undefined(self):
        results = [
            {"ok": True, "label": "等价", "predicted": "等价", "correct": True}
        ]
        self.assertIsNone(calibrate.cohen_kappa(results))

    def test_empty(self):
        self.assertIsNone(calibrate.cohen_kappa([]))


class TestPagesEscaping(unittest.TestCase):
    def test_model_content_is_escaped(self):
        payload = {
            "generated_at": "2026-01-01T00:00:00",
            "baseline_tape": "<script>alert(1)</script>",
            "candidate_tape": "b",
            "baseline": {
                "meta": {"run_id": "a", "variant": "<img src=x>"},
                "steps": [],
                "output": {"summary": "<script>alert(2)</script>"},
            },
            "candidate": {
                "meta": {"run_id": "b", "variant": "b"},
                "steps": [],
                "output": {"summary": "ok"},
            },
            "report": {
                "task": "<svg onload=alert(3)>",
                "checks": [
                    {"label": "<b>x</b>", "consistent": True, "detail": "<script>alert(4)</script>"}
                ],
                "summary": {"total": 1, "consistent": 1, "different": 0},
                "content": {
                    "changed_steps": [
                        {"index": 1, "label": "<i>s</i>", "name": "x", "diff_count": 1}
                    ],
                    "root_steps": [],
                    "final_output_changed": True,
                },
                "provenance": {
                    "available": True,
                    "changed": True,
                    "items": [{"kind": "prompt", "name": "p", "label": "<script>alert(5)</script>", "similarity": 0.5}],
                },
                "verdict": {
                    "verdict": "等价",
                    "agreement": "3:0",
                    "reason": "<script>alert(6)</script>",
                    "model": "<script>alert(7)</script>",
                    "runs": [{"index": 1, "verdict": "等价", "reason": "<script>alert(8)</script>"}],
                },
            },
        }
        html = pages.render_html(payload)
        for fragment in ("<script>alert", "<img src=x", "<svg onload", "<b>x</b>", "<i>s</i>"):
            self.assertNotIn(fragment, html)


class TestPathSafety(unittest.TestCase):
    def test_task_name_cannot_escape_tapes_dir(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            rec = recorder.Recorder("../../evil", {}, tapes_dir=tmp)
            rec.log("s", {}, {})
            path = rec.finish(output={})
            self.assertEqual(path.parent.resolve(), Path(tmp).resolve())

    def test_safe_name_keeps_chinese(self):
        self.assertEqual(recorder.safe_name("每日简报 v2"), "每日简报-v2")

    def test_mock_search_url_is_deterministic(self):
        first = demo_agent.mock_search(["关键词"])[0]["url"]
        second = demo_agent.mock_search(["关键词"])[0]["url"]
        self.assertEqual(first, second)
        self.assertNotIn(" ", first)


class TestToolReplay(unittest.TestCase):
    def _tape(self):
        return {
            "meta": {"run_id": "src-1"},
            "steps": [
                {"name": "search", "input": {"keywords": ["a"]}, "output": {"results": [1]}},
                {"name": "search", "input": {"keywords": ["b"]}, "output": {"results": [2]}},
            ],
        }

    def test_exact_match_and_single_use(self):
        replay = toolreplay.StepReplay(self._tape())
        self.assertEqual(replay.replay("search", {"keywords": ["a"]}), {"results": [1]})
        self.assertIsNone(replay.replay("search", {"keywords": ["a"]}))
        self.assertEqual(replay.stats(), {"hits": 1, "misses": 1})

    def test_name_match_allows_different_input(self):
        replay = toolreplay.StepReplay(self._tape(), match="name")
        self.assertEqual(replay.replay("search", {"keywords": ["z"]}), {"results": [1]})
        self.assertEqual(replay.replay("search", {"keywords": ["y"]}), {"results": [2]})

    def test_result_is_deep_copied(self):
        replay = toolreplay.StepReplay(self._tape())
        out = replay.replay("search", {"keywords": ["a"]})
        out["results"].append(99)
        self.assertEqual(replay.tape["steps"][0]["output"], {"results": [1]})

    def test_invalid_match_mode(self):
        with self.assertRaises(ValueError):
            toolreplay.StepReplay({}, match="fuzzy")


class TestReportSave(unittest.TestCase):
    def test_save_writes_three_files(self):
        import tempfile

        tape = {
            "meta": {
                "run_id": "t-1",
                "variant": "v",
                "model": "m",
                "started_at": "2026-01-01T00:00:00+08:00",
                "duration_ms": 1,
                "step_count": 0,
            },
            "task": {"name": "测试任务/../evil", "input": {}, "requirements": []},
            "steps": [],
            "output": {"summary": "内容"},
        }
        report_dict = {
            "task": "测试任务/../evil",
            "checks": [],
            "summary": {"total": 0, "consistent": 0, "different": 0},
            "content": {
                "changed_steps": [],
                "root_steps": [],
                "final_output_changed": False,
            },
            "provenance": {"available": False, "changed": False, "items": [], "reason": "x"},
            "verdict": {"skipped": True, "reason": "无差异", "verdict": None, "model": None},
        }
        with tempfile.TemporaryDirectory() as tmp:
            md, js, html = report.save(report_dict, tape, tape, out_dir=tmp)
            for path in (md, js, html):
                self.assertTrue(path.exists(), path)
                self.assertEqual(path.parent.resolve(), Path(tmp).resolve())


class TestRecorderCollision(unittest.TestCase):
    def test_same_second_does_not_overwrite(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for _ in range(2):
                rec = recorder.Recorder("t", {"q": "x"}, tapes_dir=tmp)
                rec.log("s", {}, {"v": 1})
                paths.append(rec.finish(output={"v": 1}))
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue(all(p.exists() for p in paths))


if __name__ == "__main__":
    unittest.main()