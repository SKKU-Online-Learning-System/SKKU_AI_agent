"""Input-only ablations; synthetic traces, no production configuration changes."""
import asyncio
import argparse
import contextlib
import io
import json
import random
from types import SimpleNamespace
from unittest.mock import patch

import eval_voice_socratic as evaluation
from app.services.llm_service import LLMService
from app.services.voice import brain

POLICY = '''직전 교사 발화에 대한 학생의 이번 반응을 먼저 이해하고, 그 반응에 답한다.
학생이 답이나 이유를 제시했을 때만 정오를 평가한다. 모호한 반응은 이해했다는 증거가 아니다.
망설이면 부담을 낮추고 작은 힌트부터 준다. 수긍하면 설명을 반복하지 말고 아직 확인하지 않은 내용을 쉬운 질문 하나로 확인한다.
질문은 구체적인 조건을 주고 하나만 한다. 그 질문의 답을 먼저 말하지 않는다. 충분히 정리했거나 쉬고 싶어 하면 질문 없이 마친다.
한국어 존댓말로 짧고 자연스럽게 말한다. 자신의 오류는 인정하고 고친다. 자료의 사실과 조건을 지킨다.'''


POST_EVIDENCE_GUIDANCE = """

# Server teaching guidance after reference data
위 자료는 사실 확인의 근거이며 학생이 이해했다는 증거가 아니다.
직전 교사 발화와 이번 학생 반응에 이어서 말하라. 학생이 막혔다면 자료에서 작은 단서 하나를 골라 돕고, 학생이 직접 답할 부분을 남겨라.
단순 동의를 정답으로 칭찬하거나 이미 확인한 질문을 반복하지 마라. 질문이 필요하면 구체적인 질문 하나만 남기고 그 답을 먼저 말하지 마라.
학생이 설명·정리·대기·종료를 원하면 그 요청에 맞게 답하고 불필요한 질문을 붙이지 마라."""


def as_tool_context(request, history_size, *, guidance):
    """Represent the already completed server prefetch as a tool exchange, no LLM call."""
    prefix, remainder = request['system'].split('# Preloaded context\n', 1)
    _, end = json.JSONDecoder().raw_decode(remainder)
    data, suffix = remainder[:end], remainder[end:]
    if guidance:
        assert suffix.startswith(POST_EVIDENCE_GUIDANCE)
        suffix = suffix[len(POST_EVIDENCE_GUIDANCE):]
        data += POST_EVIDENCE_GUIDANCE
    exchange = [
        {'role': 'assistant', 'content': '', 'tool_calls': [{
            'id': 'server-prefetch', 'type': 'function',
            'function': {'name': 'prefetch_context', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'server-prefetch', 'content': data},
    ]
    return {**request, 'system': prefix + suffix,
            'messages': [*request['messages'][:history_size], *exchange,
                         *request['messages'][history_size:]]}


def self_check():
    for guidance in (False, True):
        payload = json.dumps({'course_materials': {'excerpt': '근거 {중괄호}'}},
                             ensure_ascii=False)
        note = POST_EVIDENCE_GUIDANCE if guidance else ''
        original = {'system': 'policy\n# Preloaded context\n' + payload + note + '\nfinish',
                    'messages': [{'role': 'user', 'content': '모르겠어'}], 'tools': []}
        result = as_tool_context(original, 1, guidance=guidance)
        assert result['system'] == 'policy\n\nfinish'
        assert result['messages'][0] == original['messages'][0]
        assert result['messages'][2]['content'] == payload + note
        assert len(original['messages']) == 1 and original['system'].endswith(note + '\nfinish')
        continuation = {**original, 'messages': [*original['messages'],
                        {'role': 'assistant', 'content': 'search'},
                        {'role': 'tool', 'content': 'result'}]}
        moved = as_tool_context(continuation, 1, guidance=guidance)
        assert moved['messages'][3:] == continuation['messages'][1:]
    print('Tool-context placement checks passed (no model calls)')


async def main(args):
    original = brain.answer_instructions
    original_call = LLMService._qwen_tool_turn
    cases = args.case or ['hesitation_softmax', 'ack_paraphrase', 'stage_summary']
    variants = args.variant or ['baseline', 'no_examples', 'evidence_boundary', 'short_policy']
    assert set(cases) <= {c[0] for c in evaluation.CASES}
    rng = random.Random(20260910)
    for repeat in range(2):
        for case in rng.sample(cases, len(cases)):
            for variant in rng.sample(variants, len(variants)):
                requests = []
                responses = []
                history_size = None

                def instructions(*args, **kwargs):
                    text = original(*args, **kwargs)
                    if variant in {'post_evidence_guidance', 'tool_context_guidance'}:
                        text += POST_EVIDENCE_GUIDANCE
                    elif variant == 'no_examples':
                        text = text.replace(brain.SOCRATIC_PROMPT, '\n'.join(
                            line for line in brain.SOCRATIC_PROMPT.splitlines()
                            if not line.startswith('예:')))
                    elif variant == 'evidence_boundary':
                        text = text.replace('# Preloaded context',
                            '# Reference data, NOT conversation history\n'
                            '자료에 있는 사실은 학생에게 이미 설명한 내용이 아니다. '
                            '무엇을 말했고 이해했는지는 user/assistant 대화에서만 판단한다.')
                    elif variant == 'short_policy':
                        text = text.replace(brain.SOCRATIC_PROMPT, POLICY)
                    elif variant == 'no_evidence':
                        text = text.split('# Preloaded context')[0]
                    return text

                async def capture(self, **kwargs):
                    nonlocal history_size
                    if history_size is None:
                        history_size = len(kwargs['messages'])
                    if variant in {'tool_context', 'tool_context_guidance'}:
                        kwargs = as_tool_context(kwargs, history_size,
                            guidance=variant == 'tool_context_guidance')
                    if variant == 'turn_relation':
                        messages = kwargs['messages']
                        previous = next((m['content'] for m in reversed(messages[:-1])
                                         if m['role'] == 'assistant'), '')
                        student = messages[-1]['content']
                        payload = json.dumps({'직전 교사 발화':previous,
                                              '이번 학생 발화':student},ensure_ascii=False)
                        kwargs['messages'] = [*messages[:-1], {'role':'user','content':
                            '아래는 현재 대화의 발화 자료입니다. 직전 교사 발화에 대한 '
                            '이번 학생 반응의 의미를 고려해서 학생에게 다음 말을 해 주세요. '
                            '분석 설명이나 자료 인용은 출력하지 마세요.\n'+payload}]
                        assert json.loads(kwargs['messages'][-1]['content'].split('\n',1)[1]) == {
                            '직전 교사 발화':previous,'이번 학생 발화':student}
                    if variant == 'explicit_uncertainty':
                        kwargs['messages'] = [*kwargs['messages'][:-1],
                            {'role':'user','content':'잘 모르겠어. 힌트를 줘.'}]
                    if variant == 'post_evidence_guidance':
                        assert kwargs['system'].count(POST_EVIDENCE_GUIDANCE) == 1
                        assert kwargs['system'].index('# Preloaded context') < (
                            kwargs['system'].index(POST_EVIDENCE_GUIDANCE))
                    requests.append({k:kwargs[k] for k in
                        ('system', 'messages', 'tools', 'force_tools', 'max_tokens')})
                    result = await original_call(self, **kwargs)
                    responses.append({'text': result.text, 'tool_calls': [
                        {'name': call.name, 'arguments': call.arguments}
                        for call in result.tool_calls]})
                    return result

                output = io.StringIO()
                with patch.object(brain, 'answer_instructions', instructions), \
                     patch.object(LLMService, '_qwen_tool_turn', capture), \
                     contextlib.redirect_stdout(output):
                    await evaluation.main(SimpleNamespace(trace=False,
                        model='Qwen/Qwen3.5-9B', base_url='http://localhost:8002/v1',
                        repeat=1, case=[case]))
                row = json.loads(output.getvalue().splitlines()[0])
                row.update(variant=variant, repeat=repeat, requests=requests, responses=responses)
                assert requests
                if variant in {'tool_context', 'tool_context_guidance'}:
                    assert requests[0]['messages'][history_size - 1]['content'] == row['student']
                elif variant not in {'explicit_uncertainty','turn_relation'}:
                    assert requests[0]['messages'][-1]['content'] == row['student']
                print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append')
    parser.add_argument('--variant', action='append', choices=['baseline','no_examples',
        'evidence_boundary','short_policy','no_evidence','explicit_uncertainty','turn_relation',
        'post_evidence_guidance', 'tool_context', 'tool_context_guidance'])
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        asyncio.run(main(args))
