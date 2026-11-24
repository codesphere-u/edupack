"""CLI for edupack."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from edupack.engine import (
    Sm2State,
    compile_markdown_pack,
    grade_submission,
    pack_to_dict,
    parse_sms_response_string,
    render_printable_html,
    sm2_review,
)

DEMO_MD = """# O-Level Physics & Biology Mastery Pack

## Electricity
Q: What is the SI unit of electrical resistance?
A) Ampere
B) Volt
C) Ohm
D) Watt
Answer: C
Hint: Recall Ohm's Law R = V / I.
Explain: Resistance is measured in Ohms (V/A).

## Cell Biology
Q: Which organelle produces most ATP during aerobic respiration?
A) Ribosome
B) Mitochondrion
C) Vacuole
D) Cell wall
Answer: B
Hint: Known as the powerhouse of the cell.
Explain: Mitochondria carry out oxidative phosphorylation.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edupack",
        description="Offline-first Markdown curriculum compiler, SM-2 scheduler & SMS grader.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_comp = sub.add_parser("compile", help="Compile a Markdown syllabus into offline JSON/HTML")
    p_comp.add_argument("markdown_file")
    p_comp.add_argument("--html-out", default=None)

    sub.add_parser("demo", help="Compile, SMS-format, SM-2 schedule, and grade a sample STEM pack")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        pack = compile_markdown_pack(DEMO_MD)
        answers = parse_sms_response_string("1C 2B")
        grade = grade_submission(pack, "STU-001", answers)
        next_card = sm2_review(sm2_review(Sm2State(), 5), 4)
        print(
            json.dumps(
                {
                    "pack": pack_to_dict(pack),
                    "grade": {
                        "student_id": grade.student_id,
                        "score_pct": grade.score_pct,
                        "topic_accuracy": grade.topic_accuracy,
                    },
                    "sm2_after_two_reviews": {
                        "repetitions": next_card.repetitions,
                        "interval_days": next_card.interval_days,
                        "ease_factor": next_card.ease_factor,
                    },
                },
                indent=2,
            )
        )
        return 0

    if args.command == "compile":
        pack = compile_markdown_pack(Path(args.markdown_file).read_text(encoding="utf-8"))
        if args.html_out:
            Path(args.html_out).write_text(render_printable_html(pack), encoding="utf-8")
        print(json.dumps(pack_to_dict(pack), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
