"""Offline-first Markdown syllabus compiler, GSM-7 SMS quiz formatter, SM-2 scheduler & grader."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

_OPTION_RE = re.compile(r"^([A-D])\)\s+(.+)$")


@dataclass(frozen=True)
class QuestionItem:
    item_id: str
    topic: str
    prompt: str
    choices: dict[str, str]
    answer: str
    hint: str
    explanation: str


@dataclass(frozen=True)
class MasteryPack:
    title: str
    pack_sha256: str
    items: tuple[QuestionItem, ...]


@dataclass(frozen=True)
class Sm2State:
    repetitions: int = 0
    interval_days: int = 0
    ease_factor: float = 2.5


@dataclass(frozen=True)
class GradeResult:
    student_id: str
    correct: int
    total: int
    score_pct: float
    topic_accuracy: dict[str, float]
    missed_items: tuple[str, ...]


def compile_markdown_pack(markdown_text: str, *, title: str = "Curriculum Mastery Pack") -> MasteryPack:
    """Parse structured Markdown questions into a content-addressed offline `MasteryPack`."""
    topic = "General"
    items: list[QuestionItem] = []

    current_q: str | None = None
    choices: dict[str, str] = {}
    answer: str | None = None
    hint = ""
    explanation = ""

    def _flush() -> None:
        nonlocal current_q, choices, answer, hint, explanation
        if current_q is not None:
            if not answer or answer not in choices:
                raise ValueError(f"Question '{current_q[:40]}' missing valid Answer key in choices {sorted(choices)}")
            idx = len(items) + 1
            items.append(
                QuestionItem(
                    item_id=f"Q{idx}",
                    topic=topic,
                    prompt=current_q.strip(),
                    choices=dict(choices),
                    answer=answer,
                    hint=hint.strip(),
                    explanation=explanation.strip(),
                )
            )
        current_q = None
        choices = {}
        answer = None
        hint = ""
        explanation = ""

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            _flush()
            topic = line[3:].strip()
        elif line.startswith("Q:"):
            _flush()
            current_q = line[2:].strip()
        elif m := _OPTION_RE.match(line):
            choices[m.group(1)] = m.group(2).strip()
        elif line.startswith("Answer:"):
            answer = line[7:].strip().upper()
        elif line.startswith("Hint:"):
            hint = line[5:].strip()
        elif line.startswith("Explain:"):
            explanation = line[8:].strip()

    _flush()
    if not items:
        raise ValueError("No questions found in Markdown curriculum source")

    canonical = json.dumps(
        {
            "title": title,
            "items": [
                {
                    "id": i.item_id,
                    "topic": i.topic,
                    "prompt": i.prompt,
                    "choices": i.choices,
                    "answer": i.answer,
                }
                for i in items
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return MasteryPack(title=title, pack_sha256=digest, items=tuple(items))


def format_sms_quiz_card(item: QuestionItem) -> str:
    """Format a question into a strict <=160-char ASCII GSM-7 SMS study card."""
    opts = " ".join(f"{k}){v}" for k, v in sorted(item.choices.items()))
    sms = f"{item.item_id}: {item.prompt} {opts}"
    sms_ascii = sms.encode("ascii", errors="ignore").decode("ascii")
    if len(sms_ascii) > 160:
        sms_ascii = sms_ascii[:157] + "..."
    return sms_ascii


def render_printable_html(pack: MasteryPack) -> str:
    """Render a zero-CDN, print-ready offline HTML exam worksheet with answer key."""
    blocks: list[str] = []
    for item in pack.items:
        opts = "".join(
            f"<li><strong>{html.escape(k)}.</strong> {html.escape(v)}</li>"
            for k, v in sorted(item.choices.items())
        )
        blocks.append(
            f"<section><h3>{html.escape(item.item_id)} [{html.escape(item.topic)}]</h3>"
            f"<p>{html.escape(item.prompt)}</p><ul>{opts}</ul></section>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(pack.title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;line-height:1.5}</style>"
        f"</head><body><h1>{html.escape(pack.title)}</h1>"
        f"<p><small>Pack SHA-256: {pack.pack_sha256[:16]}</small></p>"
        f"{''.join(blocks)}</body></html>"
    )


def sm2_review(state: Sm2State, quality: int) -> Sm2State:
    """Compute the next SuperMemo SM-2 review interval and ease factor (quality 0..5)."""
    if not 0 <= quality <= 5:
        raise ValueError("SM-2 quality must be an integer between 0 and 5")

    ef = state.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(1.3, round(ef, 4))

    if quality < 3:
        return Sm2State(repetitions=0, interval_days=1, ease_factor=ef)

    reps = state.repetitions + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = max(1, round(state.interval_days * ef))
    return Sm2State(repetitions=reps, interval_days=interval, ease_factor=ef)


def parse_sms_response_string(raw: str) -> dict[str, str]:
    """Parse compact SMS exam reply strings such as '1B 2A 3D' or 'Q1:B, Q2:A'."""
    answers: dict[str, str] = {}
    for match in re.finditer(r"(?i)Q?(\d+)\s*[:=-]?\s*([A-D])\b", raw):
        answers[f"Q{int(match.group(1))}"] = match.group(2).upper()
    return answers


def grade_submission(pack: MasteryPack, student_id: str, answers: dict[str, str]) -> GradeResult:
    """Grade one student's responses and compute per-topic mastery percentages."""
    topic_correct: dict[str, int] = defaultdict(int)
    topic_total: dict[str, int] = defaultdict(int)
    missed: list[str] = []
    correct = 0

    for item in pack.items:
        topic_total[item.topic] += 1
        submitted = answers.get(item.item_id, "").strip().upper()
        if submitted == item.answer:
            correct += 1
            topic_correct[item.topic] += 1
        else:
            missed.append(item.item_id)

    total = len(pack.items)
    topic_acc = {
        t: round((topic_correct[t] / topic_total[t]) * 100.0, 1)
        for t in sorted(topic_total)
    }
    return GradeResult(
        student_id=student_id,
        correct=correct,
        total=total,
        score_pct=round((correct / total) * 100.0, 1) if total else 0.0,
        topic_accuracy=topic_acc,
        missed_items=tuple(missed),
    )


def pack_to_dict(pack: MasteryPack) -> dict[str, Any]:
    return {
        "title": pack.title,
        "pack_sha256": pack.pack_sha256,
        "item_count": len(pack.items),
        "items": [
            {
                "item_id": i.item_id,
                "topic": i.topic,
                "prompt": i.prompt,
                "choices": i.choices,
                "answer": i.answer,
                "hint": i.hint,
                "explanation": i.explanation,
                "sms_160": format_sms_quiz_card(i),
            }
            for i in pack.items
        ],
    }
