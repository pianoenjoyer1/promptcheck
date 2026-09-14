from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from promptcheck import check_response, evaluate, load_jsonl


class EvalTests(unittest.TestCase):
    def test_good_and_bad_demo(self):
        cases = load_jsonl("examples/cases.jsonl")
        self.assertEqual(evaluate(cases, load_jsonl("examples/responses-good.jsonl"))["passed"], 4)
        self.assertEqual(evaluate(cases, load_jsonl("examples/responses-bad.jsonl"))["failed"], 3)

    def test_missing_response_fails(self):
        result = evaluate([{"id": "a", "checks": {"contains": ["yes"]}}], [])
        self.assertEqual(result["failed"], 1)

    def test_duplicate_and_extra_ids_rejected(self):
        cases = [{"id": "a", "checks": {"max_words": 1}}]
        for responses in [[{"id": "a", "response": ""}] * 2, [{"id": "b", "response": ""}]]:
            with self.assertRaises(ValueError):
                evaluate(cases, responses)

    def test_invalid_rules_rejected(self):
        for rule in [{}, {"unknown": True}, {"max_words": True}, {"contains": "yes"},
                     {"contains": []}, {"json_object": False}, {"required_keys": [2]}]:
            with self.assertRaises(ValueError):
                check_response("yes", rule)

    def test_json_object_and_keys(self):
        for text in ["[]", "null", "```json\n{}\n```", '{"a": NaN}', "broken"]:
            self.assertFalse(check_response(text, {"json_object": True})[0]["passed"])
        result = check_response('{"title":"x"}', {"required_keys": ["title", "steps"]})
        self.assertEqual([r["passed"] for r in result], [True, True, False])

    def test_casefold_and_word_limit(self):
        self.assertTrue(all(c["passed"] for c in check_response("ДЕРЕКТЕР сапасы", {"contains": ["деректер"], "max_words": 2})))
        self.assertFalse(check_response("one two", {"max_words": 1})[0]["passed"])

    def test_invalid_json_line_identified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "test.jsonl")
            path.write_text('{}\ninvalid', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, ":2:"):
                load_jsonl(path)

    def test_empty_suite_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([], [])

    def test_cli_failure_exit_code(self):
        result = subprocess.run([sys.executable, "promptcheck.py", "examples/cases.jsonl", "examples/responses-bad.jsonl"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed: 3", result.stdout)


if __name__ == "__main__":
    unittest.main()
