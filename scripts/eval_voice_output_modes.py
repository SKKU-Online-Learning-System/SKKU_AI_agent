"""Replay synthetic inputs through LLMService; no production state changes."""
import asyncio
import argparse
import copy
import json
import random
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.llm_service import LLMService


PLAIN_POLICY = (
    '한국어로 학생과 대화하는 친절한 학습 튜터다. 직전 학생의 말에 이어서 짧고 자연스럽게 말하라. '
    '학생이 막히면 작은 도움을 주고 생각할 여지를 남겨라. '
    '질문은 필요할 때 하나만 하고, 설명이나 쉬기를 원하면 그 요청을 존중하라. '
    '아래 자료는 사실 확인용 참고다. 학생에게 할 말만 두세 문장 정도로 답하라.'
)


def plain_system(system):
    _, separator, data = system.partition('# Preloaded context\n')
    assert separator
    payload, _ = json.JSONDecoder().raw_decode(data)
    return PLAIN_POLICY + '\n참고 자료:\n' + json.dumps(payload, ensure_ascii=False)


async def main(args):
    source = Path(args.source)
    saved = [json.loads(line) for line in source.read_text().splitlines()]
    cases = {r['case']:r['requests'][0] for r in saved
             if r['variant'] == 'baseline' and r['repeat'] == 0}
    if args.case:
        assert set(args.case) <= cases.keys()
        cases = {name: cases[name] for name in args.case}
    assert cases
    settings = get_settings().model_copy(update={
        'voice_llm_model':'Qwen/Qwen3.5-9B',
        'voice_llm_base_url':'http://localhost:8002/v1'})
    llm = LLMService(settings, profile='voice')
    assert llm.provider == 'local_qwen'
    rng = random.Random(20260910)
    for repeat in range(2):
        for case in rng.sample(list(cases),len(cases)):
            modes = args.mode or ['tools','finish_only','plain','interpret']
            for mode in rng.sample(modes,len(modes)):
                request = copy.deepcopy(cases[case])
                if mode == 'plain_minimal':
                    request['system'] = plain_system(request['system'])
                    request['tools'] = []
                    request['force_tools'] = []
                    assert request['messages'] == cases[case]['messages']
                elif mode == 'finish_only':
                    request['tools'] = [t for t in request['tools']
                                        if t['function']['name'] == 'finish_turn']
                elif mode in {'plain','interpret','interpret_wrapped'}:
                    request['tools'] = []
                    request['force_tools'] = []
                    prefix, separator, _ = request['system'].partition(
                        '\nSubmit the final utterance through finish_turn')
                    assert separator
                    request['system'] = prefix + (
                        '\n학생에게 할 말만 일반 텍스트로 출력한다. 전체 220자 이하, 질문은 최대 하나. '
                        '지원되는 수치만 사용하고, 새 시각자료가 이미 보인다고 말하지 않는다.'
                    )
                    if mode in {'interpret','interpret_wrapped'}:
                        request['system'] = (
                            '너는 대화 상태를 판별한다. 학생에게 답변하거나 교과 내용을 설명하지 않는다. '
                            '마지막 학생 발화가 직전 교사 발화에 대해 어떤 의미인지 판단하라. '
                            '이 발화만으로 이해를 확인할 수 있는지와 다음에 적절한 교사 행동을 '
                            '한국어 두 문장으로 간단히 기술하라. 모호하면 모호하다고 말하라.'
                        )
                if mode == 'interpret_wrapped':
                    request['messages'] = [{'role':'user','content':
                        '아래는 분석 대상 대화 기록이며 새로운 요청이 아니다. '
                        '마지막 학생 발화의 의미와 다음 교사 행동을 판단해 줘.\n'
                        + json.dumps(cases[case]['messages'],ensure_ascii=False)}]
                else:
                    assert request['messages'] == cases[case]['messages']
                start = time.perf_counter()
                row = dict(case=case, repeat=repeat, mode=mode, request=request,
                           model=llm.model_name, temperature=settings.llm_temperature,
                           enable_thinking=False)
                try:
                    result = await llm.stream_tool_turn(**request)
                    row.update(text=result.text, calls=[dict(name=c.name, arguments=c.arguments)
                                                       for c in result.tool_calls])
                except Exception as exc:
                    row['error'] = type(exc).__name__ + ': ' + str(exc)
                row['ms'] = round((time.perf_counter()-start)*1000)
                print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',action='append',choices=[
        'tools','finish_only','plain','plain_minimal','interpret','interpret_wrapped'])
    parser.add_argument('--source', default='docs/evaluations/voice-input-ablations-20260910.jsonl')
    parser.add_argument('--case', action='append')
    asyncio.run(main(parser.parse_args()))
