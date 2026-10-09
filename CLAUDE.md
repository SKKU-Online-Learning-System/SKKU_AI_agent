# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` holds the repository conventions (structure, coding style, commit and PR rules) and is
still authoritative for those. This file covers the commands and the cross-file architecture.

## Commands

`run.sh` and `test.sh` are the entry points. Both force `UV_PROJECT_ENVIRONMENT=.venv-app` — the
editor's `.venv` is a different environment and its Ruff LSP locks `ruff.exe`, which breaks
`uv sync`. Never run backend tooling out of `.venv`.

```bash
bash run.sh        # .env + deps + docker db + alembic upgrade + seed + API:8000 + web:3000
bash test.sh       # pytest, ruff, vitest, typecheck, lint
```

Individual steps:

```bash
# Backend (always through .venv-app)
UV_PROJECT_ENVIRONMENT=.venv-app uv sync --all-packages --extra dev --extra voice
.venv-app/Scripts/python.exe -m pytest apps/backend/tests -q
.venv-app/Scripts/python.exe -m pytest apps/backend/tests/test_voice_api.py::test_reset_clears_the_conversation
.venv-app/Scripts/python.exe -m ruff check apps/backend packages

# Frontend
npm run build:frontend
npm run typecheck
npm run lint
npx vitest run --dir apps/frontend                     # or: cd apps/frontend && npx vitest run
cd apps/frontend && npx vitest run app/lib/auth.test.ts

# Database
docker compose up -d --wait db
UV_PROJECT_ENVIRONMENT=.venv-app uv run alembic -c apps/backend/alembic.ini upgrade head
UV_PROJECT_ENVIRONMENT=.venv-app uv run python -m app.db.seed
```

Two gotchas:

- **Deleting a route requires clearing `apps/frontend/.next`.** Next.js keeps generated route types
  there, and a stale one fails `next build` and `tsc --noEmit` with "Cannot find module
  `../../../app/.../page.js`".
- The baseline is **green**: `pytest` passes with no failures and no collection errors, and so do
  `vitest`, `ruff`, `typecheck` and `lint`. Any failure is yours.

Python is 3.12+. The `voice` extra installs the optional Moss memory SDK; the `vad` extra installs
`webrtcvad-wheels`, which needs a C toolchain and is deliberately left out of the default install.

## Architecture

Monorepo: `apps/frontend` (Next.js App Router), `apps/backend` (FastAPI), `packages/shared`
(TypeScript domain types), `packages/ai_rag` (standalone RAG package), `infra/postgres/init`
(pgvector bootstrap). Product source of truth is `docs/PRD.md` and `docs/TEC_SPEC.md`.

### Two answer paths, one boundary

There are two chat surfaces and they must not diverge:

1. `POST /api/chat` → `ChatService` — the plain RAG chatbot.
2. `POST /api/voice/courses/{id}/answer-text[/stream]` → COURSE AGENT's `brain.think()`, and
   `WS .../stream` → `local_brain.think_voice()`, the only question surface students actually see.

**Which of those two a typed question takes is decided by the voice panel, and that is deliberate.**
The panel being open means the student chose voice; typing with it open is the student who *cannot*
use a microphone (no device, a shared or noisy room), not a student asking for the text chatbot. So
a typed turn goes over the same WebSocket, through `think_voice`, and comes back as speech they can
hear — bounded to 220 characters and submitted through `finish_turn` like any spoken turn. Only with
the panel closed does typing use `answer-text`. Do not "unify" these two paths, and do not let a
typed turn fall back to `answer-text` while the panel is open: `course-agent-client.tsx` queues it in
`pendingTextRef` until the socket is live again, because a reconnect gap would otherwise reroute the
student to a different brain mid-conversation without anyone noticing.

Both go through `SafetyGuardService` for guardrails, `RagService` for retrieval, `LLMService` for
generation, and both persist to `ChatSession`/`ChatLog`. **All model provider calls live in
`app/services/llm_service.py`** — `brain.py` must never import a model SDK. The one exception is
`app/services/voice/grok_live.py`, the legacy realtime transport, kept only as a comparison
provider and reachable solely through the transport factory.

**Neither brain writes the question into the history until an answer exists beside it.** Voice turns
are abandoned routinely — every barge-in cancels one — and appending the question up front left
orphan user messages that filled the bounded 12-message window and pushed the real dialogue out.

`LLMService` has two modes throughout. With `USE_MOCK_LLM=true` (the default) a deterministic mock
answers, including a scripted tool-use turn, so the whole product runs with no API key. That is why
tests can exercise the agent end to end.

### Retrieval pipeline

Upload → `MaterialProcessingService.process_material` claims the row (status guard prevents
concurrent processing) → `DocumentParserService` → `ChunkingService` → `EmbeddingService` →
`VectorStoreService.replace_material_chunks`. Retrieval is always filtered by `course_id`;
`RagService.retrieve` returns a `RetrievalOutcome` whose `summary.reason` distinguishes
`NO_PROCESSED_MATERIAL` from `NO_RELEVANT_CONTEXT`, and `ChatService` turns that into the
`answer_source_type` the UI badges. Sources are built server-side from search results, never from
model output.

`VECTOR_SEARCH_MODE` switches between in-Python cosine similarity and pgvector. The default
embedding provider is a local hash, so `RAG_SCORE_THRESHOLD` is tuned low (0.1); raise it to ~0.3
with a real embedding model.

**There are two parser modules and only one is live.** The pipeline calls
`app/services/document_parser.py` (`parse_material`); `app/services/document_parser_service.py` is
an older duplicate that only the stale tests import. Same trap in `chunking_service`
(`create_chunks` is live, `ParagraphChunkingService` no longer exists) and
`vector_store_service` (`SQLAlchemyLocalVectorStoreService` no longer exists). Those stale imports
are exactly what the pre-existing collection failures are. Fix the live module, and check
`material_processing_service._run_pipeline` for what is actually wired.

### COURSE AGENT (`app/services/voice/`)

Ported from `github.com/lyh030725/kingo-voice-agent`, rewired to this project:

- `brain.py` — six-tool agent loop. `TOOLS` stays in OpenAI/realtime schema shape because
  `grok_live.py` feeds it to xAI directly; `anthropic_tools()` converts it for Claude. Tool results
  travel as Anthropic `tool_use`/`tool_result` blocks. The two context tools
  (`recall_weak_concepts`, `search_course_materials`) are forced via `tool_choice: any` until both
  have run.
- `search_course_materials` calls `RagService` (course-scoped pgvector), not a private PDF index, so
  citations keep the `filename p.page` shape professors see elsewhere. It opens its own
  `SessionLocal` because it runs inside tool dispatch, off the request session.
- `search_trusted_web` uses Claude's server-side web search restricted to the professor-managed
  allowlist, then **re-checks the allowlist locally** before any URL reaches a student.
- `session_store.py` keeps one `VoiceContext` per `(user, course)` in process. Its lock is an
  `RLock` on purpose: `get_context()` calls `memory_store()` while holding it.
- `moss_memory.py` — weak-concept memory keyed by user id. Falls back to
  `uploads/voice/weak-concepts.json` when Moss credentials or quota are missing.
- `voice_log.py` — writes every turn (typed and spoken) into `ChatLog` so professor and admin log
  screens see voice traffic for free, and `restore_history()` rehydrates a conversation reopened
  from 대화 이력.
- `local_cascade.py` — the default transport: application-side Silero VAD → external Speech Server
  ASR → `think_voice` → chunked TTS, with generation-numbered cancellation for barge-in. It sets
  `owns_history = True`, so `_pump_provider_events` relays transcripts without writing a second,
  independently trimmed copy of the conversation. **The brain releases one validated utterance per
  turn, so there is no token stream to synthesize incrementally**; the pipeline plans the finished
  reply into requests (first one cut short, at a clause boundary, so audio starts sooner) and
  forwards each server chunk as it arrives. `tts_ms` in the turn metrics is synthesis wall time
  only — do not restart that clock before the brain runs or the logged RTF stops meaning anything.
- `turn_detector.py` — Silero VAD endpointing for the local cascade. Its tuning is read per
  detector, not frozen at import.
- Only Grok is driven by a provider-side persona, tool schema and dispatcher, so `voice.py` builds
  `agent_spec.*` and prefetches learner memory **only when `uses_grok()`** — that prefetch costs up
  to 3 seconds per connection and the cascade discards it.
- A turn that fails (ASR, LLM or TTS) is still written to `ChatLog` with the error as its answer.
  Logging only on a successful agent transcript hid outages from the log screens completely.
- `filler.pick_filler` composes the progress notice both question surfaces show **from the question
  itself**: it echoes the topic in the student's own words ("경사하강법이요? 네, 잠깐 정리해 볼게요.")
  and phrases it for the kind of question (definition, why, how, a comparison naming both things,
  example, yes/no check, where-in-the-materials), never repeating the session's previous notice
  (`VoiceContext.last_filler`). A turn that is not waiting for an answer — a greeting, thanks,
  "네, 알겠어요", a laugh — gets **no notice** (`pick_filler` returns `None` and both surfaces skip
  it): nobody says "잠시만요" back to "안녕". A **stuck** turn ("몰라", "모르겠어요", "힌트 주세요") is an
  answer to the tutor's question, not a question: it gets a `STUCK` notice that promises another
  angle and echoes nothing ("몰라" is a verb; "몰라에 대해 설명해 드릴게요" was the notice that made this
  rule, and `_VERBISH_END` now rejects finite verb endings as topics). A short reply with no question
  cue after a tutor turn that ended in "?" (`previous_turn=last_assistant_turn(context)`) is the
  student's **answer** and gets an `ANSWER` notice, never a topic echo. Korean particles follow the *spoken* form of the topic via
  `pronounce.hangulize`, so "TCP" takes 요, not 이요. It is a pure rule-based function with an
  injectable RNG — no model call — so it costs nothing on the turn and can be spoken before any
  validation has run: the only words in it that are not ours are the student's. A second model on
  the hot path was tried for visuals and removed (see `visual_router` below); do not reintroduce one
  here. On the cascade the notice is also **spoken** (`VOICE_SPOKEN_FILLER`), because a
  validated-then-released reply makes a slow turn pure silence. `_FillerSpeech` starts synthesizing
  it alongside the brain and decides when its first audio is ready: reply already there → drop it
  unheard, still thinking → play all of it.
  A spoken filler always delays the answer behind it, so it must only cover dead air that happened,
  and it must be entirely emitted before the reply's audio — the client plays audio in arrival order.
  It is sent as `AgentFiller(transient=True)`, which tells the UI to let the answer replace it rather
  than leave an identical line in the transcript every turn; Grok's own generated filler is a real
  turn and stays. Its audio carries `AgentAudio(filler=True)` so the UI's 첫 음성 badge keeps timing
  the *answer* — the notice only plays on turns slow enough to need it, so timing it would report a
  fast number on exactly the slowest turns.
- **The notice opens the turn's bubble, so every way a turn can die must now close it.** Before it
  existed, a spoken turn created no bubble until its first token, so an abandoned turn left nothing
  behind. Now barge-in (`flush`), a `Failed` turn, and a dropped socket each have to end the pending
  turn in `course-agent-client.tsx`; a stale `pendingId` is what the *next* turn's notice and
  transcript patch, which renders the next answer above its own question. A turn still queued in
  `pendingTextRef` is the exception — it was never sent, so the reconnect will send it.
- **The turn draws its own clue, in the call that writes the words.** `SpokenTurn` carries
  `visual_kind/title/caption/latex/labels`; `drawn_clue` validates them through the same
  `brain.show_visualization` the text path uses, and `think_voice` returns them in
  `VoiceBrainResult.visualizations`, which `_run_text_turn` emits **before** the agent transcript
  and before the first sample of audio. So the student sees the clue and then hears the question
  about it, and the reply may point at it — the order `brain.think` always had.
  There used to be a second model (`visual_router.decide_visualization`) drawing it on a parallel
  task while the reply was already being spoken. It was measured never to disagree with the brain
  (0 vetoes in 6), cost ~3.6 s of voice-profile GPU per visual turn, gated `AgentTurnDone` — which
  froze the typing box for up to 5 s — logged the clue against the *following* turn, and authored
  student-visible Korean under a thinner prompt than the brain's. It is Grok-only now; do not
  reintroduce it on the cascade. A malformed clue is dropped with a warning and never retried: the
  words are what the student needs, and the retry budget belongs to them.
- **Materials first, web only as the fallback — enforced, not requested.** `think_voice` offers
  `search_trusted_web` only when the prefetched `course_materials.found` is false. The payload's own
  `instruction` field already said this in prose and the model searched anyway on about two thirds of
  turns, spending a round on a lookup the evidence had covered (and on a dead SearXNG, an error).
  Note this makes `RAG_SCORE_THRESHOLD` the knob that decides when the web is reachable at all: at
  the hash-embedding default of 0.1 almost anything counts as found.
- **Socratic teaching is a hint ladder the server enforces, not a paragraph the model is asked to
  follow.** Told only "give hints, ask one question", the 9B voice model answered "X가 뭔지
  모르겠어" with X's definition on 12 of 12 hint turns and ended 1 in 12 with a question. Now
  `finish_turn` makes the model classify the student first (`student_state`: new_question, stuck,
  wrong, partial, correct, wants_answer, social) and write the answer it is holding back
  (`withheld_answer`) *before* the words — schema order is generation order. `VoiceContext.hint_level`
  counts stuck turns on the current concept and `brain.socratic_stage` tells each turn exactly which
  rung applies (0 probe → 1 concrete hint → 2 show the first step → 3 reveal and ask for a restate);
  `wants_answer` jumps to the reveal, a new question or a correct answer resets to 0. Below the
  reveal rung `local_brain.socratic_violation` rejects a turn with no question, a turn that spends
  more than `HINT_BUDGET` characters before its question (a definition with "so why?" stapled on),
  or a turn whose words repeat ≥ 8 compacted characters of its own `withheld_answer`. That rejection
  is a **soft** retry (`MAX_SOFT_RETRIES`, separate from the hard budget and only while no hard
  retry has been spent), and it rewrites the *policy* too — the tool error alone got patched, not
  rewritten. A second lecture is spoken rather than failed. Measured by
  `scripts/eval_voice_hint_ladder.py` with the 27B as judge: reveals 12/12 → 5/24, ends in a
  question 1/12 → 23/24, scaffold 0/12 → 19/24, median turn 5.4 s → 6.9 s. The text path shares
  the prompt and stage but has no `finish_turn`, so the model never classifies the student there;
  `brain.think` moves the ladder only on what the words alone decide
  (`rule_based_student_state`: `filler.is_stuck` → stuck, `filler.is_social` → social, anything
  else leaves the level alone) and regenerates a repeated turn once.
- **"몰라" after a tutor question is stuck, whatever the model called it.** The prompt and schema
  list "X가 뭔지 모르겠어" under `new_question`, and the 9B read a bare "몰라" the same way often
  enough to reset the ladder to 0 and ask the same probe again. `validate_spoken_turn` overrides
  the model's `student_state` to `stuck` when `rule_based_student_state` says so — only when there
  is a previous assistant turn to be stuck on, and never when the student names a concept. The
  stage section also quotes the tutor's last question (`last_assistant_question`): told only "do
  not repeat yourself", the model had nothing concrete to differ from. Every released turn logs
  `student_state` and `hint_level` (`voice turn …` / `text turn …`, and in the cascade's
  `metrics=` line) so the ladder can be read off the logs. Measured live with
  `scripts/eval_voice_hint_ladder.py --no-guards` vs guards on the 9B
  (`docs/evaluations/voice-hint-ladder-guards-20260914.md`): a bare "모르겠어" read as stuck 3/6 →
  6/6, repeated probe after it 2 → 0, judge columns within noise, p90 turn 9.8 s → 13.8 s from the
  extra rewrite. **The text path could not be measured at the time**: `answer-text` runs the 27B
  with thinking on (only the voice profile sets `enable_thinking: False`), and under
  `LLM_MAX_TOKENS=1024` 11 of 14 turns truncated after ~38 s before any retry. The text profile
  now has its own budget (`TEXT_LLM_MAX_TOKENS`, default 4096, `LLMService.default_max_tokens`),
  and a turn that still truncates raises `LLMTruncatedError`, which `brain.think` answers by
  retrying that round once with `thinking=False` ("생각이 길어져 답부터 씁니다" in the trace) after a
  `rewind` event; re-measure the ladder on the text path with those in place.
- **A turn that repeats the previous question is rejected and regenerated once**, checked before
  the whole-turn restatement below: `repeats_previous_question` compares only the last question
  sentence of the draft with the one the student already failed (`REPEAT_RATIO` on the compacted
  text, ignoring questions under 6 characters such as "왜 그럴까요?"), because a draft that rewords its
  hint and keeps its question passes the whole-turn check and leaves the student on the same rung.
  Both live in `brain.py` so the text path applies them too; `local_brain` re-exports them.
- **A turn that restates the previous one is rejected and regenerated once.** The same evidence is
  supplied every turn, so the model's failure mode is re-delivering it — verbatim after an
  unintelligible turn, reworded after "더 알려줘". `restates_previous_turn` catches both (containment,
  or a 0.80 similarity ratio; a legitimately different answer measured at most 0.66 against the live
  model). Only while a retry is left: a repeated answer is a poor turn, no answer is a worse one.
  **Do not "help" by putting the previous turn in the prompt** — it is already in the conversation,
  and injecting the text again measurably *induces* the copying (mean similarity 0.50 vs 0.29).
- **The reply is written to be heard, not read.** The policy asks for Korean only — no English
  gloss in brackets, no LaTeX — because both are unsayable: `소프트맥스 (softmax)` becomes the same
  word twice once the English is converted, and `$e^x$` has no reading at all. Note the voice path
  only receives `SYSTEM_PROMPT`'s **first paragraph**, so a rule that must reach it belongs there.
  `for_speech` drops notation, and drops a bracket only when it *reads as* the word before it, so
  `(A)와 (B)` stays two options rather than vanishing; the chat bubble typesets
  notation with the MathJax already loaded in `layout.tsx`, so a slip renders instead of looking
  broken.
- **Nothing Latin reaches the voice.** It runs in Korean mode, so English is
  mispronounced and can come out as a tonal artefact. `for_speech` sends every Latin term through
  `pronounce.hangulize`: `TERMS` first (the course vocabulary, which no rule engine derives),
  acronyms letter by letter, then a grapheme fallback so an unknown word is still sayable. Display
  text keeps its own spelling — only the copy on its way to the speech server is converted. Adding a
  term to `TERMS` is always better than tuning the fallback rules.
- **The PCM stream is sample-aligned by `SpeechClient`, not by whoever consumes it.** `aiter_bytes`
  splits the body wherever the transport did, and a consumer handed half a sample either drops it —
  shifting every later sample by a byte, which is white noise — or refuses the buffer. The client
  also resamples to the output device's rate itself (`app/lib/pcm.ts`), carrying state across chunks:
  letting the browser resample each chunk independently leaves a step at every boundary.
- **Submitting a typed turn interrupts the agent.** `course-agent-client.tsx` flushes its own
  playback on submit: only a spoken barge-in gets a server `flush`, and typing is the whole way a
  student with no microphone interrupts, so without it the agent talks through its previous answer.
- **One turn per generation.** Speech onset claims a generation, so an utterance ending normally has
  nothing to cancel — but a turn typed *while* that utterance was still being spoken claims one
  after it. `send_audio` therefore supersedes any in-flight turn at the endpoint; without it both
  turns answer into the same generation and their audio interleaves in one playback stream.

WebSockets cannot set headers, so `WS /api/voice/courses/{id}/stream` takes the JWT as a `token`
query parameter and re-runs `authorize_course_access` itself.

### The typed path shows its work (text only)

`answer-text/stream` is NDJSON, and besides `status`/`token`/`done`/`error` it now carries the
turn's trace, which only the typed path has -- a spoken turn is heard, not watched:

- `step` -- one line of the agent's work, **addressed by `key`**: the first event with a key adds
  the line, a later one with the same key updates it in place, so "강의자료를 검색하는 중" becomes
  "강의자료 3곳을 찾았어요" where it was. `state` is `running`/`done`/`failed`; `label` and `detail`
  are Korean text composed **server-side in `brain.py`** (`emit_step`, `_tool_step_labels`) from tool
  arguments and results -- never from model output, so nothing unreviewed reaches the screen before
  the answer. Keys: `attachments`, `recall`, `material`, `llm-<round>`, `tool-<round>-<index>`.
- A step's `detail` on failure is a Korean phrase for the few server-composed error classes and empty
  otherwise -- the tool's `error` string (a Python exception, an HTTP error) is for the model, which
  gets the tool result verbatim, never for the screen. A model call that raises marks its `llm-<n>`
  step `failed` before the route's `error` event, and the UI marks any step still running as failed
  when the stream errors, so nothing spins under an error message.
- `rewind` -- the answer text streamed so far is not the answer; the UI drops it and the next
  tokens replace it. Sent when a repeated draft is regenerated and when a truncated turn is
  retried with thinking off. Before it, a regenerated draft was appended to the discarded one on
  screen until `done` replaced the whole bubble.
- `thinking` -- a delta of the model's own raw reasoning, **keyed to the model round it happened
  in** (`key: "llm-<n>"`). vLLM runs the text model with `--reasoning-parser qwen3` and thinking on,
  so `reasoning_content` (newer releases: `reasoning`) arrives in its own delta field;
  `LLMService.stream_tool_turn(on_reasoning=...)` forwards it and `brain.think` turns it into this
  event. It never becomes part of the reply. In the UI it sits behind a "생각 원문 보기" disclosure:
  raw chain of thought is long, fast and often English, and shown live it scrolled past unread.
- `thought` -- **what the student actually watches**: one Korean headline of what the model is doing
  now ("이름을 뜯어보며 접근 방식을 정한다"), the way Codex shows reasoning summaries.
  `voice/thoughts.py` (`ThoughtSummarizer`) collects the round's reasoning deltas and, every
  `THOUGHT_SUMMARY_MIN_CHARS` and `THOUGHT_SUMMARY_INTERVAL_SECONDS`, asks the **voice-profile** model
  (9B, thinking off, `LLMService.summarize_reasoning`) for the headline of the new part. It runs
  beside the turn as background tasks, one at a time so headlines stay in order, flushes when the
  first answer token arrives and is cancelled when the round ends -- it never gates the answer, and a
  failure (voice model down) is skipped. This is the one deliberate second model on the typed path;
  it is off with `TEXT_THOUGHT_SUMMARIES=false`. The round's `done` step carries the split
  "생각 4.1초 · 작성 2.1초" (time to the first answer token vs the rest). The policy for the typed
  path ends with `THINKING_LANGUAGE_NOTE` ("Think in Korean…"); the 27B does not always obey it,
  which is another reason the headlines, not the raw text, are what is shown. The mock emits
  `MOCK_REASONING` and a mock headline so the panel works with no model server.

**The typed reply is read, not heard, so it may be long.** `SOCRATIC_PROMPT`'s "짧게", "힌트 한 문장
(90자 이내)" exist for a spoken 220-character utterance; `answer_instructions(voice=False)` appends
`TEXT_REPLY_NOTE`, which lifts them for the screen (2~5 sentences, a paragraph or two, the ladder
still enforced) -- the voice path never sees it. `THINKING_LANGUAGE_NOTE` also asks the model to
**think briefly**: told nothing about length, the 27B spent 48 s on "소프트맥스가 뭐야?" weighing whether
to call a tool; measured after the note, "안녕" thought 1.5-7 s. The wait before the first word *is*
the reasoning -- the answer itself streams at ~25 tokens/s once it starts. The stream was measured
line by line through the Next.js dev rewrite (`:3000`) and directly (`:8000`): both deliver each
NDJSON line as it is written. `answer_text_stream` still sends `Cache-Control: no-cache, no-transform`
and `X-Accel-Buffering: no` so a compressing or buffering proxy (nginx, a CDN) cannot hold the
body until the end.

`course-agent-trace.tsx` renders it the way Codex does: one quiet grey line, folded by default --
"생각 중…" with a shimmer sweeping across the text while the turn runs, trailed by the one thought being
written right now; "N초 동안 생각함" once it is answered, "생각이 중단됨" after an error -- that opens on
a click onto the steps, each with its headlines as their own lines (fading in, a few seconds apart)
and the raw reasoning folded beneath, hung off a soft vertical rule. The pending bubble stays empty until the progress notice or
the first token fills it, so the line is all the student sees while waiting. The voice path
(`think_voice`, the WebSocket) is untouched.

### Attachments: images and PDFs on a typed question (text only)

`POST /api/voice/courses/{id}/attachments` stores one file (image or PDF) under
`uploads/voice/attachments/<user>/`, validated but **not read**; `VoiceQuestion.attachment_ids`
carries it on the next typed turn, and the reading happens there, as the `attachments` step the
student watches. `app/services/voice/attachments.py` owns all of it -- `brain.py` only receives the
finished `AttachmentContent` records, and never touches a file or a model SDK.

- Ownership is checked against the stored sidecar record (user **and** course), so an id copied from
  another learner resolves to 404; the request-size middleware bounds the upload path too (with its
  own, larger limit than course materials: a textbook is bigger than a lecture deck).
- **A long PDF is read through a private index, not whole.** Up to `ATTACHMENT_INLINE_MAX_PAGES` (8)
  the file goes into the turn as text; beyond that (up to `ATTACHMENT_MAX_PAGES`, 600) the upload
  route queues `attachment_index.build_index` as a background task -- page text → `create_chunks` →
  `EmbeddingService`, exactly the material pipeline, but written to `<file>.index.json` beside the
  file in the learner's directory, never to the course vector store, so nothing a student uploads can
  surface for anyone else. `<file>.status.json` carries progress; `GET .../attachments/{id}` returns
  it and the composer polls it ("색인 중 120/312쪽") and holds the send until `ready` (the answer
  routes answer 409 while indexing, 422 after a failure). On each turn `read_attachment` embeds the
  question (`retrieval_query`, so a short follow-up carries the previous turn) and pulls the
  `ATTACHMENT_INDEX_TOP_K` best chunks as `AttachmentContent(mode="excerpt", pages_used=[...])`; the
  trace says "교재.pdf 12, 13쪽 참고". Pages without a text layer are skipped in this mode (a scanned
  book would cost hundreds of vision calls; an all-scan PDF fails with a message). The composer keeps
  an excerpted file **pinned across turns** until the student removes it, because a textbook is asked
  about many times; inline files are consumed by the turn that carries them.
- **The cost of reading a file is bounded at upload, before it is stored.** Every enrolled student can
  upload, and PDFium materializes a whole content stream inside `get_textpage()` -- a 72 KB PDF whose
  one page inflates to 20 M text operators cost seconds and gigabytes *while holding the process-wide
  PDFium lock ingestion shares* (PDFium is not thread safe, so a second lock is not an option). So
  `_inspect_pdf` walks each page's `/Contents` with pypdf and stream-decompresses Flate with a cap
  (`PAGE_CONTENT_MAX_BYTES`, `PDF_CONTENT_MAX_BYTES`), refuses embedded images over `MAX_IMAGE_PIXELS`
  from their header, and `_verify_image` does the same for a standalone image. Per-learner storage is
  bounded too (`ATTACHMENT_MAX_STORED_FILES/BYTES`, oldest evicted), and `_read_attachments` gives up
  after `ATTACHMENT_READ_TIMEOUT_SECONDS` and answers without the files.
- **The text model looks at the picture itself when it can.** Qwen3.8-27B is a vision-language model;
  with `TEXT_LLM_VISION=true` here and the model server keeping its encoder
  (`TEXT_LANGUAGE_MODEL_ONLY=false` in `SKKU_AI_model_server/.env`, `--limit-mm-per-prompt` from
  `TEXT_MAX_IMAGES`), a photo or a text-less PDF page becomes `AttachmentContent(mode="vision",
  images=[...])` and `brain.think` sends the user message as text-and-image parts
  (`attachments.image_parts`; `_ensure_openai_messages` keeps them, the Anthropic adapter converts
  them). Up to `ATTACHMENT_DIRECT_IMAGES_MAX` per request, about 1k tokens per megapixel each. The
  history stays text (an image is too big to keep): the heading says the model looked at it, and the
  turn's images are kept in `VoiceContext.recent_images` and sent **once more with the next
  question**, so "그럼 2번은?" still sees the photo; `restore_history` reloads them from the learner's
  directory after a reload. If the server turns out to be text-only it answers 400, which
  `LLMService` raises as `LLMBadRequestError`; `think` then transcribes the images through the 9B
  (`transcribe_images`), sends `rewind`, and retries the round with the transcripts -- so the flag can
  be on before the model server is restarted. Images are never logged.
- Otherwise reading reuses the ingestion pieces: PDFium for a page's native text, and the vision model
  through `LLMService.read_document_image` for a photo or a page with under `MIN_NATIVE_TEXT_CHARS`
  of text. `ATTACHMENT_MAX_VISION_PAGES` bounds vision calls per turn. `AttachmentContent.text` holds only what
  was read: pages skipped for budget or failed in vision are listed (`skipped_pages`,
  `unreadable_pages`) and rendered as notes, never written into the text, so the trace, the character
  counts and the retrieval hint cannot mistake a status line for content.
- The text joins the **student's user message** (`model_content`: question, then a header that marks
  the block as data, then one section per file), so the model sees it where the student put it. The
  history keeps a shorter copy (`history_content`, `ATTACHMENT_HISTORY_CHARS`), and when the model is
  called only the newest `ATTACHMENT_HISTORY_TURNS` user turns keep their file text at all
  (`collapse_old_attachments`; older turns keep the file names). The arithmetic: the text model has a
  16k-token window and Korean runs ~0.56 tokens per character, so 6000 + 2000 chars of file text plus
  the prompt fits and six turns of 2000 would not. `retrieval_hint` gives course-material search a
  400-character excerpt.
- `ChatLog.question` keeps only the student's words; the files and their text go in
  `retrieval_result.attachments`, which `voice_log.restore_history` uses to rebuild the message when
  a conversation is reopened, and which `/api/chat/sessions/{id}` returns (without text) as
  `attachments` for the history replay. The professor/admin log detail lists them by name.
- Attachments are refused while the voice panel is open (the composer disables the button and keeps
  the files for the next typed-only turn) -- a typed turn on the voice path goes over the WebSocket to
  `think_voice`, which knows nothing about files.

**Test gotcha:** FastAPI (0.140) resolves `Depends(get_settings)` lazily, so monkeypatching a route
module's `get_settings` (e.g. `voice_routes.get_settings`) before its first request makes that route
call the patched lambda instead of the fixture's `dependency_overrides` -- patch `brain.get_settings`
and let the routes take the fixture's settings through `Depends`.

### Frontend

The UI is a clone of SKKU i-Campus (Canvas LMS, <https://canvas.skku.edu/>): a 76px dark-blue global
rail, a 64px top bar, a 204px course menu. **i-Campus menu entries this MVP does not implement stay
visible but inactive** (rendered as `<span>` instead of `<Link>`) so the shell keeps matching the
real LMS — do not delete them to "clean up".

`AppShell` renders the top bar for role pages; inside a course, `CourseWorkspaceClient` renders its
own identical top bar with the course context, which is why `AppShell` suppresses its own when
`data-course-workspace="true"`.

Students have exactly one question surface: COURSE AGENT inside a course. There is no separate
"AI 질문" menu item, course tab, or route — 대화 이력 links back into COURSE AGENT with
`?sessionId=`, which the backend rehydrates. Do not reintroduce them.

Styles: `app/globals.css` (shell and pages), `app/course-agent.css` (Course Agent symbol and chat panel).
`packages/shared` exports the domain types; `app/lib/api.ts` and `app/lib/voice-api.ts` are the only
places that talk to the backend.

## Configuration

Copy `.env.example` to `.env`. Notable behaviour:

- `USE_MOCK_LLM=true` and the local hash embedding mean the whole app runs with no API key.
- `ANTHROPIC_API_KEY` + `CLAUDE_MODEL` drive both `/api/chat` and COURSE AGENT's text answers.
- `XAI_API_KEY` is only for the legacy `VOICE_PROVIDER=grok` path. Blank leaves the mic button
  disabled while text chat keeps working; do not gate text answers on it.
- `VOICE_LLM_MAX_TOKENS` must fit a whole `finish_turn` call (220 Korean characters plus its JSON
  envelope). Too small and the generation truncates, burning the single retry.
- `MOSS_PROJECT_ID`/`MOSS_PROJECT_KEY` are optional; without them weak concepts go to a local file.
- Settings are read through `app.core.config.Settings` (pydantic-settings). Do not add a second
  dotenv loader — a `load_dotenv()` anywhere leaks `.env` into `os.environ` and silently changes
  `JWT_SECRET` resolution for the whole app.
