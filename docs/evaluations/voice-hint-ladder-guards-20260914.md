# Hint ladder: the same probe after "몰라" (2026-09-14)

Live A/B of the two server rules added against the repeated Socratic probe, run with
`scripts/eval_voice_hint_ladder.py` (5 scripted students, 2 repetitions, 27B judge).

- **guards**: the tutor's last question is quoted in the stage section, and a bare
  "몰라"/"모르겠어" after a tutor question is forced to `student_state=stuck` on the server
  (`rule_based_student_state`), so the ladder climbs instead of resetting.
- **noguards** (`--no-guards`): both switched off; everything else, including the older
  whole-turn restatement guard, identical.

## Voice path (Qwen3.5-9B, `think_voice`), 28 teach turns per run

| run | reveals answer | ends in one question | scaffold | responds | repeated question | bare "모르겠어" read as stuck | median turn | p90 turn |
|---|---|---|---|---|---|---|---|---|
| noguards | 12/28 | 28/28 | 14/28 | 26/28 | 3/20 | 3/6 | 6.9 s | 9.8 s |
| guards | 9/28 | 26/28 | 17/28 | 27/28 | 3/20 | **6/6** | 6.9 s | 13.8 s |

What the repeated questions were:

- **noguards**: 2 of 3 are the reported failure exactly — the student said "모르겠어", the model
  called it `partial`, the level stayed 0 and the previous probe came back verbatim
  (`sdpa_user_case` rep1, `softmax_stuck` rep0). The third is a greeting repeated.
- **guards**: 0 repeats after a bare "모르겠어". One repeat followed "그러게" (not yet in the
  stuck rule at the time of the run; added afterwards), one is the greeting case where the
  model answered the concept question with its greeting again and the single soft retry was
  spent.

The judge columns move within noise at n=28 (fewer reveals, more scaffolds, two fewer
question endings). The cost is the retry: p90 latency rose ~4 s because a repeated question
now triggers the soft rewrite.

Files: `voice-hint-ladder-{guards,noguards}-voice-20260914.jsonl` (per-turn replies,
`student_state`, `hint_level`, `repeated_question`, judge verdicts).

## Text path (`answer-text` → `brain.think`, Qwen3.8-27B): not measurable

11 of 14 turns in the guards run failed with `Model output was truncated before completion`
or `도구 호출 arguments가 올바른 JSON이 아닙니다`, each after ~38 s. Direct probe of the 27B
shows thinking is **on by default** for the text profile (`reasoning_content` present, 93 of 123
completion tokens were reasoning on a one-sentence prompt); `_qwen_request` only sets
`enable_thinking: False` for the voice profile, and `LLM_MAX_TOKENS=1024` is spent on reasoning
under the long Socratic system prompt. This predates the ladder change (the first truncation in
every run is the opening concept question, before any retry) and blocks any A/B on this path.
The noguards text run was stopped as it would only reproduce the errors. Partial file:
`voice-hint-ladder-guards-text-20260914.jsonl`.

Fix to evaluate separately: disable thinking for the text profile too, or raise its token
budget; then rerun `--path text`.
