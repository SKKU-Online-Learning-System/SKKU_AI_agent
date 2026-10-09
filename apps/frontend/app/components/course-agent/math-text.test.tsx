// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MathText, hasMath } from "./math-text";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("hasMath", () => {
  it("spots the notation a reply is not supposed to contain", () => {
    expect(hasMath("지수함수 $e^x$ 를 적용해요.")).toBe(true);
    expect(hasMath("\\frac{a}{b} 형태예요.")).toBe(true);
    expect(hasMath("\\(x\\) 를 보세요.")).toBe(true);
  });

  it("leaves ordinary Korean alone", () => {
    expect(hasMath("두 확률의 합은 1이 됩니다.")).toBe(false);
    // A lone dollar is money, not math.
    expect(hasMath("가격은 $ 기호로 씁니다.")).toBe(false);
  });
});

describe("MathText", () => {
  it("typesets a reply that contains notation, so it is not shown raw", async () => {
    const typesetPromise = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("MathJax", { typesetClear: vi.fn(), typesetPromise });

    render(<MathText text="지수함수 $e^x$ 를 적용해요." />);

    expect(screen.getByText(/지수함수/)).toBeInTheDocument();
    expect(typesetPromise).toHaveBeenCalled();
  });

  it("does not call the typesetter for an ordinary reply", () => {
    const typesetPromise = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("MathJax", { typesetClear: vi.fn(), typesetPromise });

    render(<MathText text="두 확률의 합은 1이 됩니다." />);

    expect(typesetPromise).not.toHaveBeenCalled();
  });

  it("renders even when MathJax never loaded", () => {
    vi.stubGlobal("MathJax", undefined);
    render(<MathText text="지수함수 $e^x$ 를 적용해요." />);
    expect(screen.getByText(/지수함수/)).toBeInTheDocument();
  });
});
