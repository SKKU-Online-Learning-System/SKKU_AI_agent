"use client";

import type { VoiceTraceStep } from "../../lib/voice-api";
import { UiIcon } from "../ui/ui-icon";

/**
 * What the agent did for one typed turn: the steps it took and, when the model
 * streamed it, the reasoning behind the answer.
 *
 * Folded to one quiet line by default -- a shimmering "생각 중…" while the turn
 * runs, with the headline of what the model is doing right now trailing after
 * it, and "N초 동안 생각함" once it is answered. The line opens on a click to show
 * the steps, each with the headlines of the reasoning that ran under it (one
 * every few seconds, written by the server), and the raw reasoning behind a
 * small disclosure for whoever wants the whole of it.
 */
export type TurnTrace = {
  steps: VoiceTraceStep[];
  /** Raw reasoning that arrived without a step to belong to. */
  thinking: string;
  /** Headlines that arrived without a step to belong to. */
  thoughts: string[];
  done: boolean;
  /** The turn ended in an error; whatever was still running did not finish. */
  failed: boolean;
  open: boolean;
  /** When the turn started (ms since epoch), so the folded line can say how long it took. */
  startedAt: number;
  durationMs?: number;
};

export const EMPTY_TRACE: TurnTrace = {
  done: false,
  failed: false,
  open: false,
  startedAt: 0,
  steps: [],
  thinking: "",
  thoughts: []
};

/** A fresh trace for a turn that starts now. */
export function startTrace(now: number = Date.now()): TurnTrace {
  return { ...EMPTY_TRACE, startedAt: now };
}

/** Close the trace once the answer is there. */
export function finishTrace(trace: TurnTrace, now: number = Date.now()): TurnTrace {
  return { ...trace, done: true, durationMs: Math.max(0, now - trace.startedAt) };
}

/** Close the trace after an error: nothing that was still running will finish. */
export function failTrace(trace: TurnTrace, now: number = Date.now()): TurnTrace {
  return {
    ...trace,
    done: true,
    durationMs: Math.max(0, now - trace.startedAt),
    failed: true,
    steps: trace.steps.map((step) =>
      step.state === "running" ? { ...step, state: "failed" as const } : step
    )
  };
}

/** Add a step, or update the one that already carries its key. */
export function upsertStep(steps: VoiceTraceStep[], step: VoiceTraceStep): VoiceTraceStep[] {
  const index = steps.findIndex((item) => item.key === step.key);
  if (index === -1) return [...steps, step];
  return steps.map((item, position) => (position === index ? { ...item, ...step } : item));
}

/**
 * Hang a reasoning delta under the step it was keyed to; a delta with no key,
 * or for a step that is not there, goes to the trace's own thinking.
 */
export function appendThinking(trace: TurnTrace, text: string, stepKey?: string): TurnTrace {
  if (stepKey && trace.steps.some((step) => step.key === stepKey)) {
    return {
      ...trace,
      steps: trace.steps.map((step) =>
        step.key === stepKey ? { ...step, thinking: (step.thinking ?? "") + text } : step
      )
    };
  }
  return { ...trace, thinking: trace.thinking + text };
}

/** Hang a headline under the step it was keyed to, or on the trace itself. */
export function appendThought(trace: TurnTrace, text: string, stepKey?: string): TurnTrace {
  const line = text.trim();
  if (!line) return trace;
  if (stepKey && trace.steps.some((step) => step.key === stepKey)) {
    return {
      ...trace,
      steps: trace.steps.map((step) =>
        step.key === stepKey ? { ...step, thoughts: [...(step.thoughts ?? []), line] } : step
      )
    };
  }
  return { ...trace, thoughts: [...trace.thoughts, line] };
}

/** What the model is doing right now: the newest headline of the running step. */
export function currentThought(trace: TurnTrace): string | null {
  const running = trace.steps.filter((step) => step.state === "running" && step.thoughts?.length);
  const source = running[running.length - 1]?.thoughts ?? trace.thoughts;
  return source.length ? source[source.length - 1] : null;
}

function formatElapsed(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${ms}ms`;
}

/** "3.2초", "12초": one decimal under ten seconds, whole seconds above. */
export function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)}초` : `${Math.round(seconds)}초`;
}

/** The one line shown when the trace is folded. */
export function traceSummary(trace: TurnTrace): string {
  if (!trace.done) return "생각 중…";
  if (trace.failed) return "생각이 중단됨";
  return trace.durationMs === undefined
    ? "생각 과정 보기"
    : `${formatDuration(trace.durationMs)} 동안 생각함`;
}

/**
 * The headlines of one stretch of reasoning, newest still forming while the
 * step runs, and the raw reasoning itself folded away beneath them.
 */
function Thoughts({
  thoughts,
  thinking,
  live
}: {
  thoughts: string[];
  thinking?: string;
  live: boolean;
}) {
  if (!thoughts.length && !thinking) return null;
  return (
    <div className="voice-trace-thinking">
      {thoughts.length ? (
        <ul aria-label="모델의 생각" className="voice-trace-thoughts">
          {thoughts.map((thought, index) => (
            <li
              className="voice-trace-thought"
              data-current={live && index === thoughts.length - 1 ? "true" : undefined}
              key={`${index}-${thought}`}
            >
              {thought}
            </li>
          ))}
        </ul>
      ) : live ? (
        <div className="voice-trace-thought" data-current="true">
          생각을 정리하는 중
        </div>
      ) : null}
      {thinking ? (
        <details className="voice-trace-raw">
          <summary>생각 원문 보기</summary>
          <div className="voice-trace-raw-text">{thinking}</div>
        </details>
      ) : null}
    </div>
  );
}

export function CourseAgentTrace({
  trace,
  onToggle
}: {
  trace: TurnTrace;
  onToggle: () => void;
}) {
  // The panel never scrolls itself. Reasoning arrives faster than it can be
  // read, and a view that jumps to the newest line on every delta cannot be
  // read at all; whoever opens it scrolls it.
  if (!trace.steps.length && !trace.thinking && !trace.thoughts.length && !trace.done) {
    return null;
  }

  const state = trace.failed ? "failed" : trace.done ? "done" : "running";
  const now = trace.done ? null : currentThought(trace);

  return (
    // The transcript is a live region; the work in progress is not read aloud
    // delta by delta, only the answer is.
    <div aria-live="off" className="voice-trace" data-open={trace.open} data-state={state}>
      <button
        aria-expanded={trace.open}
        className="voice-trace-toggle"
        onClick={onToggle}
        type="button"
      >
        <span className="voice-trace-summary">{traceSummary(trace)}</span>
        <UiIcon className="voice-trace-chevron" name="chevron" />
      </button>
      {now && !trace.open ? (
        <div className="voice-trace-now" key={now}>
          {now}
        </div>
      ) : null}
      {trace.open ? (
        <div className="voice-trace-body">
          {trace.steps.length ? (
            <ol aria-label="진행 단계" className="voice-trace-steps">
              {trace.steps.map((step) => (
                <li className="voice-trace-step" data-state={step.state} key={step.key}>
                  <div className="voice-trace-step-line">
                    <span aria-hidden="true" className="voice-trace-mark" />
                    <span className="voice-trace-text">
                      <span className="voice-trace-label">{step.label}</span>
                      {step.detail ? (
                        <span className="voice-trace-detail">{step.detail}</span>
                      ) : null}
                    </span>
                    {step.elapsed_ms !== undefined && step.state !== "running" ? (
                      <span className="voice-trace-elapsed">{formatElapsed(step.elapsed_ms)}</span>
                    ) : null}
                  </div>
                  {step.thinking || step.thoughts?.length ? (
                    <Thoughts
                      live={step.state === "running"}
                      thinking={step.thinking}
                      thoughts={step.thoughts ?? []}
                    />
                  ) : null}
                </li>
              ))}
            </ol>
          ) : null}
          {trace.thinking || trace.thoughts.length ? (
            <Thoughts live={!trace.done} thinking={trace.thinking} thoughts={trace.thoughts} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
