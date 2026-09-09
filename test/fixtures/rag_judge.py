"""Shared Judge-report fixtures for eval CLI and composition tests."""

from __future__ import annotations


def judge_report(*, eligible: bool, passed: bool):
    """Build a real EvaluateRag report for CLI exit-code tests.

    Args:
        eligible (bool): When false, return a fake ineligible report.
        passed (bool): When eligible, whether the live gate should pass.

    Returns:
        RagJudgeReport: Report produced by ``EvaluateRag.execute``.
    """
    from test.application.test_evaluate_rag import (
        _ScriptedJudge,
        _baseline,
        _coverage_cases,
        _execute,
    )

    if not eligible:
        return _execute(_coverage_cases(), execution_mode="fake", baseline=None)
    content = (
        '{"score": 1.0, "explanation": "ok"}'
        if passed
        else '{"score": 0.8, "explanation": "ok"}'
    )
    return _execute(
        _coverage_cases(),
        judge=_ScriptedJudge(content),
        baseline=_baseline(),
        execution_mode="live",
    )


def scripted_judge(content: str = '{"score": 0.8, "explanation": "ok"}'):
    from test.application.test_evaluate_rag import _ScriptedJudge

    return _ScriptedJudge(content)


def coverage_cases():
    from test.application.test_evaluate_rag import _coverage_cases

    return _coverage_cases()


def observations_for(cases):
    from test.application.test_evaluate_rag import _observations_for

    return _observations_for(cases)
