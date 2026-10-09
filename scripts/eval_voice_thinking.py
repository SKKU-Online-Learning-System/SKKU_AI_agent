"""Same-model thinking ablation, synthetic inputs, no production settings writes."""
import argparse
import asyncio
import copy
import hashlib
import json
import random
import statistics
import time
from pathlib import Path
from unittest.mock import patch

import httpx

from app.core.config import get_settings
from app.services.llm_service import LLMService
from app.services.voice import brain, local_brain


def check_file(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert len(rows)==12
    assert len({(r['case'],r['repeat'],r['thinking']) for r in rows})==12
    source = Path(__file__).resolve().parents[1]/'docs/evaluations/voice-input-ablations-20260910.jsonl'
    saved = [json.loads(line) for line in source.read_text().splitlines()]
    originals = {r['case']:r['requests'][0] for r in saved
                 if r['variant']=='baseline' and r['repeat']==0}
    for row in rows:
        peer = next(r for r in rows if r['case']==row['case'] and
                    r['repeat']==row['repeat'] and r['thinking']!=row['thinking'])
        assert peer['input_hash']==row['input_hash']
        assert row['sent_thinking']==row['thinking']
        tokens = row['usage']['completion_tokens_details']['reasoning_tokens']
        assert (tokens>0)==row['thinking']
        request = originals[row['case']]
        payload = request['system'].split('# Preloaded context\n',1)[1].split(
            '\nSubmit the final utterance',1)[0]
        context = brain.VoiceContext('eval','평가 과목','eval',None)
        context.last_visualizations = json.loads(payload)['recent_visualizations']
        try:
            if 'error' in row:
                raise ValueError(row['error'])
            assert len(row['calls'])==1 and row['calls'][0]['name']=='finish_turn'
            local_brain.validate_spoken_turn(row['calls'][0]['arguments'],context,
                                            request['messages'][-1]['content'])
            row['valid'] = True
        except (ValueError,AssertionError):
            row['valid'] = False
    for thinking in [False,True]:
        group = [r for r in rows if r['thinking']==thinking]
        print(json.dumps(dict(thinking=thinking,n=len(group),
            valid_turns=sum(r['valid'] for r in group),
            median_ms=statistics.median(r['ms'] for r in group),
            max_ms=max(r['ms'] for r in group))))


async def main(args):
    source = Path(__file__).resolve().parents[1]/'docs/evaluations/voice-input-ablations-20260910.jsonl'
    saved = [json.loads(line) for line in source.read_text().splitlines()]
    cases = {r['case']:r['requests'][0] for r in saved
             if r['variant']=='baseline' and r['repeat']==0}
    assert len(cases)==3
    settings = get_settings().model_copy(update={
        'voice_llm_model':'Qwen/Qwen3.5-9B','voice_llm_base_url':'http://localhost:8002/v1'})
    llm = LLMService(settings,profile='voice')
    assert llm.provider=='local_qwen'
    original_request = LLMService._qwen_request
    original_lines = httpx.Response.aiter_lines
    rng = random.Random(20260910)
    for repeat in range(2):
        for case in rng.sample(list(cases),len(cases)):
            for thinking in rng.sample([False,True],2):
                request = copy.deepcopy(cases[case])
                request['max_tokens'] = args.max_tokens
                metadata = dict(reasoning_chars=0,finish_reason=None)

                def configure(self,**kwargs):
                    body = original_request(self,**kwargs)
                    body['chat_template_kwargs'] = {'enable_thinking':thinking}
                    body['stream_options'] = {'include_usage':True}
                    metadata['sent_thinking'] = body['chat_template_kwargs']['enable_thinking']
                    return body

                async def observe(response):
                    async for line in original_lines(response):
                        if line.startswith('data:') and line[5:].strip() not in {'','[DONE]'}:
                            chunk = json.loads(line[5:])
                            if chunk.get('usage'):
                                metadata['usage'] = chunk['usage']
                            choices = chunk.get('choices') or []
                            if choices:
                                choice = choices[0]
                                delta = choice.get('delta') or {}
                                metadata['reasoning_chars'] += len(
                                    delta.get('reasoning_content') or delta.get('reasoning') or '')
                                if choice.get('finish_reason'):
                                    metadata['finish_reason'] = choice['finish_reason']
                        yield line

                row = dict(case=case,repeat=repeat,thinking=thinking,max_tokens=args.max_tokens,
                    model=llm.model_name,temperature=settings.llm_temperature,
                    input_hash=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest())
                started = time.perf_counter()
                with patch.object(LLMService,'_qwen_request',configure), \
                     patch.object(httpx.Response,'aiter_lines',observe):
                    try:
                        result = await llm.stream_tool_turn(**request)
                        row.update(text=result.text,calls=[{'name':c.name,'arguments':c.arguments}
                                                          for c in result.tool_calls])
                    except Exception as exc:
                        row['error'] = type(exc).__name__+': '+str(exc)
                row.update(ms=round((time.perf_counter()-started)*1000),**metadata)
                assert row['sent_thinking']==thinking
                print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-tokens',type=int,default=320)
    parser.add_argument('--check-file')
    args = parser.parse_args()
    if args.check_file:
        check_file(args.check_file)
    else:
        asyncio.run(main(args))
