"""Evaluate saved model responses with reproducible, deterministic checks."""
import argparse
import json
from pathlib import Path
import re

CHECKS = {"contains", "not_contains", "max_words", "json_object", "required_keys"}


def reject_constant(token):
    raise ValueError("Non-standard JSON constant: " + token)


def load_jsonl(path):
    records = []
    for line, text in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not text.strip():
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("{}:{}: invalid JSON ({})".format(path, line, error.msg)) from error
        if not isinstance(item, dict):
            raise ValueError("{}:{}: expected an object".format(path, line))
        records.append(item)
    return records


def keyed(records, label):
    result = {}
    for record in records:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(label + ": every record needs a nonempty string id")
        if identifier in result:
            raise ValueError(label + ": duplicate id " + identifier)
        result[identifier] = record
    return result


def validate_checks(checks):
    if not isinstance(checks, dict) or not checks:
        raise ValueError("checks must be a nonempty object")
    unknown = set(checks) - CHECKS
    if unknown:
        raise ValueError("Unknown checks: " + ", ".join(sorted(unknown)))
    for name in {"contains", "not_contains", "required_keys"} & set(checks):
        value = checks[name]
        if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value):
            raise ValueError(name + " must be a nonempty list of nonempty strings")
    if "max_words" in checks and (type(checks["max_words"]) is not int or checks["max_words"] < 0):
        raise ValueError("max_words must be a nonnegative integer")
    if "json_object" in checks and checks["json_object"] is not True:
        raise ValueError("json_object must be true when specified")


def check_response(text, checks):
    validate_checks(checks)
    results = []
    folded = text.casefold()
    for word in checks.get("contains", []):
        results.append({"check": "contains: " + word, "passed": word.casefold() in folded})
    for word in checks.get("not_contains", []):
        results.append({"check": "not_contains: " + word, "passed": word.casefold() not in folded})
    if "max_words" in checks:
        count = len(re.findall(r"\S+", text))
        results.append({"check": "max_words", "passed": count <= checks["max_words"], "actual": count})
    if "json_object" in checks or "required_keys" in checks:
        try:
            obj = json.loads(text, parse_constant=reject_constant)
        except (ValueError, RecursionError):
            obj = None
        valid = isinstance(obj, dict)
        results.append({"check": "json_object", "passed": valid})
        for key in checks.get("required_keys", []):
            results.append({"check": "required_key: " + key, "passed": valid and key in obj})
    return results


def evaluate(cases, responses):
    expected = keyed(cases, "cases")
    actual = keyed(responses, "responses")
    if not expected:
        raise ValueError("The case suite is empty")
    extra = set(actual) - set(expected)
    if extra:
        raise ValueError("Unexpected response ids: " + ", ".join(sorted(extra)))
    results = []
    for identifier, case in expected.items():
        checks = case.get("checks")
        validate_checks(checks)
        if identifier not in actual:
            details = [{"check": "response_present", "passed": False}]
        else:
            answer = actual[identifier].get("response")
            if not isinstance(answer, str):
                raise ValueError("Response for {} must be a string".format(identifier))
            details = check_response(answer, checks)
        results.append({"id": identifier, "passed": all(c["passed"] for c in details), "checks": details})
    passed = sum(case["passed"] for case in results)
    return {"total": len(results), "passed": passed, "failed": len(results) - passed,
            "pass_rate": round(passed / len(results), 4), "cases": results}


def markdown(report):
    lines = ["# PromptCheck report", "", "Passed: {passed}/{total} · Failed: {failed}".format(**report), ""]
    for case in report["cases"]:
        # JSON quoting keeps IDs legible and prevents line breaks in this summary.
        name = json.dumps(case["id"], ensure_ascii=False)
        lines.append("- {} {}".format("PASS" if case["passed"] else "FAIL", name))
        for check in case["checks"]:
            if not check["passed"]:
                lines.append("  - Failed: " + json.dumps(check["check"], ensure_ascii=False))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("responses", type=Path)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(load_jsonl(args.cases), load_jsonl(args.responses))
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else markdown(report)
        if args.output:
            if args.output.resolve() in {args.cases.resolve(), args.responses.resolve()}:
                raise ValueError("Output must not overwrite input files")
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
