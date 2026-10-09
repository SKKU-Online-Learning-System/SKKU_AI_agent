"""Paired frozen-context comparison; test-only, no production writes."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from statistics import median

from app.core.config import get_settings
from app.services.llm_service import LLMService
from eval_voice_stage_controller import Assessment, Lesson, STEPS, phrase_reply

BASELINE = Path('docs/evaluations/voice-stage-controller-split-intent-20260910.jsonl')
SELECTED = {
    ('hesitate_then_finish', 0), ('hesitate_then_finish', 1),
    ('hesitate_then_finish', 2), ('hesitate_then_finish', 3),
    ('hesitate_then_finish', 4), ('wrong_then_correct', 0),
    ('paraphrase_then_pause', 2), ('mixed_stop', 0),
}


def snapshots():
    histories = {}
    cases = []
    for row in map(json.loads, BASELINE.read_text().splitlines()):
        if row['repeat'] != 0:
            continue
        history = histories.setdefault(row['scenario'], [
            {'role': 'assistant', 'content': STEPS[0][1]}])
        if (row['scenario'], row['turn']) in SELECTED:
            cases.append(dict(name=f"{row['scenario']}:{row['turn']}",
                stage=row['stage_before'], student=row['student'],
                history=list(history), request=row['request']))
        history.extend([{'role':'user','content':row['student']},
                        {'role':'assistant','content':row['reply']}])
    assert len(cases) == len(SELECTED)
    return cases


def simple_request(case):
    # ponytail: snapshots isolate response behavior, not autonomous conversation success.
    goal, _, reference, _ = STEPS[case['stage']]
    return dict(
        system=('한국어 음성 학습 튜터다. 180자 이내 2~3문장으로 자연스럽게 답하라. '
                '학생이 모르면 부담 없이 쉬운 힌트를 주고, 수긍만으로 이해했다고 칭찬하지 마라. '
                '정답이면 그 답만 짧게 인정하고 다음 이해 확인 질문 하나로 이어가라. '
                '현재 개념을 충분히 확인할 때까지 돕되 중단 요청은 존중하라. '
                '학습 순서: 같은 입력의 확률 → 같은 확률인 이유 → 소프트맥스 요약. '
                f'현재 목표: {goal}. 참고 사실: {reference}'),
        messages=[*case['history'], {'role':'user','content':case['student']}],
        tools=[], max_tokens=320)


async def run_case(llm, case, mode):
    row = dict(case=case['name'],mode=mode,stage_before=case['stage'],
               student=case['student'],history=case['history'],calls=0)
    started = time.perf_counter()
    try:
        request = simple_request(case) if mode == 'simple' else case['request']
        row['request'] = request
        row['calls'] += 1
        result = await llm.stream_tool_turn(**request)
        row['raw'] = dict(text=result.text,calls=[
            dict(name=c.name,arguments=c.arguments) for c in result.tool_calls])
        if mode == 'simple':
            if result.tool_calls or not result.text.strip() or len(result.text.strip()) > 180:
                raise ValueError('Expected nonempty plain speech up to 180 characters')
            row['reply'] = result.text.strip()
        else:
            if len(result.tool_calls)!=1 or result.tool_calls[0].name!='assess_answer':
                raise ValueError('Expected one assessment')
            assessment = Assessment.model_validate(result.tool_calls[0].arguments)
            row['assessment'] = assessment.model_dump()
            lesson = Lesson(stage=case['stage'])
            row['reply'] = lesson.apply(assessment,case['student'])
            if not lesson.stopped and lesson.stage < len(STEPS):
                row['calls'] += 1
                try:
                    row['reply'] = await phrase_reply(
                        llm,lesson,assessment,case['history'],case['student'],row)
                except Exception as exc:
                    row['speech_error'] = f'{type(exc).__name__}: {exc}'
            row['stage_after'] = lesson.stage
            row['stopped'] = lesson.stopped
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {exc}'
    row['ms'] = round((time.perf_counter()-started)*1000)
    return row


def self_check():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    cases = snapshots()
    for case in cases:
        request = simple_request(case)
        assert request['messages'][:-1] == case['history']
        assert request['messages'][-1]['content'] == case['student']
        assert request['tools'] == [] and 'assessment' not in request['system']
        original = json.loads(case['request']['messages'][0]['content'])
        assert original['student'] == case['student']
        assert original['previous_teacher'] == case['history'][-1]['content']
    assert len({case['name'] for case in cases}) == 8
    llm = SimpleNamespace(stream_tool_turn=AsyncMock(return_value=SimpleNamespace(
        text='같이 생각해 봐요.',tool_calls=[])))
    row = asyncio.run(run_case(llm,cases[0],'simple'))
    assert row['calls'] == 1 and row['reply'] == '같이 생각해 봐요.' and 'error' not in row
    llm.stream_tool_turn.return_value.text = ''
    assert 'error' in asyncio.run(run_case(llm,cases[0],'simple'))
    llm.stream_tool_turn.return_value = SimpleNamespace(text='',tool_calls=[
        SimpleNamespace(name='assess_answer',arguments=dict(
            intent='pause',verdict='insufficient',evidence=''))])
    row = asyncio.run(run_case(llm,cases[0],'complex'))
    assert row['calls'] == 1 and row['stopped'] and row['stage_after'] == 0
    print('Paired snapshot checks passed')


async def main():
    settings = get_settings().model_copy(update={
        'voice_llm_model':'Qwen/Qwen3.5-9B','voice_llm_base_url':'http://localhost:8002/v1'})
    llm = LLMService(settings,profile='voice')
    assert llm.provider == 'local_qwen'
    for repeat in range(2):
        for index, case in enumerate(snapshots()):
            order = ['complex','simple'] if (repeat+index)%2 == 0 else ['simple','complex']
            for mode in order:
                row = await run_case(llm,case,mode)
                row.update(repeat=repeat,model=llm.model_name,
                           temperature=settings.llm_temperature,max_tokens_per_call=320)
                print(json.dumps(row,ensure_ascii=False),flush=True)


def check_file(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    expected = {(repeat,c['name'],mode) for repeat in range(2)
                for c in snapshots() for mode in ['complex','simple']}
    assert len(rows) == len(expected) == 32
    assert {(r['repeat'],r['case'],r['mode']) for r in rows} == expected
    for mode in ['complex','simple']:
        group = [r for r in rows if r['mode'] == mode]
        print(mode, 'median_ms=',median(r['ms'] for r in group),
              'calls=',sum(r['calls'] for r in group),
              'errors=',sum(bool(r.get('error') or r.get('speech_error')) for r in group))
    assert all(not r.get('error') and not r.get('speech_error') for r in rows)
    print('Completeness/format checks only; semantic quality requires output review.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--check-file')
    args = parser.parse_args()
    if args.check_file:
        check_file(args.check_file)
    elif args.self_check:
        self_check()
    else:
        asyncio.run(main())
