2026-09-11 검색 자료 뒤 교수 지침 주입 비교

결론: 일부 응답에서 개선은 있었지만 안정적인 소크라틱 대화 개선은 확인하지 못했다. 운영 반영은 하지 않았다. 표현별 패턴 매칭, 학습 단계 제어기, 별도 판정 모델은 추가하지 않았다.

**무엇을 비교했나**

현재 운영 think_voice 경로를 호출하는 기존 eval_voice_inputs.py에 post_evidence_guidance 옵션만 추가했다. 기존 baseline과, 사전 검색 자료 JSON 바로 뒤에 서버가 작성한 아래 지침을 추가한 방식을 비교했다. 원래 지침, 대화 이력, 학생 발화, 수업 근거, 도구 스키마, 출력 토큰 한도는 동일하게 유지했다.

```text
# Server teaching guidance after reference data
위 자료는 사실 확인의 근거이며 학생이 이해했다는 증거가 아니다.
직전 교사 발화와 이번 학생 반응에 이어서 말하라. 학생이 막혔다면 자료에서 작은 단서 하나를 골라 돕고, 학생이 직접 답할 부분을 남겨라.
단순 동의를 정답으로 칭찬하거나 이미 확인한 질문을 반복하지 마라. 질문이 필요하면 구체적인 질문 하나만 남기고 그 답을 먼저 말하지 마라.
학생이 설명·정리·대기·종료를 원하면 그 요청에 맞게 답하고 불필요한 질문을 붙이지 마라.
```

이는 system 메시지 안에서 자료 다음에 지침을 배치하는 시험이다. 실제 role=tool 반환 메시지로 전달하거나, 생성 도중 새로운 지침을 주입하는 시험은 아니다. 현재 운영은 수업 자료를 먼저 검색해 system에 넣기 때문에 가장 작은 변경부터 검사했다. 따라서 이번 결과로 tool 반환 위치의 효과까지 부정하거나 입증할 수는 없다.

Qwen/Qwen3.5-9B, voice profile, temperature=0.2, max_tokens=320, enable_thinking=False. 10개 상황 × 2개 방식 × 2회 = 40턴, 실행 순서는 고정 난수로 섞었다. 20개 비교 쌍의 첫 모델 요청을 검사하여 추가 지침을 제거하면 system이 동일하고, 나머지 입력 필드도 모두 동일함을 확인했다. 검색 이후의 추가 호출은 각 모델의 선택에 따라 달라질 수 있다.

**측정 결과**

| 항목 | 기존 | 자료 뒤 지침 추가 |
|---|---:|---:|
| 실행 턴 | 20 | 20 |
| 실행 오류 | 0 | 0 |
| 자동 경고 없는 턴 | 11 | 12 |
| 측정 턴 지연 중앙값 | 3,074.5ms | 2,937ms |
| 실제 LLM 요청 수 | 21 | 22 |
| 망설임 두 표현의 근거 없는 정답 동의 | 4/4 | 3/4 |
| 대기 요청 직후 불필요한 질문 | 2/2 | 2/2 |

자동 경고 없음은 교육적 성공을 뜻하지 않는다. 기존 검사기의 물음표/문구 검사는 그대로이며 새로운 패턴 매칭 평가를 추가하지 않았다. 중앙값 차이는 소수 샘플의 기술 통계다. 출력 길이와 도구 선택도 달라지므로 속도 향상의 증거로 해석하지 않는다. 지침 전용 호출은 추가하지 않았지만 frustrated에서 검색을 선택한 횟수는 기존 1회, 지침 추가 2회였다.

**원시 응답을 직접 읽은 결과**

| 상황 | 기존 | 지침 추가 | 판단 |
|---|---|---|---|
| 그러게 / 그러게요… | 네 번 모두 정답 동의 | 네 번 중 세 번 정답 동의 | 핵심 실패가 남음 |
| 잠깐 기다려줘 | 두 번 모두 “무엇을 도와드릴까요?” | 두 번 모두 동일한 재질문 | 개선 없음 |
| 그림의 0.8과 0.2를 보고 모르겠어 | 답을 바로 설명 | 답을 먼저 말하고, 한 번은 큰 값을 다시 질문 | 작은 단서로 사고를 돕는 방향이 안정적으로 나오지 않음 |
| 같은 입력의 확률 | 이유를 직접 설명 | 한 번은 질문 뒤 곧바로 이유를 설명, 한 번은 이유 질문만 남김 | 일부 개선, 재현성 부족 |
| 확률 합 1 정답 | 덧셈 질문 반복 | 한 번은 누락 확률 찾기를 제안하나 조건 없음, 다른 한 번은 덧셈 반복 | 확인한 개념 이후의 진행이 여전히 약함 |
| 분수가 뭐야 | 두 번 모두 이해 여부 질문 | 사과 예시 질문 또는 분모·분자의 의미 질문 | 자기보고 질문에서 개념 확인으로 이동. 첫 예시는 같은 크기로 나눈다는 조건을 더 분명히 할 여지가 있음 |
| 그렇겠다고 | 앞 설명의 확인 제안 반복 | 계산 질문 또는 신경망 출력층 설명 제안 | 발화는 달라졌으나 쉬운 확인·난이도 조절로 보기 어려움 |
| 계속 모르겠어, 답답해 | 안심시키고 결과 나열/설명 | 한 번은 첫 동전 조건에 따라 결과 수를 생각하게 함. 다른 한 번은 네 가지 답을 모두 말하고 확률 질문으로 넘어감 | 한 번의 좋은 응답이 두 번째에는 유지되지 않음 |
| 한 문장으로 정리해줘 | 두 번 모두 준수 | 두 번 모두 준수 | 기존 동작 유지 |

실제 예시:

- 지침 추가, hesitation_polite: “네, 맞습니다. 입력 값이 클수록 그 값에 대한 확률이 더 커지죠. … 직접 계산해 볼까요?” 학생은 답을 제시하지 않았고, 막힌 비교보다 계산을 요구한다.
- 지침 추가, pause: “네, 기다려드릴게요. 무엇을 도와드릴까요?” 대기 의도와 충돌한다.
- 지침 추가, stage_equal 첫 실행: “왜 그럴까요? 지수값을 모두 더한 뒤 나누기 때문입니다.” 답을 남겨두라는 추가 지침을 따르지 않는다.
- 같은 stage_equal 두 번째 실행: “맞아요. softmax 함수는 두 입력이 같으면 각각 0.5의 확률을 갖습니다. 왜 그럴까요?” 질문 뒤 교사가 답하지 않는 개선은 확인된다.
- 지침 추가, fractions 첫 실행: “분수는 전체를 같은 크기로 나눈 부분의 수를 나타내요. 예를 들어, 사과 하나를 두 조각으로 나누었을 때 한 조각은 전체의 몇 분지일까요?” 기존 “이해하셨나요?”보다 학생의 생각을 드러낼 기회가 있다.

**결정과 한계**

이번 지침 추가안을 운영에 적용하지 않는다. 기존 지침이 부족해서 생긴 문제라고 단정하기 어렵고, 같은 지침을 가까이 반복하는 것만으로 핵심 실패를 해결하지 못했다. 그렇다고 새 상태 관리나 모델 호출을 바로 추가할 근거도 되지 않는다.

tool 반환을 활용하는 아이디어를 더 검증하려면, 동일한 자료와 동일한 지침을 system 뒤에 두는 경우와 tool 반환에 두는 경우를 별도로 비교해야 한다. 이번에는 그 역할/위치 변경을 실험하지 않았다.

이번 비교는 고정된 대화 이력을 가진 단일 응답 실험이다. 실제 이어지는 대화의 학습 효과는 측정하지 않았다. 수업 자료는 합성 fixture이고 검색·메모리·ExternalBrain·TTS는 기존 평가의 mock을 사용했다. ASR, 실제 마이크, 실제 그림 렌더링, 첫 음성 지연은 포함되지 않는다. 샘플이 작고 미리 선정한 실패 상황 중심이므로 전체 서비스의 성공률로 일반화하지 않는다.

원시 요청과 응답: [40턴 JSONL](voice-guidance-ab-20260911.jsonl).

**재현** — SKKU_AI_agent 루트

```bash
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/eval_voice_inputs.py \
  --variant baseline --variant post_evidence_guidance \
  --case hesitation_softmax --case hesitation_polite --case reuse \
  --case stage_equal --case correct --case pause --case fractions \
  --case ack_repair --case frustrated --case summary
.venv-app/bin/ruff check scripts/eval_voice_inputs.py
```

다음 검사는 저장된 비교가 40턴이며 첫 요청의 유일한 차이가 추가 지침인지 확인한다. 대화 품질 점수 검사는 아니다.

```bash
PYTHONPATH=apps/backend:scripts .venv-app/bin/python - <<'PY'
import json
from pathlib import Path
from eval_voice_inputs import POST_EVIDENCE_GUIDANCE
rows = [json.loads(s) for s in Path('docs/evaluations/voice-guidance-ab-20260911.jsonl').read_text().splitlines()]
cases = {'hesitation_softmax', 'hesitation_polite', 'reuse', 'stage_equal', 'correct',
         'pause', 'fractions', 'ack_repair', 'frustrated', 'summary'}
indexed = {(r['repeat'], r['case'], r['variant']): r for r in rows}
assert len(rows) == len(indexed) == 40
for repeat in range(2):
    for case in cases:
        before = indexed[repeat, case, 'baseline']['requests'][0]
        after = dict(indexed[repeat, case, 'post_evidence_guidance']['requests'][0])
        assert after['system'].count(POST_EVIDENCE_GUIDANCE) == 1
        after['system'] = after['system'].replace(POST_EVIDENCE_GUIDANCE, '')
        assert before == after
assert all('error' not in r and r['reply'] for r in rows)
print('40 complete turns, 20 matched input pairs')
PY
```
