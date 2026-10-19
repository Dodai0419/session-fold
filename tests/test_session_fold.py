import unittest
from pathlib import Path

import session_fold as sf

FX = Path(__file__).resolve().parent.parent / "fixtures"


class Parse(unittest.TestCase):
    # Expected totals are what agentplay 0.2.1 reports for fixtures/session.jsonl (agentplay export).
    def setUp(self):
        self.s = sf.parse(FX / "session.jsonl")

    def test_totals_match_agentplay(self):
        t = self.s["totals"]
        self.assertEqual((t["calls"], t["errors"], t["requests"], t["tokens"], t["outputTokens"], t["retries"],
                          t["durationMs"], t["userTurns"]), (8, 1, 9, 311408, 2820, 1, 75000, 1))

    def test_event_kinds_match_agentplay(self):
        kinds = [e["kind"] for e in self.s["events"]]
        self.assertEqual(kinds, ["search", "read", "read", "read", "edit", "verify", "edit", "verify"])
        self.assertTrue(self.s["events"][5]["err"])
        self.assertEqual(self.s["events"][7]["retryOf"], 5)


class Fold(unittest.TestCase):
    # Expected levels are what TextFold 0.10.7 prints for fixtures/sample.md with no model (`get --no-generate`).
    def setUp(self):
        self.doc = sf.fold((FX / "sample.md").read_text(encoding="utf-8"))

    def test_local_levels_match_textfold(self):
        u = self.doc["sections"][0]["units"][0]
        self.assertEqual(u["topic"], "The /orders endpoint")
        self.assertEqual(u["takeaway"], "The /orders endpoint returned 429 for every request after the deploy")
        self.assertEqual(u["key"], "The /orders endpoint returned 429 for every request after the deploy.")

    def test_topic_level_joins_unit_topics(self):
        md = sf.render(self.doc, "topic")
        self.assertIn("The middleware now; Parse durations explicitly; Add a test", md)

    def test_takeaway_cuts_at_14_words(self):
        u = sf.fold("# t\n\n## s\n\none two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen.")["sections"][0]["units"][0]
        self.assertEqual(u["takeaway"], "one two three four five six seven eight nine ten eleven twelve thirteen fourteen")


class SessionDoc(unittest.TestCase):
    def test_session_markdown_folds_to_one_line_per_step(self):
        md = sf.session_markdown(sf.parse(FX / "session.jsonl"))
        self.assertIn("npm test", md)
        out = sf.render(sf.fold(md), "takeaway")
        self.assertIn("FAILED", out)


if __name__ == "__main__":
    unittest.main()
