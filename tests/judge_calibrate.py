#!/usr/bin/env python3
"""Opt-in judge calibration over hand-labeled answers. Never required CI.

This file is intentionally not named ``test_*.py``. Usage:

  CYCLAW_EVAL_LIVE=1 python tests/judge_calibrate.py

Runs only the judge (Anthropic by default, or the loopback model named by
config.yaml ``evals.local_judge``) over the thirty labeled rows in
``tests/fixtures/groundedness/calibration.json`` and reports agreement with the
hand labels. No contestant generation happens. Run it before trusting a judge's
nightly trend, especially a local judge whose family may overlap the contestant
(#1398 slice D). Report only: set an agreement floor from a measured run, not
from this file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import judge_eval  # noqa: E402

CALIBRATION_PATH = judge_eval.FIXTURE_ROOT / "calibration.json"
REPORT_PATH = judge_eval.EVAL_ROOT / "calibration_report.json"
MIN_ROWS = 30
_ROW_FIELDS = frozenset({
    "id",
    "case_id",
    "answer",
    "expected_supported_claim_ids",
    "expected_contradicted_claim_ids",
    "expected_forbidden_claim_ids",
    "expected_pass",
})
_ROW_ID_RE = re.compile(r"^cal_[a-z0-9_]{2,63}$")


@dataclass(frozen=True, slots=True)
class CalibrationRow:
    row_id: str
    case_id: str
    answer: str
    expected_supported: tuple[str, ...]
    expected_contradicted: tuple[str, ...]
    expected_forbidden: tuple[str, ...]
    expected_pass: bool


def _id_tuple(raw: object, *, field: str, allowed: set[str]) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise judge_eval.EvalError(f"calibration field {field} must be a string array")
    values = tuple(raw)
    if len(values) != len(set(values)) or not set(values).issubset(allowed):
        raise judge_eval.EvalError(f"calibration field {field} contains duplicate or unknown claim ids")
    return values


def load_rows(
    path: Path = CALIBRATION_PATH,
    cases: dict[str, judge_eval.EvalCase] | None = None,
) -> tuple[CalibrationRow, ...]:
    if cases is None:
        cases = {case.case_id: case for case in judge_eval.load_cases()}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise judge_eval.EvalError(f"cannot load calibration rows ({type(exc).__name__})") from None
    if not isinstance(raw, list) or len(raw) < MIN_ROWS:
        raise judge_eval.EvalError(f"calibration fixture must contain at least {MIN_ROWS} rows")
    rows: list[CalibrationRow] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != _ROW_FIELDS:
            raise judge_eval.EvalError("calibration row has missing or unexpected fields")
        row_id = item["id"]
        case_id = item["case_id"]
        answer = item["answer"]
        expected_pass = item["expected_pass"]
        if not isinstance(row_id, str) or not _ROW_ID_RE.fullmatch(row_id):
            raise judge_eval.EvalError("calibration row id is invalid")
        if not isinstance(case_id, str) or case_id not in cases:
            raise judge_eval.EvalError(f"calibration row {row_id} names an unknown case")
        if not isinstance(answer, str) or not answer.strip():
            raise judge_eval.EvalError(f"calibration row {row_id} has an empty answer")
        if not isinstance(expected_pass, bool):
            raise judge_eval.EvalError(f"calibration row {row_id} has a non-boolean expected_pass")
        case = cases[case_id]
        expected_ids = {f"E{index}" for index in range(1, len(case.expected_claims) + 1)}
        forbidden_ids = {f"F{index}" for index in range(1, len(case.forbidden_claims) + 1)}
        supported = _id_tuple(item["expected_supported_claim_ids"], field="expected_supported_claim_ids", allowed=expected_ids)
        contradicted = _id_tuple(
            item["expected_contradicted_claim_ids"], field="expected_contradicted_claim_ids", allowed=expected_ids
        )
        forbidden = _id_tuple(item["expected_forbidden_claim_ids"], field="expected_forbidden_claim_ids", allowed=forbidden_ids)
        if set(supported).intersection(contradicted):
            raise judge_eval.EvalError(f"calibration row {row_id} marks a claim both supported and contradicted")
        rows.append(CalibrationRow(
            row_id=row_id,
            case_id=case_id,
            answer=answer.strip(),
            expected_supported=supported,
            expected_contradicted=contradicted,
            expected_forbidden=forbidden,
            expected_pass=expected_pass,
        ))
    ids = [row.row_id for row in rows]
    if len(ids) != len(set(ids)):
        raise judge_eval.EvalError("calibration row ids must be unique")
    return tuple(rows)


def compare(row: CalibrationRow, scored: dict[str, object], judged: judge_eval.JudgeResult) -> dict[str, object]:
    """One metadata-only comparison of the judge's verdict against the hand label."""
    return {
        "id": row.row_id,
        "case_id": row.case_id,
        "expected_pass": row.expected_pass,
        "observed_pass": scored["pass"],
        "pass_match": scored["pass"] is row.expected_pass,
        "supported_match": set(judged.supported_claim_ids) == set(row.expected_supported),
        "contradicted_match": set(judged.contradicted_claim_ids) == set(row.expected_contradicted),
        "forbidden_match": set(judged.forbidden_claim_ids) == set(row.expected_forbidden),
        "groundedness": scored["groundedness"],
        "reason_codes": list(judged.reason_codes),
    }


def summarize(
    results: list[dict[str, object]],
    *,
    judge_provider: str,
    judge_model: str,
    index_fingerprint: str,
) -> dict[str, object]:
    total = len(results)

    def rate(key: str) -> float:
        return round(sum(result[key] is True for result in results) / total, 4) if total else 0.0

    return {
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": judge_eval._git_sha(),
        "rubric_version": judge_eval.RUBRIC_VERSION,
        "index_fingerprint": index_fingerprint,
        "judge": judge_eval._model_record(judge_provider, judge_model),
        "aggregate": {
            "rows": total,
            "pass_agreement": rate("pass_match"),
            "supported_agreement": rate("supported_match"),
            "contradicted_agreement": rate("contradicted_match"),
            "forbidden_agreement": rate("forbidden_match"),
        },
        "rows": results,
    }


def write_report(report: dict[str, object], eval_root: Path = judge_eval.EVAL_ROOT) -> Path:
    eval_root.mkdir(parents=True, exist_ok=True)
    report_path = eval_root / REPORT_PATH.name
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    return report_path


def run_calibration(eval_root: Path = judge_eval.EVAL_ROOT) -> dict[str, object]:
    root_cfg = judge_eval._require_live_authorization()
    cases = {case.case_id: case for case in judge_eval.load_cases()}
    rows = load_rows(cases=cases)
    config_path, index_fingerprint, _ = judge_eval.build_eval_index(eval_root)
    retriever = judge_eval._new_retriever(config_path)
    try:
        judge, judge_provider = judge_eval._new_judge(root_cfg)
    except Exception:
        retriever.close()
        raise
    results: list[dict[str, object]] = []
    try:
        for row in rows:
            case = cases[row.case_id]
            evidence = judge_eval._retrieve_evidence(retriever, case.query)
            try:
                judged_text = judge.generate(
                    judge_eval._judge_prompt(case, row.answer, evidence),
                    spend_context={"source": "eval", "spend_file": eval_root / judge_eval.SPEND_PATH.name},
                )
                judged = judge_eval.parse_judge_result(judged_text, case)
            except Exception as exc:  # noqa: BLE001 - no provider/body text crosses this CLI boundary
                raise judge_eval.EvalError(f"row {row.row_id} could not be judged ({type(exc).__name__})") from None
            scored = judge_eval.score_case(case, row.answer, evidence, judged)
            results.append(compare(row, scored, judged))
    finally:
        judge.close()
        retriever.close()
    report = summarize(
        results,
        judge_provider=judge_provider,
        judge_model=judge.model,
        index_fingerprint=index_fingerprint,
    )
    write_report(report, eval_root)
    return report


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("refusing: judge_calibrate accepts no path or endpoint overrides", file=sys.stderr)
        return 2
    try:
        judge_eval._require_live_authorization()
    except judge_eval.EvalError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    try:
        report = run_calibration()
    except judge_eval.EvalError as exc:
        print(f"calibration failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - redact unexpected provider and local-runtime details
        print(f"calibration failed: unexpected {type(exc).__name__}", file=sys.stderr)
        return 2
    aggregate = report["aggregate"]
    if not isinstance(aggregate, dict):
        print("calibration failed: report aggregate is invalid", file=sys.stderr)
        return 2
    print(
        "judge calibration: rows={rows} pass_agreement={p} supported={s} contradicted={c} forbidden={f} report={r}".format(
            rows=aggregate["rows"],
            p=aggregate["pass_agreement"],
            s=aggregate["supported_agreement"],
            c=aggregate["contradicted_agreement"],
            f=aggregate["forbidden_agreement"],
            r=REPORT_PATH,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
