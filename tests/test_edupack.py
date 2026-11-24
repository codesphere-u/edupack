"""Tests for edupack Markdown compilation, SM-2 scheduling, SMS cards, HTML export & grading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edupack import (
    Sm2State,
    compile_markdown_pack,
    format_sms_quiz_card,
    grade_submission,
    parse_sms_response_string,
    render_printable_html,
    sm2_review,
)
from edupack.cli import DEMO_MD
from edupack.cli import main as cli_main


def test_compile_sms_and_printable_html_offline() -> None:
    pack = compile_markdown_pack(DEMO_MD)
    assert len(pack.items) == 2
    assert len(pack.pack_sha256) == 64
    for item in pack.items:
        sms = format_sms_quiz_card(item)
        assert len(sms) <= 160
        assert sms.isascii()
    html_doc = render_printable_html(pack)
    assert "<!doctype html>" in html_doc
    assert "Ohm" in html_doc


def test_sm2_progression_and_lapse_reset() -> None:
    s0 = Sm2State()
    s1 = sm2_review(s0, 5)
    assert s1.repetitions == 1 and s1.interval_days == 1
    s2 = sm2_review(s1, 5)
    assert s2.repetitions == 2 and s2.interval_days == 6
    s3 = sm2_review(s2, 4)
    assert s3.repetitions == 3 and s3.interval_days > 6
    # Forgotten card resets repetitions to 0 and interval to 1 day
    lapsed = sm2_review(s3, 1)
    assert lapsed.repetitions == 0 and lapsed.interval_days == 1
    with pytest.raises(ValueError):
        sm2_review(s0, 6)


def test_sms_grading_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pack = compile_markdown_pack(DEMO_MD)
    parsed = parse_sms_response_string("1C 2A")
    res = grade_submission(pack, "STU-42", parsed)
    assert res.correct == 1 and res.total == 2 and res.score_pct == 50.0
    assert res.topic_accuracy["Electricity"] == 100.0
    assert res.topic_accuracy["Cell Biology"] == 0.0
    assert res.missed_items == ("Q2",)

    assert cli_main(["demo"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["grade"]["score_pct"] == 100.0

    md_path = tmp_path / "quiz.md"
    html_path = tmp_path / "quiz.html"
    md_path.write_text(DEMO_MD, encoding="utf-8")
    assert cli_main(["compile", str(md_path), "--html-out", str(html_path)]) == 0
    assert html_path.exists()
