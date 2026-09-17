"""Live production voice brain with actual course RAG; no learner history writes.

Set DATABASE_URL to the lecture DB and PYTHONPATH=apps/backend.
--student continues an evaluator-chosen dialogue stored in --output.
Only memory recall/background memory writes are disabled, not RAG or model inference.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.core.config import get_settings
from app.services.llm_service import LLMService
from app.services.voice import brain, local_brain

CASES = [
    ("causal_wrong", "인과 마스크를 공부하자", "인과 마스크에서 3번 행은 어느 열까지 볼 수 있을까요?",
     "0번부터 7번까지 전부 볼 수 있어요"),
    ("causal_correct", "인과 마스크를 공부하자", "인과 마스크에서 3번 행은 어느 열까지 볼 수 있을까요?",
     "0번부터 3번까지요"),
    ("causal_unsure", "인과 마스크를 공부하자", "인과 마스크에서 3번 행은 어느 열까지 볼 수 있을까요?",
     "말은 알겠는데 아직 감이 안 와"),
    ("causal_consent", "인과 마스크를 공부하자", "인과 마스크에서 3번 행을 함께 살펴볼까요?", "응"),
    ("softmax_wrong", "소프트맥스를 공부하자", "소프트맥스에서 지수값을 무엇으로 나눌까요?",
     "가장 큰 값으로 나눠요"),
    ("softmax_hesitation", "소프트맥스를 공부하자", "입력 두 개가 같으면 확률도 같을까요?",
     "그러게요..."),
    ("diagram_heads", "", "", "MHA, MQA, GQA 그림에서 키와 값의 헤드 수는 어떻게 달라?"),
    ("diagram_axes", "", "", "사인 위치 인코딩 그림에서 가로축과 세로축은 뭐야?"),
    ("topic_switch", "인과 마스크를 공부하자", "3번 행은 어디까지 볼 수 있을까요?",
     "그거 말고 RoPE가 회전한다는 게 궁금해"),
    ("missing_evidence", "", "", "이 강의자료에서 기회비용을 어떻게 정의해?"),
    ("pause", "인과 마스크를 공부하자", "3번 행은 어디까지 볼 수 있을까요?", "잠깐 기다려줘"),
    ("closing", "인과 마스크를 공부하자", "3번 행은 어디까지 볼 수 있을까요?", "고마워 오늘은 여기까지"),
]


async def run_turn(context, student):
    trace = {"requests": [], "image_reads": [], "prefetch": None}
    real_prefetch = brain.prefetch_context
    real_llm = LLMService.stream_tool_turn
    real_read = LLMService.read_document_image

    async def prefetch(*args, **kwargs):
        value = await real_prefetch(*args, **kwargs)
        trace["prefetch"] = value
        return value

    async def llm(self, **kwargs):
        start = time.perf_counter()
        record = {k: v for k, v in kwargs.items() if not callable(v)}
        trace["requests"].append(record)
        try:
            value = await real_llm(self, **kwargs)
            record["response"] = asdict(value)
            return value
        finally:
            record["elapsed_ms"] = round((time.perf_counter()-start)*1000)

    def read(self, url, question=""):
        start = time.perf_counter()
        record = {"question": question}
        trace["image_reads"].append(record)
        try:
            value = real_read(self, url, question)
            record["evidence"] = value
            return value
        finally:
            record["elapsed_ms"] = round((time.perf_counter()-start)*1000)

    timer = brain.StageTimer()
    start = time.perf_counter()
    released_ms = None

    async def speech(text):
        nonlocal released_ms
        if released_ms is None:
            released_ms = round((time.perf_counter()-start)*1000)

    before = [dict(m) for m in context.history]
    with (patch.object(brain, "prefetch_context", prefetch),
          patch.object(brain, "recent_weak_concepts", AsyncMock(return_value={"found": False})),
          patch.object(LLMService, "stream_tool_turn", llm),
          patch.object(LLMService, "read_document_image", read),
          patch("app.services.voice.session_store.external_brain_for",
                return_value=SimpleNamespace(schedule=Mock()))):
        try:
            result = await local_brain.think_voice(context, student, timer, on_token=speech)
            outcome = asdict(result)
        except Exception as exc:
            outcome = {"error": str(exc), "cause": str(exc.__cause__ or "")}
    return {"student": student, "history_before": before, "history_after": context.history,
            **outcome, "elapsed_ms": round((time.perf_counter()-start)*1000),
            "speech_released_ms": released_ms, "timings_ms": timer.timings_ms,
            "citations": context.last_material_sources, "trace": trace}


async def main(args):
    settings = get_settings()
    assert settings.embedding_provider == "qwen" and not settings.use_mock_llm
    assert settings.voice_llm_model == "Qwen/Qwen3.5-9B"
    path = Path(args.output)
    existing = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    cases = [(args.session, "", "", args.student)] if args.student else [
        case for case in CASES if not args.case or case[0] in args.case
    ]
    for repeat in range(args.repeat):
        for name, topic, previous, student in cases:
            context = brain.VoiceContext(args.course_id, "Transformer 강의", "voice-eval", None)
            if topic:
                context.history = [{"role": "user", "content": topic},
                                   {"role": "assistant", "content": previous}]
            if args.student:
                prior = [row for row in existing if row["case"] == args.session]
                if prior:
                    context.history = prior[-1]["history_after"]
            row = await run_turn(context, student)
            row.update(case=name, repeat=repeat)
            with path.open("a") as output:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(json.dumps({k: v for k, v in row.items()
                              if k not in {"trace", "history_before", "history_after"}},
                             ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", default="384a5d06-f329-4e51-8b42-f817273df9c2")
    parser.add_argument("--output", default="docs/evaluations/voice-post-rag-live-20260911.jsonl")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--session", default="dialogue")
    parser.add_argument("--student")
    parser.add_argument("--case", action="append", choices=[case[0] for case in CASES])
    asyncio.run(main(parser.parse_args()))
