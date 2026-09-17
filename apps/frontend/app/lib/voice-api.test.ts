// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import type { VoiceTraceStep } from "./voice-api";
import { streamVoiceAnswer } from "./voice-api";

function ndjsonResponse(events: Array<Record<string, unknown>>, ok = true): Response {
  const body = events.map((event) => JSON.stringify(event)).join("\n") + "\n";
  // Split mid-line to prove the reader reassembles partial chunks.
  const encoder = new TextEncoder();
  const cut = Math.floor(body.length / 2);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body.slice(0, cut)));
      controller.enqueue(encoder.encode(body.slice(cut)));
      controller.close();
    }
  });
  return {
    body: stream,
    json: async () => ({}),
    ok,
    status: ok ? 200 : 503
  } as unknown as Response;
}

describe("streamVoiceAnswer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dispatches status, steps, thinking and tokens, then resolves with the done event", async () => {
    const done = {
      attachments: [{ chars: 12, id: "att-1", kind: "pdf", name: "notes.pdf", pages: 2, size: 10 }],
      log_id: "log-1",
      material_sources: [],
      reply: "경사하강법은 기울기를 따라 내려가요.",
      safety: { blocked: false, category: "normal" },
      session_id: "session-1",
      sources: [],
      timings: { total: 900 },
      tools: [],
      transcript: "경사하강법이 뭐야?",
      type: "done",
      visualizations: []
    };
    const fetchMock = vi.fn().mockResolvedValue(
      ndjsonResponse([
        { text: "경사하강법이요? 잠깐 정리해 볼게요.", type: "status" },
        { key: "material", label: "강의자료를 검색하는 중", stage: "material", state: "running",
          type: "step" },
        { key: "llm-1", text: "정의를 먼저 확인한다.", type: "thinking" },
        { key: "llm-1", text: "정의부터 확인한다", type: "thought" },
        { elapsed_ms: 300, key: "material", label: "강의자료 1곳을 찾았어요", stage: "material",
          state: "done", type: "step" },
        { text: "경사하강법은 ", type: "token" },
        { text: "기울기를 따라 내려가요.", type: "token" },
        done
      ])
    );
    vi.stubGlobal("fetch", fetchMock);
    const tokens: string[] = [];
    const steps: VoiceTraceStep[] = [];
    const thoughts: Array<[string, string | undefined]> = [];
    const headlines: Array<[string, string | undefined]> = [];
    const statuses: string[] = [];

    const answer = await streamVoiceAnswer(
      "course-1",
      { attachment_ids: ["att-1"], mode: "socratic", text: "경사하강법이 뭐야?" },
      {
        onStatus: (message) => statuses.push(message),
        onStep: (step) => steps.push(step),
        onThinking: (text, key) => thoughts.push([text, key]),
        onThought: (text, key) => headlines.push([text, key]),
        onToken: (token) => tokens.push(token)
      }
    );

    expect(statuses).toEqual(["경사하강법이요? 잠깐 정리해 볼게요."]);
    expect(steps.map((step) => [step.key, step.state])).toEqual([
      ["material", "running"],
      ["material", "done"]
    ]);
    expect(thoughts).toEqual([["정의를 먼저 확인한다.", "llm-1"]]);
    expect(headlines).toEqual([["정의부터 확인한다", "llm-1"]]);
    expect(tokens.join("")).toBe(done.reply);
    expect(answer.reply).toBe(done.reply);
    expect(answer.attachments[0].name).toBe("notes.pdf");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/voice\/courses\/course-1\/answer-text\/stream$/);
    expect(JSON.parse(String(init.body))).toEqual({
      attachment_ids: ["att-1"],
      mode: "socratic",
      text: "경사하강법이 뭐야?"
    });
  });

  it("lets a rewind drop the draft that streamed before it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        ndjsonResponse([
          { text: "첫 초안", type: "token" },
          { type: "rewind" },
          { text: "둘째 초안", type: "token" },
          { attachments: [], log_id: "l", material_sources: [], reply: "둘째 초안",
            safety: { blocked: false, category: "normal" }, session_id: "s", sources: [],
            timings: {}, tools: [], transcript: "q", type: "done", visualizations: [] }
        ])
      )
    );
    const seen: string[] = [];

    await streamVoiceAnswer(
      "course-1",
      { mode: "socratic", text: "q" },
      { onRewind: () => seen.push("<rewind>"), onToken: (token) => seen.push(token) }
    );

    expect(seen).toEqual(["첫 초안", "<rewind>", "둘째 초안"]);
  });

  it("turns a server error event into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        ndjsonResponse([
          { key: "llm-1", label: "답을 만들지 못했어요", stage: "llm", state: "failed", type: "step" },
          { message: "답변 생성 서비스를 사용할 수 없습니다.", type: "error" }
        ])
      )
    );
    const steps: VoiceTraceStep[] = [];

    await expect(
      streamVoiceAnswer(
        "course-1",
        { mode: "socratic", text: "질문" },
        { onStep: (step) => steps.push(step), onToken: () => undefined }
      )
    ).rejects.toMatchObject({ message: "답변 생성 서비스를 사용할 수 없습니다.", status: 503 });
    // The failed step reached the handler before the error ended the stream.
    expect(steps.map((step) => step.state)).toEqual(["failed"]);
  });

  it("rejects when the stream ends without a done event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(ndjsonResponse([{ text: "절반만", type: "token" }]))
    );

    await expect(
      streamVoiceAnswer("course-1", { mode: "socratic", text: "질문" }, { onToken: () => undefined })
    ).rejects.toBeInstanceOf(ApiError);
  });
});
