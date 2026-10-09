"""One evaluator-chosen learner turn against the same plain Qwen tutor; synthetic only."""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.llm_service import LLMService
from eval_voice_output_modes import PLAIN_POLICY


def request_for(rows, session, student, evidence):
    history = [row for row in rows if row['session'] == session]
    if history:
        previous = history[-1]
        assert not evidence, 'Supply evidence only when starting a session'
        system = previous['request']['system']
        messages = [*previous['request']['messages'],
                    {'role': 'assistant', 'content': previous['reply']}]
    else:
        assert evidence, 'A new synthetic session needs reference evidence'
        system = PLAIN_POLICY + '\n참고 자료:\n' + evidence
        messages = []
    return dict(system=system, messages=[*messages, {'role': 'user', 'content': student}],
                tools=[], force_tools=[], max_tokens=320)


async def main(args):
    path = Path(args.output)
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    request = request_for(rows, args.session, args.student, args.evidence)
    settings = get_settings()
    assert settings.voice_llm_model == 'Qwen/Qwen3.5-9B' and not settings.use_mock_llm
    llm = LLMService(settings, profile='voice')
    assert llm.provider == 'local_qwen'
    start = time.perf_counter()
    first_token_ms = None

    async def token(text):
        nonlocal first_token_ms
        if text and first_token_ms is None:
            first_token_ms = round((time.perf_counter() - start) * 1000)

    result = await llm.stream_tool_turn(**request, on_token=token)
    assert result.text.strip() and not result.tool_calls, 'Expected plain speech, no tools'
    row = dict(session=args.session, student=args.student, request=request, reply=result.text,
               model=result.model_name, temperature=settings.llm_temperature,
               enable_thinking=False, first_token_ms=first_token_ms,
               ms=round((time.perf_counter() - start) * 1000))
    with path.open('a') as output:
        output.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in row.items() if k != 'request'},
                     ensure_ascii=False), flush=True)


def self_check():
    first = request_for([], 'a', '질문', '근거')
    rows = [dict(session='a', request=first, reply='어느 쪽일까요?')]
    next_turn = request_for(rows, 'a', '모르겠어', None)
    assert next_turn['messages'] == [*first['messages'],
        {'role': 'assistant', 'content': '어느 쪽일까요?'},
        {'role': 'user', 'content': '모르겠어'}]
    assert next_turn['system'] == first['system']
    assert next_turn['tools'] == [] and next_turn['force_tools'] == []
    assert len(request_for(rows, 'b', '새 질문', '다른 근거')['messages']) == 1
    assert len(first['messages']) == 1
    print('Dialogue history checks passed (no model calls)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='docs/evaluations/voice-plain-dialogue-20260911.jsonl')
    parser.add_argument('--session')
    parser.add_argument('--student')
    parser.add_argument('--evidence')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        assert args.session and args.student
        asyncio.run(main(args))
