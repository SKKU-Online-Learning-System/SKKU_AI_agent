"""Paired, serial evaluation using the existing synthetic voice fixtures."""
import asyncio
import contextlib
import io
import json
import random
from types import SimpleNamespace

import eval_voice_socratic as evaluation


async def main():
    models = [("Qwen/Qwen3.5-9B", "http://localhost:8002/v1"),
              ("Qwen/Qwen3.8-27B", "http://localhost:8001/v1")]
    cases = ["hesitation_softmax", "ack_softmax", "ack_paraphrase", "stage_half",
             "stage_reason", "stage_summary", "stage_correct_agent", "stop_paraphrase",
             "wrong", "frustrated", "os", "assignment"]
    assert set(cases) <= {case[0] for case in evaluation.CASES}
    rng = random.Random(20260909)
    for repeat in range(-1, 3):
        ordered = ["greeting"] if repeat == -1 else rng.sample(cases, len(cases))
        for index, case in enumerate(ordered):
            for model, url in models[::1 if (repeat + index) % 2 else -1]:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    await evaluation.main(SimpleNamespace(
                        trace=False, model=model, base_url=url, repeat=1, case=[case]))
                row = json.loads(output.getvalue().splitlines()[0])
                row.update(repeat=repeat, warmup=repeat == -1)
                print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
