"""Live voice-brain evaluation, isolated from DB, memory, web and TTS writes.

PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_voice_socratic.py --repeat 2
JSONL retains answers for human review. Mechanical checks are not a pedagogy score.
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.core.config import get_settings
from app.services.voice import brain, local_brain

# name, preceding question, student utterance, evidence, question expected, visual expected
CASES = [
    (
        "softmax",
        "안녕하세요! 궁금한 게 있나요?",
        "softmax가 뭔지 모르겠어",
        "소프트맥스는 점수의 지수값을 전체 합으로 나눠 합이 1인 가중치를 만든다.",
        True,
        True,
    ),
    (
        "os",
        "",
        "운영체제가 뭐야?",
        "운영체제는 프로그램 사이에 CPU와 메모리를 할당하고 관리한다.",
        True,
        True,
    ),
    (
        "evaporation",
        "",
        "증발하면 왜 시원해?",
        "증발에 필요한 열을 피부에서 가져가면 피부 온도가 내려간다.",
        True,
        True,
    ),
    (
        "fractions",
        "",
        "분수가 뭐야?",
        "분수는 전체를 같은 크기로 나눈 부분의 수를 나타낸다.",
        True,
        True,
    ),
    (
        "uncertain",
        "동전 두 개가 모두 앞면일 확률은 얼마일까요?",
        "모르겠어",
        "공정한 동전 두 개에는 앞앞, 앞뒤, 뒤앞, 뒤뒤가 같은 확률로 나온다.",
        True,
        True,
    ),
    (
        "wrong",
        "합력이 0이면 움직이던 물체는 어떻게 될까요?",
        "바로 멈춰요",
        "합력이 0이면 물체는 현재의 속도를 유지한다.",
        True,
        False,
    ),
    (
        "correct",
        "두 확률이 0.3과 0.7이면 합은 얼마인가요?",
        "1이요",
        "확률분포의 확률 합은 1이다.",
        True,
        False,
    ),
    (
        "consent",
        "재귀가 멈추는 조건을 살펴볼까요?",
        "응",
        "재귀 함수에는 반복 호출을 끝내는 종료 조건이 필요하다.",
        True,
        True,
    ),
    (
        "switch",
        "확률의 합은 얼마인가요?",
        "그거 말고 기회비용이 궁금해",
        "기회비용은 선택으로 포기한 대안 중 가장 가치가 큰 것이다.",
        True,
        False,
    ),
    ("greeting", "", "안녕", "", False, False),
    ("closing", "어느 쪽이 더 클까요?", "고마워 오늘은 여기까지", "", False, False),
    ("pause", "그 이유가 뭘까요?", "잠깐 기다려줘", "", False, False),
    (
        "reuse",
        "이 그림에서 더 큰 가중치는 어느 쪽인가요?",
        "모르겠어",
        "두 가중치가 0.8과 0.2이면 0.8이 더 크다.",
        True,
        True,
    ),
    (
        "correction",
        "분류 문제를 보고 있어요.",
        "아니 회귀 문제라고 했어",
        "회귀는 연속적인 수치를 예측하고 분류는 범주를 예측한다.",
        True,
        False,
    ),
    (
        "binary",
        "",
        "이진 탐색이 뭐야?",
        "정렬된 목록에서 가운데 값과 비교해 탐색 범위를 절반으로 줄인다.",
        True,
        True,
    ),
    (
        "overfit",
        "",
        "과적합이 이해가 안 돼",
        "훈련 자료에는 잘 맞지만 새로운 자료에서는 성능이 나쁜 상태이다.",
        True,
        True,
    ),
    (
        "density",
        "",
        "밀도가 뭐야?",
        "밀도는 질량을 부피로 나눈 값이다. 같은 부피에서 질량이 크면 밀도가 크다.",
        True,
        True,
    ),
    (
        "scarcity",
        "",
        "희소성이 무슨 뜻이야?",
        "희소성은 욕구에 비해 이를 충족할 자원이 제한되어 선택이 필요한 상태이다.",
        True,
        False,
    ),
    (
        "chain_start",
        "",
        "평균이 뭐야?",
        "평균은 수의 합을 개수로 나눈 값이며 같은 크기로 나누는 상황으로 설명할 수 있다.",
        True,
        True,
    ),
    (
        "chain_unsure",
        "",
        "모르겠어",
        "평균은 수의 합을 개수로 나눈 값이며 같은 크기로 나누는 상황으로 설명할 수 있다.",
        True,
        True,
    ),
    (
        "chain_answer",
        "",
        "전체를 똑같이 나누는 거야?",
        "평균은 수의 합을 개수로 나눈 값이며 같은 크기로 나누는 상황으로 설명할 수 있다.",
        True,
        False,
    ),
    ("chain_close", "", "이제 그만할게", "", False, False),
]


def checks(
    question,
    reply,
    ask,
    visual,
    visuals,
    previous_reply="",
    previous_visuals=(),
    visual_planned=False,
):
    def compact(s):
        return re.sub(r"[\W_]+", "", s).casefold()

    q, answer = compact(question), compact(reply)
    issues = []
    if not answer or (q and not answer.replace(q, "")):
        issues.append("empty_or_echo")
    prior = compact(previous_reply)
    if len(prior) >= 12 and prior in answer:
        issues.append("repeated_previous")
    if len(reply) > 240:
        issues.append("long_reply")
    count = reply.count("?") + reply.count("？")
    if ask and count != 1:
        issues.append("question_count")
    if not ask and count:
        issues.append("unwanted_question")
    if re.search(r"궁금하신가요|설명해\s*드릴까요|이해되셨나요|뭐라고 생각", reply):
        issues.append("permission_or_definition_quiz")
    if visual and not (visuals or previous_visuals or visual_planned):
        issues.append("missing_visual")
    if not ask and visuals:
        issues.append("unwanted_visual")
    return issues


async def main(args):
    settings = get_settings().model_copy(update={"voice_trace_content": False})
    if args.model:
        settings.voice_llm_model = args.model
    if args.base_url:
        settings.voice_llm_base_url = args.base_url
    if settings.use_mock_llm:
        raise RuntimeError("Live LLM required, not USE_MOCK_LLM")

    async def prefetch(context, question, timer):
        return {
            "student_question": question,
            "weak_concepts": {"found": False},
            "course_materials": {
                "found": bool(context.evidence),
                "results": [
                    {"file": "eval.txt", "page": 1, "excerpt": context.evidence}
                ]
                if context.evidence
                else [],
            },
        }

    async def run_tool(context, name, arguments, timer):
        if name == "show_visualization":
            try:
                return brain.show_visualization(**arguments)
            except (ValueError, TypeError) as exc:
                return json.dumps({"error": str(exc)})
        return '{"found":false,"sources":[],"error":"offline evaluation web fixture"}'

    results = []
    with (
        patch.object(local_brain, "get_settings", return_value=settings),
        patch.object(brain, "prefetch_context", new=prefetch),
        patch.object(brain, "run_tool", new=run_tool),
        patch(
            "app.services.voice.session_store.external_brain_for",
            return_value=SimpleNamespace(schedule=Mock()),
        ),
    ):
        for repeat in range(args.repeat):
            chain_context = None
            for name, previous, question, evidence, ask, visual in CASES:
                if args.case and name not in args.case:
                    continue
                context = brain.VoiceContext("eval", "평가 과목", "eval", None)
                if name.startswith("chain_"):
                    if chain_context is None:
                        chain_context = context
                    context = chain_context
                context.evidence = evidence
                if previous:
                    context.history = [
                        {"role": "user", "content": "함께 공부하자"},
                        {"role": "assistant", "content": previous},
                    ]
                if name == "reuse":
                    context.last_visualizations = [
                        json.loads(
                            brain.show_visualization(
                                kind="plot",
                                title="두 가중치",
                                caption="두 값을 비교해 보세요.",
                                points=[{"x": 1, "y": 0.8}, {"x": 2, "y": 0.2}],
                                x_label="항목",
                                y_label="가중치",
                            )
                        )
                    ]
                previous_visuals = list(context.last_visualizations)
                started = time.perf_counter()
                try:
                    result = await local_brain.think_voice(
                        context,
                        question,
                        brain.StageTimer(),
                        "socratic",
                        on_speech_delta=AsyncMock(),
                        on_speech_rollback=AsyncMock(),
                    )
                    row = {
                        "case": name,
                        "repeat": repeat,
                        "reply": result.reply,
                        "tools": result.tools,
                        "visuals": result.visualizations,
                        "visual_action": result.visual_action,
                        "visual_topic": result.visual_topic,
                        "issues": checks(
                            question,
                            result.reply,
                            ask,
                            visual,
                            result.visualizations,
                            previous,
                            previous_visuals,
                            result.visual_action in {"show", "reuse"},
                        ),
                    }
                    if name == "reuse" and result.visualizations:
                        row["issues"].append("redrawn_visual")
                except Exception as exc:
                    row = {
                        "case": name,
                        "repeat": repeat,
                        "issues": ["error"],
                        "error": str(exc),
                        "cause": str(exc.__cause__ or ""),
                    }
                row["ms"] = round((time.perf_counter() - started) * 1000)
                row["model"] = settings.voice_llm_model
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    print(
        json.dumps(
            {
                "summary": {
                    "runs": len(results),
                    "clean": sum(not r["issues"] for r in results),
                    "median_ms": statistics.median(r["ms"] for r in results),
                    "issues": {
                        issue: sum(issue in r["issues"] for r in results)
                        for issue in sorted({i for r in results for i in r["issues"]})
                    },
                }
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--case", action="append")
    asyncio.run(main(parser.parse_args()))
