"""Recompute saved trials and generate a portable-report input and notebook."""
import contextlib
import io
import json
import os
from pathlib import Path

CODE = '''import json, statistics, math
from collections import Counter
from pathlib import Path
rows = [json.loads(l) for l in Path("voice-model-comparison-20260909.jsonl").read_text().splitlines()]
trials = [r for r in rows if not r["warmup"]]
assert len(rows) == 74 and len(trials) == 72
assert len({(r["case"],r["repeat"],r["model"]) for r in trials}) == 72
summary = []
for model in sorted({r["model"] for r in trials}):
    group = [r for r in trials if r["model"] == model]
    assert len(group) == 36
    assert set(Counter(r["case"] for r in group).values()) == {3}
    times = sorted(r["ms"] for r in group)
    summary.append(dict(model=model, n=36, median_s=statistics.median(times)/1000,
        p95_s=times[math.ceil(.95*len(times))-1]/1000, max_s=max(times)/1000,
        median_chars=statistics.median(len(r.get("reply","")) for r in group),
        errors=sum("error" in r or "generation_fallback" in r["issues"] for r in group)))
pairs = {}
for r in trials:
    pairs.setdefault((r["case"],r["repeat"]), []).append(r)
diffs = []
for pair in pairs.values():
    a,b = sorted(pair,key=lambda r:r["model"])
    assert a["student"] == b["student"] and a["previous_reply"] == b["previous_reply"]
    diffs.append(b["ms"]-a["ms"])
paired = dict(n=len(diffs), larger_slower=sum(d>0 for d in diffs), median_delta_ms=statistics.median(diffs))
print(json.dumps(dict(summary=summary, paired=paired),ensure_ascii=False,indent=2))
'''


def main():
    os.chdir(Path(__file__).resolve().parents[1] / 'docs/evaluations')
    scope, captured = {}, io.StringIO()
    with contextlib.redirect_stdout(captured):
        exec(CODE, scope)
    print(captured.getvalue())
    title = 'Voice Model Comparison'
    sections = [
        ('title', '# '+title),
        ('summary', '## Executive Summary\n\n현재 구성에서 27B로 즉시 교체할 근거는 부족합니다. 답변 완성 중앙값은 9B 3.054초, 27B 4.583초로 약 50.1% 느렸습니다. 구체적인 후속 질문은 일부 개선됐지만, “그러게”에 부적절하게 동의하는 핵심 실패는 양쪽 모두 3/3회 재현됐습니다.'),
        ('methods', '## 범위와 지표\n\n실제 비교 대상은 8B가 아니라 Qwen3.5-9B와 Qwen3.8-27B입니다. 2026-09-09 실행한 12개 고정 시나리오 × 3회 × 2모델, 총 72회입니다. 별도 인사 워밍업 2회는 제외했습니다. 기존 음성 평가 도구를 재사용해 케이스를 고정 시드로 섞고 모델 순서를 교대로 바꿨습니다. 동시 요청은 1개입니다. 같은 음성 정책·이력·자료 fixture·temperature 0.2·출력 한도 320토큰·thinking 비활성 설정을 사용했습니다.\n\n시간은 think_voice 진입부터 답변 검증 완료까지이며 재시도가 있었다면 그 시간도 포함합니다. 실제 ASR·RAG 검색·TTS·첫 음성 재생은 제외합니다. P95는 모델별 36개 관측값의 nearest-rank로 운영 SLA가 아닙니다.'),
        ('latency', '## 지연 시간\n\n전체 측정에 오류나 fallback은 없었습니다. 답변 길이 중앙값은 27B가 더 짧아 더 긴 응답만으로 지연 차이를 설명할 수 없습니다. 실제 토큰 수가 없어 tokens/s로 환산하지 않았습니다. 짝별 검증 결과: '+json.dumps(scope['paired'])+'. median_delta_ms는 27B 시간에서 9B 시간을 뺀 값의 중앙값입니다.'),
        ('quality', '## 대화 품질: 원문 검토\n\n72개 응답을 맥락 적합성·사실 정확성·학습 진행·자연스러움 관점에서 검토했습니다. 단일 AI 검토이며 블라인드 평가는 아닙니다. 자동 검사 통과율을 학습 성능 점수로 쓰지 않았습니다.\n\n- **망설임:** “그러게”에 두 모델 모두 3/3회 “맞아요/맞습니다”로 시작했습니다. 27B도 확률 차이를 예측하라는 어려운 질문을 덧붙여 학생의 부담을 낮추지 못했습니다.\n- **정확한 이유 설명 이후:** 9B는 3회 중 2회 후속 질문 없이 끝났습니다. 27B는 3/3회 입력 2와 3을 비교하는 구체적인 질문을 했습니다. 이 구간은 개선입니다.\n- **가벼운 수긍:** 27B는 확률의 합을 확인하는 질문으로 전진하는 사례가 있었지만 ack_paraphrase 3/3회에서는 실제 이력에 없는 수치를 이미 말했다고 표현했습니다. 질문 증가가 곧 맥락 이해는 아닙니다.\n- **마무리:** 정확한 요약 뒤 27B는 3회 중 2회 다시 확인 질문을 했습니다(9B 1회). 중단 요청은 양쪽 모두 3/3회 존중했습니다.\n- **오답과 자기 오류:** 두 모델 모두 물리 오답의 사실을 수정했지만 27B는 1회 “거의 맞아요”로 부적절하게 평가했습니다. 학생이 에이전트 오류를 지적하면 양쪽 모두 사실을 바로잡았으나 자신의 앞선 오류를 명시적으로 인정하지 않았습니다.\n- **음성 자연스러움:** 물음표가 여러 개인 응답은 9B 0/36, 27B 9/36이었습니다. 이는 형식 지표이지 독립적인 품질 점수는 아닙니다. 27B의 과제 도움 답변은 한 번 “알려줄까요?”로 화자 역할이 어색해졌습니다.'),
        ('next', '## 권고와 다음 단계\n\n현재는 9B를 유지하고 27B 교체를 보류하는 것이 타당합니다. 일부 학습 진행 개선은 있지만 핵심 실패를 해결하지 못했고 추가 지연이 관측됐습니다. 다음 실험은 짧은 정책의 우선순위와 실제 전달되는 이력을 확인한 뒤, 망설임 대응·학생 수준에 맞는 한 가지 질문·수업 마무리를 같은 사례로 재평가하는 것입니다. 이것이 원인으로 입증됐다는 뜻은 아닙니다. 배포 판단 전에는 실제 첫 음성 재생 지연과 동시 사용자 부하도 측정해야 합니다. 이번 작업은 운영 모델과 서버 설정을 변경하지 않았습니다.'),
        ('limits', '## 한계와 검증\n\n파라미터 수만의 효과가 아니라 서로 다른 모델 버전과 서빙 구성의 비교입니다. 실행 후 프로세스에서 확인한 설정은 9B BF16·TP1·문맥 한도 8192, 27B BF16·TP4·문맥 한도 16384입니다. 이 설정 확인은 JSONL 이외의 읽기 전용 런타임 점검에 근거합니다. GPU 배치가 다르고 공유 서버 부하·prefix cache를 통제하지 않았습니다. 같은 GPU 속도나 비용 효율을 추정할 수 없습니다. 고정된 짧은 단일 턴 사례이므로 자유 대화·장기 학습 효과·다른 8B 모델에 일반화하지 않습니다.\n\n36개 짝의 학생 발화와 직전 답변 일치, 누락·중복·오류 여부를 재검증했습니다. 전체 직렬화 프롬프트 해시는 수집하지 않았습니다. 제한 사항을 명시한 탐색적 결과로 공유 가능합니다. 원본 JSONL과 분석 노트북을 함께 보관합니다. 노트북 코드는 stdlib로 실행했고 nbclient/nbformat은 설치되어 있지 않습니다.'),
    ]
    source = {'id':'trials','label':'Paired synthetic voice trials','path':'voice-model-comparison-20260909.jsonl',
              'query':{'engine':'python','language':'python','sql':CODE,
                       'description':'Warmups excluded. All 72 trials retained; median and nearest-rank P95.',
                       'tables_used':['voice-model-comparison-20260909.jsonl']}}
    blocks = [{'id':k,'type':'markdown','body':v,**({'sourceId':'trials'} if k not in {'title','limits'} else {})} for k,v in sections]
    blocks.insert(4,{'id':'latency_table','type':'table','tableId':'latencies'})
    fields = [('model','모델'),('n','횟수'),('median_s','중앙값 (초)'),('p95_s','P95 (초)'),('max_s','최대 (초)'),('median_chars','답변 길이 중앙값 (문자)'),('errors','오류')]
    stamp = '2026-09-10T00:00:00Z'
    artifact = {'surface':'report','manifest':{'version':1,'surface':'report','title':title,'generatedAt':stamp,'blocks':blocks,'sources':[source],
        'tables':[{'id':'latencies','title':'답변 완성 시간 — 모델별 36회','dataset':'summary','sourceId':'trials','columns':[{'field':f,'label':label} for f,label in fields],'defaultSort':{'field':'median_s','direction':'asc'}}]},
        'snapshot':{'version':1,'generatedAt':stamp,'status':'ready','datasets':{'summary':scope['summary']}},'sources':[source]}
    # Comparison chart: 12 fixed cases, median seconds, grouped by model;
    # categorical labels distinguish models as well as the renderer's colors.
    import statistics
    by_case = []
    for case in sorted({r['case'] for r in scope['trials']}):
        for model in sorted({r['model'] for r in scope['trials']}):
            group = [r for r in scope['trials'] if r['case'] == case and r['model'] == model]
            by_case.append({'case':case,'model':model,'n':len(group),
                            'median_s':statistics.median(r['ms'] for r in group)/1000})
    import sqlite3
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE trials (case_name TEXT, model TEXT, ms REAL)')
    connection.executemany('INSERT INTO trials VALUES (?,?,?)',
        [(r['case'], r['model'], r['ms']) for r in scope['trials']])
    sql = '''WITH ranked AS (
      SELECT case_name, model, ms,
        ROW_NUMBER() OVER (PARTITION BY case_name, model ORDER BY ms) AS rn,
        COUNT(*) OVER (PARTITION BY case_name, model) AS n FROM trials
    ) SELECT case_name AS "case", model, MAX(n) AS n, AVG(ms)/1000 AS median_s
      FROM ranked WHERE rn IN ((n+1)/2, (n+2)/2)
      GROUP BY case_name, model ORDER BY case_name, model'''
    cursor = connection.execute(sql)
    sql_rows = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor]
    assert sql_rows == by_case
    connection.execute('CREATE TABLE model_summary (model TEXT,n INTEGER,median_s REAL,p95_s REAL,max_s REAL,median_chars REAL,errors INTEGER)')
    connection.executemany('INSERT INTO model_summary VALUES (?,?,?,?,?,?,?)',
        [tuple(r.values()) for r in scope['summary']])
    summary_sql = 'SELECT model,n,median_s,p95_s,max_s,median_chars,errors FROM model_summary ORDER BY median_s'
    cursor = connection.execute(summary_sql)
    assert [dict(zip([c[0] for c in cursor.description], row)) for row in cursor] == scope['summary']
    connection.close()
    table_source = {'id':'summary_sql','label':'Validated Python aggregates, queried through SQLite',
        'query':{'engine':'sqlite','language':'sql','sql':summary_sql,
        'description':'model_summary contains Python median and nearest-rank P95 aggregates computed by the companion notebook.',
        'tables_used':['model_summary']}}
    artifact['manifest']['sources'].append(table_source)
    artifact['sources'].append(table_source)
    artifact['manifest']['tables'][0]['sourceId'] = 'summary_sql'
    chart_source = {'id':'case_sql','label':'Case medians from measured trials',
        'query':{'engine':'sqlite','language':'sql','sql':sql,
        'description':'In-memory trials table loaded from the 72 non-warmup JSONL records.',
        'tables_used':['trials']}}
    artifact['manifest']['sources'].append(chart_source)
    artifact['sources'].append(chart_source)
    artifact['snapshot']['datasets']['cases'] = sql_rows
    artifact['manifest']['charts'] = [{'id':'case_latency','title':'시나리오별 답변 완성 시간',
        'subtitle':'초 · 2026-09-09 · 시나리오와 모델별 3회 중앙값 · ASR/TTS 제외',
        'type':'bar','dataset':'cases','sourceId':'case_sql',
        'encodings':{'x':{'field':'case','type':'nominal'},
                     'y':{'field':'median_s','type':'quantitative'},
                     'color':{'field':'model','type':'nominal'}}}]
    blocks.insert(5,{'id':'case_chart','type':'chart','chartId':'case_latency','layout':'full'})
    Path('voice-comparison-artifact.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2))
    notebook = {'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'cells':[
        {'id':'context','cell_type':'markdown','metadata':{},'source':['# Voice Model Comparison\n\nRun from this directory. Warmups excluded; all measured trials retained. This single cell was executed with Python stdlib (nbclient unavailable). See the HTML report for findings and caveats.']},
        {'id':'analysis','cell_type':'code','metadata':{},'execution_count':1,'source':CODE.splitlines(True),'outputs':[{'output_type':'stream','name':'stdout','text':captured.getvalue().splitlines(True)}]}]}
    Path('voice-comparison.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
