"""Small multi-turn state prototype, isolated from production and real students."""
import asyncio
import copy
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.llm_service import LLMService
from app.services.voice import brain, local_brain
from eval_voice_socratic import SOFTMAX_LESSON_EVIDENCE


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    concept: Literal['order', 'equal', 'normalization', 'definition']
    quote: str = Field(min_length=1, max_length=100)


class StateTurn(local_brain.SpokenTurn):
    demonstrated: list[Evidence] = Field(
        default_factory=list, max_length=1,
        description='Only a concept demonstrated by this student answer; empty for mere assent '
                    'or hesitation. quote must be an exact substring of the current student turn.')


STUDENTS = [
    '소프트맥스가 뭔지 모르겠어. 처음부터 같이 해보자.',
    '그러게',
    '응',
    '아직 모르겠어. 계산 말고 쉬운 예로 도와줘.',
    '입력 두 개가 같으면 확률도 반반, 각각 0.5일 것 같아.',
    '같은 입력이면 지수값도 같고, 같은 합으로 나누니까 확률도 같아.',
    '정리하면 소프트맥스는 입력의 지수값을 전체 지수값의 합으로 나눠서 합이 1인 확률로 바꾸는 거네.',
    '오늘은 여기까지 하자. 머리가 꽉 찼어.',
]


def validate_evidence(evidence, student):
    if any(item.quote not in student for item in evidence):
        raise ValueError('Evidence quote is not in the current student utterance')


async def main():
    # Synthetic fixed learner script: generated tutor histories diverge between arms.
    # It tests state retention/false mastery, not real learning or matched latency.
    validate_evidence([Evidence(concept='equal', quote='반반')], '반반 같아')
    try:
        validate_evidence([Evidence(concept='equal', quote='반반')], '응')
    except ValueError:
        pass
    else:
        raise AssertionError('Invented evidence accepted')
    root = Path(__file__).resolve().parents[1] / 'docs/evaluations'
    traces = [json.loads(line) for line in
              (root/'voice-input-ablations-20260910.jsonl').read_text().splitlines()]
    template = next(r['requests'][0] for r in traces if r['variant'] == 'baseline')
    suffix = '\nSubmit the final utterance through finish_turn' + template['system'].split(
        '\nSubmit the final utterance through finish_turn',1)[1]
    settings = get_settings().model_copy(update={
        'voice_llm_model':'Qwen/Qwen3.5-9B','voice_llm_base_url':'http://localhost:8002/v1'})
    llm = LLMService(settings, profile='voice')
    assert llm.provider == 'local_qwen'
    for repeat in range(2):
        contexts = {mode:brain.VoiceContext('eval','평가 과목','eval',None)
                    for mode in ['baseline','state']}
        states = {mode:{} for mode in contexts}
        for index, student in enumerate(STUDENTS):
            for mode in (['baseline','state'] if (repeat+index)%2 else ['state','baseline']):
                context = contexts[mode]
                state = states[mode]
                before = copy.deepcopy(state)
                context.append_history({'role':'user','content':student})
                prefetched = {'student_question':student,'weak_concepts':{'found':False},
                    'course_materials':{'found':True,'results':[{
                        'file':'eval.txt','page':1,'excerpt':SOFTMAX_LESSON_EVIDENCE}]}}
                system = brain.answer_instructions(context,prefetched,voice=True)+suffix
                tools = copy.deepcopy([t for t in template['tools']
                                       if t['function']['name'] == 'finish_turn'])
                if mode == 'state':
                    schema = StateTurn.model_json_schema()
                    schema['properties'].pop('question')
                    schema.setdefault('required',[]).append('demonstrated')
                    next(t for t in tools if t['function']['name']=='finish_turn')[
                        'function']['parameters'] = schema
                    system += ('\n학습 목표: 크기 비교→같은 입력→이유→합이 1→학생 요약. '
                        '다음 기록은 학생의 실제 설명을 근거로 한 잠정 학습 기록이다. '
                        '직전 교사 질문과 학생 반응을 보고, 확인한 내용을 반복하지 말고 '
                        '막히면 더 쉬운 한 단계로 돕는다. 수긍·망설임은 이해 근거가 아니다. '
                        'demonstrated에는 이번 학생이 직접 설명하거나 적용한 개념 하나와 '
                        '그 발화의 정확한 인용만 담고, 없으면 빈 배열로 둔다.\n'
                        +json.dumps({'topic':'softmax','demonstrated':state,
                            'previous_teacher':next((m['content'] for m in
                                reversed(context.history[:-1]) if m['role']=='assistant'),'')},
                            ensure_ascii=False))
                request = dict(system=system,messages=brain._conversation(context.history),
                    tools=tools,force_tools=['finish_turn'],max_tokens=settings.voice_llm_max_tokens)
                row = dict(mode=mode,repeat=repeat,turn=index,student=student,
                    state_before=before,request=copy.deepcopy(request),model=llm.model_name)
                started = time.perf_counter()
                try:
                    result = await llm.stream_tool_turn(**request)
                    row['raw'] = {'text':result.text,'calls':[
                        {'name':c.name,'arguments':c.arguments} for c in result.tool_calls]}
                    if not result.tool_calls and result.text:
                        from app.services.llm_service import ToolCallRequest
                        recovered = local_brain.recover_plain_turn(result.text,context,student)
                        recovered_args = recovered.model_dump()
                        if mode == 'state':
                            recovered_args['demonstrated'] = []
                        result.tool_calls.append(ToolCallRequest(
                            'recovered','finish_turn',recovered_args))
                        row['plain_recovered'] = True
                    if len(result.tool_calls)!=1 or result.tool_calls[0].name!='finish_turn':
                        raise ValueError('Expected one finish_turn, no external tool execution')
                    arguments = dict(result.tool_calls[0].arguments)
                    if mode == 'state':
                        update = StateTurn.model_validate(arguments)
                        validate_evidence(update.demonstrated,student)
                        arguments.pop('demonstrated',None)
                    spoken = local_brain.validate_spoken_turn(arguments,context,student)
                    reply = f'{spoken.feedback} {spoken.question}'.strip()
                    if mode == 'state':
                        for item in update.demonstrated:
                            state[item.concept] = {'student_turn':index,'quote':item.quote}
                    row['reply'] = reply
                    context.append_history({'role':'assistant','content':reply})
                    # No renderer: don't pretend a requested visualization became visible.
                except Exception as exc:
                    row['error'] = type(exc).__name__+': '+str(exc)
                    context.append_history({'role':'assistant','content':'답변 생성에 실패했습니다.'})
                row.update(ms=round((time.perf_counter()-started)*1000),state_after=copy.deepcopy(state))
                print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
