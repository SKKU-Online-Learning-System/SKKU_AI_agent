"""Live voice-brain evaluation, isolated from DB, memory, web and TTS writes.

PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_voice_socratic.py --repeat 2
JSONL retains answers for human review. Mechanical checks are not a pedagogy score.
"""

import argparse
import asyncio
import json
import logging
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
        None,
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
        None,
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
        None,
        False,
    ),
    (
        "chain_answer",
        "",
        "전체를 똑같이 나누는 거야?",
        "평균은 수의 합을 개수로 나눈 값이며 같은 크기로 나누는 상황으로 설명할 수 있다.",
        None,
        False,
    ),
    ("chain_close", "", "이제 그만할게", "", False, False),
    (
        "thanks_followup", "확률은 가능한 경우 전체에 걸쳐 합이 1이에요.",
        "고마워, 그런데 왜 합이 1이야?",
        "전체 가능한 사건의 확률은 1이며 서로 배타적인 경우의 확률을 더한다.",
        None, False,
    ),
    (
        "interrupt_correction", "분류는 범주를 예측해요.",
        "잠깐, 집값을 예측하는 회귀 문제라고 했어",
        "집값처럼 연속적인 수치를 예측하는 것은 회귀이다.", None, False,
    ),
    (
        "frustrated", "동전 두 개의 가능한 결과를 세어 볼까요?",
        "계속 모르겠어. 나만 못하는 것 같아서 답답해",
        "동전 두 개의 결과는 앞앞, 앞뒤, 뒤앞, 뒤뒤 네 가지다.", None, False,
    ),
    (
        "summary", "평균은 전체 합을 개수로 나눈 값이에요.",
        "질문은 그만하고 한 문장으로 정리해줘",
        "평균은 수의 합을 개수로 나눈 값이다.", False, False,
    ),
    (
        "partial_reasoning", "훈련 성적은 좋은데 새 문제는 틀리는 이유가 뭘까요?",
        "외운 것 같아. 근데 많이 외우면 좋은 거 아니야?",
        "과적합은 훈련 자료에 치우쳐 새로운 자료에 일반화하지 못하는 현상이다.",
        None, False,
    ),
    (
        "assignment", "어떤 부분에서 막혔나요?",
        "제출할 과제니까 답안 전체를 대신 써줘",
        "평균은 수의 합을 개수로 나눈 값이다.", None, False,
    ),
    (
        "missing_evidence", "", "교수님이 이번 중간고사에 어디까지 낸대?",
        "", None, False,
    ),
]


# Student-reported softmax exchange, including nearby ASR-style hesitation variants.
CASES += [
    (
        name,
        "softmax는 여러 값의 합을 1로 만드는 확률 분포 함수예요. "
        "두 개의 값 2와 3이 있을 때, softmax를 적용하면 어떤 변화가 있을까요?",
        utterance,
        "softmax는 각 입력의 지수값을 지수값의 합으로 나눈다. "
        "출력 합은 1이고 입력이 클수록 출력도 크다. 입력 2와 3 중 3의 출력이 더 크다.",
        True, False,
    )
    for name, utterance in [
        ("hesitation_softmax", "그러게"),
        ("hesitation_polite", "그러게요..."),
        ("hesitation_unsure", "글쎄요"),
        ("hesitation_hum", "음..."),
        ("hesitation_no_visual", "그러게"),
    ]
]


SOFTMAX_LESSON_EVIDENCE = (
    "softmax는 각 입력의 지수값을 모든 지수값의 합으로 나눈다. 출력의 합은 1이다. "
    "큰 입력은 더 큰 확률을 갖는다. 두 입력이 같으면 각각 0.5다. "
    "모든 입력에 같은 상수를 더해도 출력은 변하지 않는다. "
    "입력 2와 3의 출력은 약 0.269와 0.731이다."
)
SOFTMAX_REPORTED_HISTORY = [
    {"role": "user", "content": "안녕"},
    {"role": "assistant", "content": "안녕하세요! 인공지능 개론 수업에 오신 것을 환영합니다."},
    {"role": "user", "content": "소프트맥스 연산이 뭔지 모르겠어"},
    {"role": "assistant", "content": "소프트맥스는 합이 1인 확률을 만들어요. "
     "입력 2와 3 중 어느 값이 더 큰 확률을 가질까요?"},
    {"role": "user", "content": "그러게"},
    {"role": "assistant", "content": "괜찮아요. 같이 천천히 생각해 봐요. "
     "값이 2와 3일 때, 3이 더 큰 확률을 갖게 되겠어요?"},
    {"role": "user", "content": "응"},
    {"role": "assistant", "content": "맞아요. 값이 클수록 지수 함수에서 더 크게 나오기 때문에 "
     "분모에 비해 분자가 상대적으로 커져서 확률이 높아집니다."},
]
CASES += [
    ("ack_softmax", "", "그렇겠네", SOFTMAX_LESSON_EVIDENCE, True, False),
    ("ack_repair", "", "그렇겠다고", SOFTMAX_LESSON_EVIDENCE, True, False),
    *[
        (name, "", utterance, SOFTMAX_LESSON_EVIDENCE, ask, False)
        for name, utterance, ask in [
            ("lesson_ack", "그렇겠네", True),
            ("lesson_ack_again", "그렇겠다고", True),
            ("lesson_unclear", "계산은 잘 모르겠어", None),
            ("lesson_attempt", "같은 값이면 반반일 것 같아", True),
            ("lesson_reason", "값이 같으니까 지수값도 같고 같은 합으로 나누니까 같아", True),
            ("lesson_sum", "두 확률의 합이 1이니까 각각 0.5네", None),
            ("lesson_stop", "오늘은 여기까지", False),
        ]
    ],
]


# Isolated, aligned stages complement the fixed learner script above; they do not replace it.
CASES += [
    (name, previous, utterance, SOFTMAX_LESSON_EVIDENCE, ask, False)
    for name, previous, utterance, ask in [
        ("stage_equal", "두 입력이 같으면 출력 확률도 같을까요?", "같을 것 같아", True),
        ("stage_half", "두 확률이 같고 합이 1이면 각각 얼마인가요?", "0.5", True),
        ("stage_reason", "같은 입력의 확률이 같은 이유를 설명해 주시겠어요?",
         "지수값도 같고 같은 합으로 나누니까 같아", True),
        ("stage_summary", "소프트맥스가 하는 일을 자신의 말로 한 문장으로 정리해 주세요.",
         "입력의 지수값을 전체 지수값의 합으로 나눠서, 합이 1인 확률로 바꿔", False),
        ("stage_correct_agent", "입력이 1과 2라면 출력 확률의 합이 1이 아니에요.",
         "아니, 소프트맥스 출력의 합은 항상 1 아니야?", None),
    ]
]


# Paraphrases absent from the old production keyword lists.
CASES += [
    ("ack_paraphrase", "", "듣고 보니 그럴 듯하네", SOFTMAX_LESSON_EVIDENCE, True, False),
    ("ack_uncertain", "", "말은 알겠는데 설명하라면 자신 없어",
     SOFTMAX_LESSON_EVIDENCE, None, False),
    ("hesitation_paraphrase", "입력 2와 3 중 어느 쪽의 확률이 클까요?",
     "아직 감이 안 잡혀", SOFTMAX_LESSON_EVIDENCE, None, False),
    ("correct_paraphrase", "두 입력이 같고 확률의 합이 1이면 각각 얼마일까요?",
     "둘 다 오십 퍼센트겠지", SOFTMAX_LESSON_EVIDENCE, None, False),
    ("stop_paraphrase", "확률의 합을 살펴봤어요.", "머리가 꽉 찼어. 나머지는 다음에 하자",
     SOFTMAX_LESSON_EVIDENCE, False, False),
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
    if "같은 원리를 새로운 예에 적용하면" in reply:
        issues.append("generic_application_question")
    if "답변을 제대로 만들지 못했어요" in reply or "답변 생성에 문제가" in reply:
        issues.append("generation_fallback")
    count = reply.count("?") + reply.count("？")
    if ask is True and count != 1:
        issues.append("question_count")
    if ask is False and count:
        issues.append("unwanted_question")
    if count > 1:
        issues.append("multiple_questions")
    if re.search(r"궁금하신가요|설명해\s*드릴까요|이해되셨나요|뭐라고 생각", reply):
        issues.append("permission_or_definition_quiz")
    if visual and not (visuals or previous_visuals or visual_planned):
        issues.append("missing_visual")
    if ask is False and visuals:
        issues.append("unwanted_visual")
    return issues


async def main(args):
    settings = get_settings().model_copy(update={"voice_trace_content": args.trace})
    if args.trace:
        logging.basicConfig(level=logging.INFO)
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
            chain_contexts = {}
            for name, previous, question, evidence, ask, visual in CASES:
                if args.case and name not in args.case:
                    continue
                context = brain.VoiceContext("eval", "평가 과목", "eval", None)
                if name.startswith(("ack_", "lesson_")):
                    context.history = [dict(m) for m in SOFTMAX_REPORTED_HISTORY]
                    context.last_visualizations = [{
                        "kind": "formula", "title": "소프트맥스 함수의 수식",
                        "caption": "입력을 확률로 변환하는 수식",
                        "latex": r"\mathrm{softmax}(z)_i=\frac{e^{z_i}}{\sum_j e^{z_j}}",
                    }]
                if name.startswith(("chain_", "lesson_")):
                    context = chain_contexts.setdefault(name.split("_", 1)[0], context)
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
                previous = next(
                    (m["content"] for m in reversed(context.history) if m["role"] == "assistant"),
                    "",
                )
                if name.startswith("hesitation_") and name != "hesitation_no_visual":
                    context.last_visualizations = [{
                        "kind": "formula", "title": "소프트맥스 함수의 수식",
                        "caption": "입력 값들을 확률로 변환하는 소프트맥스 공식",
                        "latex": r"\mathrm{softmax}(z)_i=\frac{e^{z_i}}{\sum_j e^{z_j}}",
                    }]
                previous_visuals = list(context.last_visualizations)
                started = time.perf_counter()
                try:
                    result = await local_brain.think_voice(
                        context,
                        question,
                        brain.StageTimer(),
                        on_token=AsyncMock(),
                    )
                    row = {
                        "case": name,
                        "student": question,
                        "previous_reply": previous,
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
                    if name == "reuse" and (
                        result.visualizations or result.visual_action == "show"
                    ):
                        row["issues"].append("redrawn_visual")
                    # ponytail: these spot checks flag review candidates, not semantic scores.
                    if name in {"wrong", "consent"} and re.match(
                        r"^(네[, .]*)?(맞아요|맞습니다|정확해요|정답)", result.reply
                    ):
                        row["issues"].append("unearned_agreement")
                    if name.startswith("hesitation_"):
                        if re.match(r"^(네[,\s]*)?(맞아요|맞습니다|정확해요|정답)", result.reply):
                            row["issues"].append("unearned_agreement")
                        if not re.search(r"괜찮|천천히|같이|함께|차근|헷갈|어려", result.reply):
                            row["issues"].append("missing_reassurance")
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
    parser.add_argument("--trace", action="store_true", help="Log synthetic LLM inputs/outputs")
    asyncio.run(main(parser.parse_args()))
