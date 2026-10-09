2026-09-11 tool 반환 메시지를 통한 교수 지침 전달 비교

결론: 이번 구성에서는 tool 반환 위치로 옮겨도 소크라틱 대화가 안정적으로 개선되지 않았다. 운영 반영은 하지 않았다. 별도 판단기, 패턴 매칭, 학습 상태 제어는 추가하지 않았다.

**실험 구성**

기존 eval_voice_inputs.py를 확장해 아래 세 방식을 같은 입력으로 비교했다.

| 방식 | 자료 위치 | 추가 교수 지침 위치 |
|---|---|---|
| post_evidence_guidance | system | 같은 system에서 자료 직후 |
| tool_context | role=tool | 추가 지침 없음 |
| tool_context_guidance | role=tool | 같은 tool 결과에서 자료 직후 |

기존 SOCRATIC_PROMPT는 세 방식 모두 유지했다. 추가 지침은 직전 실험과 동일한 POST_EVIDENCE_GUIDANCE다. 자료 JSON과 서버가 쓴 교수 지침은 별도 구획으로 표시했다. tool_context는 자료 전달 위치의 효과와 추가 지침의 효과를 구분하기 위한 대조군이다.

서버의 기존 사전 조회 결과를 학생의 마지막 발화 다음에 assistant tool_calls(prefetch_context) → tool(tool_call_id 일치) 메시지로 넣었다. 모델이 조회 호출을 새로 생성하게 하지 않았으며, 지침 전달을 위한 추가 모델 호출도 없다. 조회 결과는 기존 평가가 제공하는 합성 fixture다. 실제 LLM API에는 role=tool 메시지를 전달했다. 따라서 이번 실험은 **서버가 이미 조회한 결과의 표현 방식**을 비교한 것이며, 모델이 자율적으로 호출할 도구를 선택한 다음 새 지침을 받는 전체 운영 흐름은 아니다.

system에서 자료를 제거하고 마지막 학생 발화 뒤로 옮겼으므로 메시지 역할뿐 아니라 위치·인접성·완료된 도구 호출 문맥도 함께 달라진다. 순수하게 role 하나만의 인과 효과라고 해석할 수 없다. 이번 구성에서 관찰된 결과로 한정한다.

10개 기존 상황 × 3개 방식 × 2회 = 60턴. Qwen/Qwen3.5-9B, voice profile, max_tokens=320, temperature=0.2, thinking 비활성화. 실행 순서는 고정 난수로 섞었다. 20개 비교 묶음의 실제 첫 요청을 검사해 자료, 대화 이력, 도구 목록, 토큰 한도가 같고 의도한 이동/추가 지침 차이만 있음을 확인했다.

**주 비교 결과**

| 항목 | system+지침 | tool 자료만 | tool 자료+지침 |
|---|---:|---:|---:|
| 실행 턴 | 20 | 20 | 20 |
| 실행 오류 | 0 | 0 | 0 |
| 기존 자동 검사 경고 없는 턴 | 12 | 8 | 8 |
| 그러게/그러게요에 근거 없는 정답 동의 | 2/4 | 4/4 | 4/4 |
| 대기 요청 직후 재질문 | 2/2 | 2/2 | 2/2 |
| 측정 턴 지연 중앙값 | 2,937.5ms | 1,537.5ms | 1,503ms |
| LLM 요청 수 | 22 | 20 | 21 |

이 숫자는 새 실행 결과다. 이전 실험과 응답이 달라지는 경우가 있어 지난 결과와 합쳐 성공률을 계산하지 않았다. 자동 검사 통과는 의미 품질 성공이 아니다. 코드가 기존 일반 텍스트 복구를 허용하므로 실행 오류 0은 finish_turn 준수율 100%도 아니다.

**원시 응답에서 확인한 문제와 일부 개선**

- tool 자료+지침, “그러게”: “맞습니다. 입력 값이 클수록 … 얼마나 더 클지 계산해 볼까요?” 학생은 답하지 않았는데 맞다고 평가하고, 비교에 막힌 학생에게 더 어려운 계산을 요구했다. “그러게요…”에서도 두 번 모두 같은 문제가 남았다.
- tool 자료+지침, “잠깐 기다려줘”: “네, 기다려주세요. 무엇을 도와드릴까요?” 대기 요청 뒤 질문하는 데 더해 기다리는 주체도 바뀐다.
- tool 자료+지침, ack_repair 첫 실행: “이 두 값이 같다면 각각 0.5가 될 거예요. 만약 입력이 2와 2라면 각각 얼마가 될까요?” 답을 미리 말한 뒤 다시 묻는다.
- tool 자료+지침, stage_equal 두 번 모두: 같은 입력의 확률이 같은 이유를 설명하고 입력 2와 3의 결과로 넘어갔다. 학생에게 이유를 설명할 기회를 남기는 흐름이 아니다.
- tool 자료+지침, reuse: 첫 실행은 0.8이 더 크다고 알려줬다. 두 번째에는 “0.8과 0.2 중 어느 숫자가 더 크다고 생각해요?”라고 답을 남겨두었다. 일부 개선은 있으나 일관되지 않다.
- tool 자료+지침, correct: 한 번은 확률 합을 맞힌 직후 곱 0.21에서 각 확률을 찾는 문제로 난이도가 뛰었다. 다른 한 번은 여사건 질문으로 진행했다.
- tool 자료+지침, fractions: 첫 실행은 사과를 나눈 부분을 물었지만, 두 번째는 쿠키 4개를 2명에게 나누는 몫 질문으로 이동했다. 분수의 의미를 확인하는 흐름이 안정적이지 않다.
- summary는 세 방식 모두 두 번씩 한 문장 정리 요청을 지켰다.

**빠르게 보이는 이유를 추가 확인**

tool 방식의 짧은 지연을 그대로 성능 개선으로 보고하지 않기 위해 원시 모델 응답을 저장하는 계측을 추가했다. hesitation_polite와 pause를 세 방식으로 두 번씩 추가 실행했다. 총 12턴이며 주 비교와 별도 파일이다.

| 원시 응답 형식 | system+지침 | tool 자료만 | tool 자료+지침 |
|---|---:|---:|---:|
| finish_turn 호출 | 4/4 | 0/4 | 0/4 |
| 일반 텍스트 응답 | 0/4 | 4/4 | 4/4 |

현재 local_brain.py는 도구 호출 없는 텍스트를 recover_plain_turn으로 복구하고 intent=teach, visual_action=none으로 처리한다. 그래서 사용자에게 응답은 도착하지만 모델이 의도한 구조화된 학습/시각화 계획을 제출한 것은 아니다. 특히 이전 그림이 있는 hesitation_polite에서도 tool 방식은 시각화 재사용 계획을 내지 않았다.

관찰된 형식 변화는 tool 방식의 짧은 응답 시간을 설명하는 요인이다. 입력 위치, 출력 길이, 모델 서버 상태 등의 효과를 따로 통제하지 않았으므로 속도 차이 전부의 원인으로 단정하지 않는다. 주 비교 60턴은 원시 생성 결과 계측을 추가하기 전에 실행했으므로 **일반 텍스트 비율 8/8은 추가 진단 12턴의 tool 두 그룹에만 해당한다.**

**검증과 결정**

- as_tool_context self-check: 자료 JSON과 지침 이동, 원본 요청 불변, 추가 검색 이후 메시지 순서 보존을 검증했다.
- Ruff: scripts/eval_voice_inputs.py 통과.
- 주 비교: 60턴 완전성 및 20개 입력 묶음의 차이 검증 통과.
- 추가 진단: 12턴 원시 응답 확인. 총 72턴 실행.
- 운영 코드/설정/기존 대화 정책 변경 없음. 평가 스크립트와 결과물만 추가·수정했다.

tool 반환에 지침을 붙이는 구성을 현재 상태로 도입하지 않는다. 위치를 옮기는 것만으로 핵심 대화 오류를 해결하지 못했고, 일반 텍스트 복구 경로 사용이라는 추가 변수도 확인됐다. 더 검증한다면 우선 finish_turn을 실제로 준수하는 동일한 출력 조건을 확보한 비교가 필요하다. 새 판단기나 단계 제어기를 붙이는 결정은 이번 결과로 정당화하지 않는다.

합성 수업 근거와 고정 과거 대화로 만든 단일 응답 비교다. 실제 다중 턴 학습 효과, ASR 정확도, 실제 검색, 그림 렌더링, 마이크와 TTS 지연은 측정하지 않았다. 소수 실패 사례 중심이므로 모델/서비스 전체의 성능으로 일반화하지 않는다.

원시 자료: [주 비교 60턴](voice-tool-guidance-20260911.jsonl), [원시 출력 추가 진단 12턴](voice-tool-guidance-raw-20260911.jsonl).

**재현** — SKKU_AI_agent 루트

```bash
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/eval_voice_inputs.py --self-check
.venv-app/bin/ruff check scripts/eval_voice_inputs.py
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/eval_voice_inputs.py \
  --variant post_evidence_guidance --variant tool_context --variant tool_context_guidance \
  --case hesitation_softmax --case hesitation_polite --case reuse --case stage_equal \
  --case correct --case pause --case fractions --case ack_repair --case frustrated --case summary
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/eval_voice_inputs.py \
  --variant post_evidence_guidance --variant tool_context --variant tool_context_guidance \
  --case hesitation_polite --case pause
```

이제 스크립트는 요청뿐 아니라 responses에 원시 text/tool_calls도 남긴다. 모델 호출을 완료한 후 원시 응답 저장을 추가했으므로 주 비교 파일에는 responses가 없고 추가 진단 파일에는 있다.
