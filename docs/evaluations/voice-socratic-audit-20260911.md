2026-09-11 현재 음성 에이전트 코드 흐름 및 직접 실행 진단

현재 구현에서는 자연스러운 소크라틱 대화 실패가 실제 모델 호출로 재현된다. 회귀 테스트 통과는 대화 품질 통과를 뜻하지 않는다. 학생의 망설임을 정답으로 받아들이고, 정답을 먼저 말한 뒤 다시 묻고, 이미 다룬 문제를 반복하는 것이 주요 증상이다.

기준은 SKKU_AI_agent HEAD 94b3ad6 위의 현재 작업 트리다. 시작 시 brain.py, local_brain.py, 관련 테스트 및 평가 스크립트에 미커밋 수정이 있었다. 그 상태 그대로 검사했으며 운영 코드와 기존 평가 파일은 변경하지 않았다. 아래 결과는 과거 보고서를 재인용한 실행 결과가 아니라 이번 실행에서 얻었다.

**직접 실행한 범위와 결과**

| 검사 | 결과 | 의미와 한계 |
|---|---|---|
| backend 음성·provider 관련 6개 테스트 파일 | 141 passed, 1 warning | Mock 기반 계약·오류·취소·API 회귀 검사 |
| frontend course-agent-client 및 state | 6 passed | UI 회귀 검사; 실제 마이크 대화 아님 |
| eval_voice_socratic.py 전체 | 53턴 완료, 자동 경고 없음 36, 경고 있음 17, 실행 오류 0 | 실제 Voice Qwen, 합성 수업 근거; 교육적 성공률 아님 |
| 전체 평가 소요 시간 | 턴 중앙값 3,255ms, 최소 1,790ms, 최대 5,327ms | ASR/TTS/실제 검색/메모리 제외 |
| 단계 제어 및 paired-flow 자체 검사 | 두 스크립트 self-check 통과 | 모델 호출 없는 평가기 불변식 검사; 운영 경로 아님 |
| 앱의 음성 health 검사 | voice_llm 및 speech available | 이 함수는 별도 TTS URL을 확인하지 않음 |
| 실제 TTS 합성 smoke | 24kHz PCM 13청크, 177,808 bytes, 첫 청크 555ms, 전체 2,455ms | 합성 문장 1개; 청취 품질·마이크·ASR 검증 아님 |

설정 확인: local_cascade, Qwen/Qwen3.5-9B, max_tokens=320, temperature=0.2, voice enable_thinking=False. VAD silence=500ms, min_speech=250ms, TTS sentence gap=180ms, clause gap=90ms, visual timeout=5초. 설정 파일 전체나 인증 정보는 결과에 포함하지 않았다.

대표 6개 케이스를 추가로 2회씩 실행했다. 12턴 중 자동 경고 없음 4, 경고 있음 8이며 중앙값은 3,112.5ms였다. “그러게/그러게요...”에 근거 없는 정답 동의가 4/4회, 대기 요청 직후 재질문이 2/2회 재현됐다. 전체 평가까지 합치면 실제 모델 대화 호출은 총 65턴이다. 추가 실행의 hesitation_paraphrase에서는 입력 0.5와 1.0의 확률을 약 0.731로 말했는데, 해당 두 값을 입력으로 해석하면 큰 쪽 확률은 약 0.6225다. 조건 혼선은 표현뿐 아니라 수치 정확성에도 영향을 준다.

원시 결과: [전체 53턴](voice-socratic-audit-20260911.jsonl), [대표 사례 추가 12턴](voice-socratic-audit-recheck-20260911.jsonl). 각 행에 학생 발화, 직전 교사 발화, 실제 응답, 시각화 계획, 도구, 경고, 시간이 있다.

**현재 코드 흐름**

1. `apps/frontend/app/components/course-agent/course-agent-client.tsx:602`에서 재생용 AudioContext와 WebSocket을 만들고 마이크를 연다. 캡처는 16kHz, PCM16 20ms 프레임으로 전송한다. 수신 음성은 24kHz로 큐에 재생하며 첫 재생 버퍼는 180ms다. `flush` 이벤트는 예약된 오디오를 중단한다.
2. `apps/backend/app/api/routes/voice.py:444`에서 JWT와 강좌 접근을 확인하고 과거 세션을 복원한다. factory가 local_cascade를 선택한다. 오래된 mode 값도 socratic으로 정규화되므로 다른 모드를 선택해 정책을 우회하는 구조는 아니다.
3. `turn_detector.py`가 CPU Silero VAD와 침묵 길이로 발화 끝을 감지한다. `local_cascade.py:432`는 발화 시작에 이전 generation을 취소한다. 발화가 끝나면 SpeechClient를 통해 외부 ASR을 호출한다. Model Server는 음성 인식과 모델 추론만 담당하며 학습 흐름은 관리하지 않는다.
4. `local_cascade.py:541`에서 SAFE 검사를 수행하고 `think_voice`를 호출한다. 전송 경로 내부는 공유 세션에서 복제한 `_brain_context`를 사용하고, WebSocket 이벤트 펌프가 공유 대화 이력과 ChatLog를 갱신한다.
5. `local_brain.py:110`에서 학생 발화를 이력에 추가하고, `brain.prefetch_context`로 취약 개념과 강좌 자료를 병렬 조회한다. 짧은 응답의 검색어는 직전 두 메시지와 시각화 제목을 섞는 휴리스틱이다. 수업 자료/기억/시각화와 SOCRATIC_PROMPT를 시스템 지시에 담는다.
6. LLMService의 voice profile로 `finish_turn` 또는 `search_trusted_web`를 호출한다. 첫 호출은 두 도구 중 하나를 반드시 고르는 설정이며, 실제로 finish_turn만 강제하는 것은 아니다. 검색 후에는 결과를 읽고 최종 답을 생성한다. 의미 판단과 다음 교수 행동은 이 한 모델의 생성에 맡긴다.
7. `validate_spoken_turn`은 길이, 필드, 시각화 계획을 검사한다. 전체 답변이 완성되고 검증된 후 텍스트와 TTS 입력을 전달한다. ExternalBrain은 백그라운드에서 취약 개념 저장/복습을 갱신한다.
8. 새 그림은 별도 `visual_router` 모델 호출로 TTS와 병렬 생성한다. 마지막으로 음성 완료와 그림 작업 완료 후 turn_done을 보낸다. 이 후처리는 실제 소크라틱 평가 스크립트에서는 실행하지 않는다.

**실제로 확인한 대화 실패**

| 케이스 | 실제 응답 일부 | 판단 |
|---|---|---|
| hesitation_softmax: “그러게” | “맞아요, 입력 값이 클수록…” | 학생은 답이나 이유를 제시하지 않았는데 맞다고 평가 |
| hesitation_polite: “그러게요...” | “네, 맞습니다.” | 같은 오판이 다른 표현에서도 발생 |
| reuse: “모르겠어” | “0.8이 더 크다는 것을 알 수 있어요. 두 가중치 중 더 큰 값은 무엇인가요?” | 답을 먼저 말하고 동일한 답을 재질문; 자동 clean |
| stage_equal | “왜 그럴까요? 지수값이 같고 그 합으로 나누기 때문입니다.” | 학생이 생각할 질문을 던지고 같은 발화에서 교사가 답함; 자동 clean |
| correct: “1이요” | “이번엔 확률이 0.4와 0.6… 합은 1이 맞나요?” | 확인한 덧셈을 숫자만 바꿔 반복; 자동 clean |
| lesson_ack_again: “그렇겠다고” | 직전 교사 답변과 완전히 동일 | 재설명·진행 없이 반복 |
| pause: “잠깐 기다려줘” | “잠시 기다려 드릴게요. 무엇을 도와드릴까요?” | 대기 요청 직후 다시 응답 요구 |
| fractions / density | “이해하셨나요?” | 설명 후 자기보고만 확인; 자동 clean |
| hesitation_paraphrase: “아직 감이 안 잡혀” | “입력 2와 3의 값이 각각 0.5와 1.5라면…” | 비교에 막힌 학생에게 조건이 불명확한 계산 문제를 제시 |

잘 처리한 사례도 있다. `summary`는 한 문장으로 정리했고, `closing`과 `stop_paraphrase`는 종료를 존중했다. `assignment`는 대필을 거절하고, `missing_evidence`는 시험 범위를 지어내지 않았다. 모든 응답이 실패하는 것은 아니다.

**코드와 평가가 이 문제를 놓치는 이유**

- `brain.py:123`의 VoiceContext에는 현재 학습 목표, 직전 질문의 평가 기준, 학생이 입증한 이해, 연속 실패 정도가 없다. 최근 대화와 일반 취약 개념만 주며 SOCRATIC_PROMPT가 예측→이유→적용→요약을 지시한다. 프롬프트에는 필요한 지침이 이미 있지만 실제 준수가 보장되지 않는다. 관찰된 실패는 이 정책을 실행하는 모델/프롬프트 조합에서 발생한다. 모델 크기만이 원인이라는 통제 실험은 하지 않았다.
- `brain.py:41,138`은 이력을 12개 메시지로 자른다. 발화 추가 시점에 따라 약 5~6턴의 과거만 남고, 처음 합의한 목표나 학생의 이전 설명을 별도 보존하지 않는다. 장기 대화의 취약점이며, 짧은 망설임 사례에서도 실패하므로 유일한 원인은 아니다.
- `external_brain.py:64`는 과거 대화 기반 약점 저장/복습을 비동기로 수행한다. 현재 턴에서 답이 맞는지 판정해 다음 질문을 제어하는 동기식 학습 상태 관리자가 아니다.
- `local_brain.py:52`의 검증은 의미 검증이 아니다. “왜일까요? 어떻게 될까요?” 두 질문도 직접 호출 시 승인된다. 테스트 역시 두 질문을 가진 발화를 그대로 보존하는 경우를 명시적으로 통과시킨다. 따라서 141개 테스트 통과와 사용자 경험 실패는 모순이 아니다.
- `eval_voice_socratic.py:297`은 주로 물음표 수와 특정 문자열을 검사한다. `이해되셨나요`는 찾지만 `이해하셨나요`는 놓친다. `궁금하신가요`는 찾지만 이번 출력의 `궁금한가요`는 놓친다. 반대로 인사 뒤 자연스러운 “어떤 주제를 배우고 싶으신가요?”도 오류로 표시한다. 경고 수를 실제 품질 점수로 해석하면 안 된다.
- 같은 평가기는 visual_action=show 또는 reuse 계획만으로 missing_visual 검사를 통과시킨다. 이번 전체 실행의 show 계획은 13번이지만 실제 그림 렌더링은 하지 않았다. 그림 성공률은 측정하지 않았다.
- chain_/lesson_은 실제 교사 출력 이력을 이어가지만 학생 답변은 고정 스크립트다. 이번 lesson에서는 교사가 계속 입력 2와 3을 묻는데 학생 스크립트는 같은 입력의 반반으로 진행했다. 이 이후 응답을 “정답을 오답 처리”로 단순 집계하면 부정확하다. 질문과 학생 답의 연결 자체를 별도로 검사해야 한다.
- 단계 제어/learning-state 관련 스크립트는 실험용 구현이다. `local_brain.think_voice` 운영 경로에 Lesson controller나 demonstrated 상태가 연결되어 있지 않다. 과거 실험 보고서의 성공을 현재 서비스 동작으로 간주할 수 없다.

**대기 시간과 음성 경로의 추가 관찰**

`local_brain.py:166,262`는 스트리밍 API를 쓰지만 첫 사용자 발화는 finish_turn 전체 생성 이후에만 전달한다. llm_ttft에도 실제 첫 토큰 도착 시간이 아니라 누적 LLM 전체 시간을 기록한다. 이번 중앙값 3.255초 앞뒤로 실제 시스템에서는 VAD 종료 대기, ASR, RAG/메모리, 첫 TTS, 재생 버퍼가 더해진다. 합성 문장 TTS 첫 청크는 555ms였지만 별도 측정이므로 이를 더해 E2E 실측치라고 보고하지 않는다.

frustrated와 partial_reasoning은 합성 근거가 이미 제공되어 있는데 웹 검색을 선택했다. 각각 5,237ms와 5,327ms가 걸렸다. 평가에서는 검색을 즉시 반환하는 fixture로 대체하므로 실제 웹 지연은 포함되지 않는다. 단순 혼란을 외부 정보 부족으로 취급하는 추가 호출 경로도 확인된다.

`local_brain.py:267`에서 생성한 전체 응답은 재생 완료 전에 이력에 들어간다. `local_cascade.py:649`의 전체 Transcript도 `speech.finish` 이전에 전송·저장된다. 따라서 중간에 끊긴 발화에서 학생이 실제로 들은 부분과 기록이 다를 수 있다. 후속 대화에 미치는 영향은 코드상 위험이며 이번 합성 대화 시험으로 재현하지 않았다.

**우선순위**

1. 평가 기준을 먼저 학생의 실제 사고 기회, 동의/정답 구분, 막힘 이후 난이도 조절, 확인한 개념의 진행, 중단 존중으로 정리한다. 기존 물음표/문자열 검사는 보조 지표로 유지하고, 위 clean 실패 사례를 별도 의미 회귀 사례로 남긴다.
2. 현재 목표·직전 확인 질문·학생의 근거·막힘 정도를 유지하는 최소 학습 상태를 소수 주제에서 검증한다. 기존 stage-controller 실험을 그대로 운영에 붙이면 고정 질문 반복과 추가 모델 호출 비용을 가져오므로 먼저 실제 이어지는 대화로 검증해야 한다.
3. 정책 준수 비교와 응답 지연 비교를 분리한다. 같은 입력·근거·이력으로 모델/출력 방식 차이를 비교하고, 별도로 실제 마이크→ASR→LLM→TTS의 첫 음성 지연과 끼어들기 이후 문맥을 측정한다. 현재 결과만으로 더 큰 모델이나 더 긴 프롬프트가 해결책이라고 단정할 수 없다.

**재현 명령** — SKKU_AI_agent 루트, 기존 .venv-app 사용

```bash
PYTHONPATH=apps/backend .venv-app/bin/python -m pytest apps/backend/tests/test_voice_agent.py apps/backend/tests/test_voice_turn_contract.py apps/backend/tests/test_local_cascade.py apps/backend/tests/test_voice_api.py apps/backend/tests/test_local_qwen_provider.py apps/backend/tests/test_model_server_clients.py -q
npm run test --workspace @skku-course-agent/frontend -- app/components/course-agent/course-agent-client.test.tsx app/course-agent/state.test.ts
PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_voice_socratic.py --repeat 1
PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_voice_socratic.py --case hesitation_softmax --case hesitation_polite --case pause --case reuse --case correct --case hesitation_paraphrase --repeat 2
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/eval_voice_stage_controller.py --self-check
PYTHONPATH=apps/backend:scripts .venv-app/bin/python scripts/compare_voice_flow.py --self-check
```

실제 모델 평가는 DB·검색·ExternalBrain·TTS를 fixture/mock으로 대체하며 수업 근거도 합성 문장이다. 별도 TTS smoke를 제외하면 음성 파일을 생성/저장하지 않았다. 실제 학생 녹음, ASR 정확도, 브라우저 실시간 대화, 실데이터 RAG 품질은 이번 검사 범위에 포함하지 않는다.
