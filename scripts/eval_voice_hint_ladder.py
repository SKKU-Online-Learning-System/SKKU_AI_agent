"""Multi-turn hint-ladder evaluation against the live model servers.

PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_voice_hint_ladder.py --path voice --tag after --repeat 2

Scripted students (a new concept, "모르겠어" three times, a partial answer, a wrong
answer, an explicit request for the answer) are driven through the real brain with
prefetch and tools patched, and the 27B text model judges every tutor turn: did it
reveal the answer, end in one question, give a scaffold, respond to the student.
The judge is a review aid, not a pedagogy score; the JSONL keeps the replies.

``--no-guards`` switches off the two server rules added against the repeated probe
(the quoted previous question and the rule-based ``stuck`` override) so the same
run can be compared with and without them; ``repeated_question`` in the summary
counts tutor turns whose closing question is the one the student already failed.

Measured on Qwen3.5-9B before and after the ladder (hint turns only, i.e. excluding
the two turns where the student explicitly asks to be told):
    before  reveals the answer 12/12, ends in a question 1/12,  scaffold 0/12
    after   reveals the answer  5/24, ends in a question 23/24, scaffold 19/24
"""

import argparse
import asyncio
import json
import time
import re
from difflib import SequenceMatcher
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.core.config import get_settings
from app.services.voice import brain, local_brain

SDPA = (
    "Scaled Dot Product. The dot-product score is a sum over d dimensions. As the key dimension "
    "d_k grows, the variance of this score also grows. Then softmax can become overly sharp, which "
    "may lead to very small gradients. To stabilize training, we scale the score by sqrt(d): "
    "s = q^T k / sqrt(d) (scaled dot-product). Scaled dot-product attention: alpha = softmax(s), "
    "y = sum alpha_k v_k. The current input attends to previous inputs by query-key similarity and "
    "aggregates their values using adaptive weights."
)
SOFTMAX = (
    "From Scores to Attention Weights. Convert the scores into normalized weights using softmax: "
    "alpha_k = exp(s_k) / sum_j exp(s_j). This is still a weighted sum, but now the coefficients "
    "depend on the input. Outputs are positive and sum to 1; a larger score gets a larger weight."
)

SCENARIOS = {
    "sdpa_user_case": (
        SDPA,
        [
            "안녕.",
            "스케일드닷 프로덕터 텐션이 뭔지 모르겠어.",
            "모르겠어.",
            "음... 그것도 잘 모르겠어.",
            "그냥 답 알려주면 안 돼?",
        ],
    ),
    "softmax_stuck": (
        SOFTMAX,
        [
            "소프트맥스 연산이 뭐야?",
            "모르겠어.",
            "그러게.",
        ],
    ),
    "softmax_partial": (
        SOFTMAX,
        [
            "소프트맥스 연산이 뭐야?",
            "점수들을 확률처럼 합이 1이 되게 바꾸는 거 아니야?",
            "큰 점수가 더 큰 확률을 받겠지.",
        ],
    ),
    "sdpa_wrong": (
        SDPA,
        [
            "어텐션에서 점수를 왜 루트 d로 나눠?",
            "값이 너무 작아져서 키우려고 나누는 거 아니야?",
        ],
    ),
    "sdpa_asks_directly": (
        SDPA,
        [
            "스케일드 닷 프로덕트 어텐션 설명해줘.",
            "정리해서 한 문장으로 말해줘.",
        ],
    ),
}

JUDGE_PROMPT = """당신은 소크라테스식 튜터링 품질 심사자입니다. 아래 튜터의 한 턴을 평가하세요.

[강의자료 요지]
{evidence}

[대화 맥락 (마지막이 평가 대상 튜터 발화)]
{dialogue}

다음 JSON만 출력하세요 (설명 없이):
{{"reveals_answer": true/false,   // 학생이 질문한 개념의 정의나 핵심 답(예: '왜 루트 d로 나누는지')을 튜터가 직접 말해버렸는가
 "ends_with_one_question": true/false, // 학생이 답할 수 있는 구체적 질문이 정확히 하나 있는가
 "gives_scaffold": true/false,    // 정답을 말하지 않고 학생이 스스로 답에 다가갈 수 있는 힌트/연결고리를 주는가
 "responds_to_student": true/false, // 학생의 직전 발화(모름/오답/부분정답)에 실제로 반응하는가
 "note": "한 줄 근거"}}"""


async def judge(settings, evidence, dialogue):
    prompt = JUDGE_PROMPT.format(evidence=evidence, dialogue=dialogue)
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            settings.text_llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.model_server_api_key}"},
            json={
                "model": settings.text_llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 300,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {"raw": text}
    except json.JSONDecodeError:
        return {"raw": text}


async def main(args):
    settings = get_settings()
    if settings.use_mock_llm:
        raise RuntimeError("live LLM required")

    async def prefetch(context, question, timer):
        return {
            "student_question": question,
            "weak_concepts": {"found": False, "memories": []},
            "course_materials": {
                "found": True,
                "results": [
                    {"file": "lecture.pdf", "page": 8, "excerpt": context.evidence}
                ],
            },
        }

    async def run_tool(context, name, arguments, timer):
        if name == "show_visualization":
            try:
                return brain.show_visualization(**arguments)
            except (ValueError, TypeError) as exc:
                return json.dumps({"error": str(exc)})
        if name in {"recall_weak_concepts"}:
            return json.dumps({"found": False, "memories": []})
        if name == "search_course_materials":
            return json.dumps(
                {
                    "found": True,
                    "results": [
                        {"file": "lecture.pdf", "page": 8, "excerpt": context.evidence}
                    ],
                }
            )
        return '{"found":false,"sources":[],"error":"offline"}'

    rows = []
    guards = (
        [
            patch.object(brain, "last_assistant_question", lambda context: ""),
            patch.object(brain, "rule_based_student_state", lambda context, transcript: None),
        ]
        if args.no_guards
        else []
    )
    for guard in guards:
        guard.start()
    with (
        patch.object(local_brain, "get_settings", return_value=settings),
        patch.object(brain, "prefetch_context", new=prefetch),
        patch.object(brain, "run_tool", new=run_tool),
        patch(
            "app.services.voice.session_store.external_brain_for",
            return_value=SimpleNamespace(schedule=Mock()),
        ),
    ):
        for name, (evidence, turns) in SCENARIOS.items():
            if args.scenario and name not in args.scenario:
                continue
            for rep in range(args.repeat):
                context = brain.VoiceContext("eval", "인공지능개론", "eval", None)
                context.evidence = evidence
                print(f"\n===== {name} (rep {rep}, path={args.path}) =====")
                for student in turns:
                    t0 = time.perf_counter()
                    previous_question = brain.last_question_sentence(
                        brain.last_assistant_turn(context)
                    )
                    student_state = ""
                    try:
                        if args.path == "voice":
                            res = await local_brain.think_voice(
                                context,
                                student,
                                brain.StageTimer(),
                                on_token=AsyncMock(),
                            )
                            reply, visuals = res.reply, res.visualizations
                            student_state = res.student_state
                        else:
                            reply, _tools, _src, visuals = await brain.think(
                                context, student, brain.StageTimer()
                            )
                    except Exception as exc:
                        reply, visuals = f"<<ERROR {type(exc).__name__}: {exc}>>", []
                        context.append_history({"role": "user", "content": student})
                        context.append_history({"role": "assistant", "content": reply})
                    ms = round((time.perf_counter() - t0) * 1000)
                    dialogue = "\n".join(
                        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
                        for m in context.history
                    )
                    verdict = (
                        await judge(settings, evidence, dialogue)
                        if not reply.startswith("<<")
                        else {}
                    )
                    repeated = bool(previous_question) and _same_question(
                        previous_question, brain.last_question_sentence(reply)
                    )
                    print(f"학생: {student}")
                    print(
                        f"튜터 ({ms} ms, state={student_state or '-'} level={context.hint_level}"
                        f"{' REPEATED QUESTION' if repeated else ''}): {reply}"
                    )
                    if visuals:
                        print(
                            f"   [visual] {visuals[0].get('kind')} / {visuals[0].get('title')} / {visuals[0].get('caption')}"
                        )
                    print(f"   judge: {json.dumps(verdict, ensure_ascii=False)}")
                    rows.append(
                        {
                            "scenario": name,
                            "rep": rep,
                            "student": student,
                            "reply": reply,
                            "ms": ms,
                            "judge": verdict,
                            "tag": args.tag,
                            "path": args.path,
                            "student_state": student_state,
                            "hint_level": context.hint_level,
                            "repeated_question": repeated,
                        }
                    )
    for guard in guards:
        guard.stop()
    out = f"{args.out}/{args.tag}_{args.path}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # summary
    teach = [r for r in rows if r["judge"] and not r["student"].startswith("안녕")]

    def rate(k):
        vals = [r["judge"].get(k) for r in teach if isinstance(r["judge"].get(k), bool)]
        return f"{sum(vals)}/{len(vals)}"

    followups = [r for r in rows if not r["reply"].startswith("<<") and r["student"] != turns_first(rows, r)]
    repeated = sum(r["repeated_question"] for r in followups)
    print(
        f"\n### {args.tag}/{args.path}: reveals_answer={rate('reveals_answer')}  one_question={rate('ends_with_one_question')}  scaffold={rate('gives_scaffold')}  responds={rate('responds_to_student')}  repeated_question={repeated}/{len(followups)}  errors={sum(r['reply'].startswith('<<') for r in rows)}"
    )


def turns_first(rows, row):
    """The opening student turn of ``row``'s scenario, which has no question to repeat."""
    return SCENARIOS[row["scenario"]][1][0]


def _same_question(asked: str, asking: str) -> bool:
    a, b = brain._compact(asked), brain._compact(asking)
    if len(a) < 6 or len(b) < 6:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= brain.REPEAT_RATIO


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--path", default="voice", choices=["voice", "text"])
    p.add_argument("--tag", default="baseline")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--scenario", nargs="*")
    p.add_argument("--out", default="uploads/voice")
    p.add_argument("--no-guards", action="store_true", help="disable the quoted previous question and the stuck override")
    asyncio.run(main(p.parse_args()))
