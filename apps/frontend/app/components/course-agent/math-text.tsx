"use client";

import { useEffect, useRef } from "react";

declare global {
  interface Window {
    MathJax?: {
      typesetPromise?: (elements?: Element[]) => Promise<void>;
      typesetClear?: (elements?: Element[]) => void;
    };
  }
}

/** Whether a reply contains math worth handing to the typesetter. */
export function hasMath(text: string): boolean {
  return /\$[^$]+\$|\\\(|\\\[|\\[a-zA-Z]+\s*\{/.test(text);
}

/**
 * A reply, typeset if it turns out to contain math.
 *
 * The agent is told to say formulas in words and leave the notation to
 * show_visualization, because the reply is read aloud and `$e^x$` cannot be.
 * When it writes notation anyway the student used to see the raw source, so this
 * renders it rather than leaving something that looks broken on screen.
 */
export function MathText({ text }: { text: string }) {
  const host = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element || !hasMath(text)) return;
    // Typesetting rewrites the node, so drop what a previous pass left behind
    // before MathJax reads the text again -- replies are patched as they stream.
    window.MathJax?.typesetClear?.([element]);
    void window.MathJax?.typesetPromise?.([element]).catch(() => undefined);
  }, [text]);

  return (
    <div className="voice-bubble" ref={host}>
      {text}
    </div>
  );
}
