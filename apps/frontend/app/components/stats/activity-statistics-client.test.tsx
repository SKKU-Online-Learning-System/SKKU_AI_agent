// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivityStatisticsClient } from "./activity-statistics-client";

const apiMocks = vi.hoisted(() => ({ getActivityStatistics: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getActivityStatistics: apiMocks.getActivityStatistics };
});

const statistics = {
  days: 30,
  since: "2026-09-06T00:00:00Z",
  totals: {
    userCount: 3,
    activeUserCount: 1,
    loginCount: 2,
    activeMinutes: 25.5,
    turnCount: 4,
    promptTokens: 400,
    completionTokens: 80,
    totalTokens: 480
  },
  byDate: [{ date: "2026-10-05", logins: 2, turns: 4, tokens: 480, activeMinutes: 25.5 }],
  users: [
    {
      userId: "u1",
      name: "김학생",
      email: "student@skku.edu",
      loginCount: 2,
      lastLoginAt: "2026-10-05T10:00:00Z",
      activeMinutes: 25.5,
      turnCount: 4,
      promptTokens: 400,
      completionTokens: 80,
      totalTokens: 480
    },
    {
      userId: "u2",
      name: "관리자",
      email: "admin@skku.edu",
      loginCount: 0,
      lastLoginAt: null,
      activeMinutes: 0,
      turnCount: 0,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0
    }
  ]
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ActivityStatisticsClient", () => {
  it("renders totals, charts and the per-user table, and refetches on a range change", async () => {
    apiMocks.getActivityStatistics.mockResolvedValue(statistics);

    render(<ActivityStatisticsClient />);

    await waitFor(() => expect(screen.getAllByText("김학생").length).toBeGreaterThan(0));
    expect(apiMocks.getActivityStatistics).toHaveBeenCalledWith(30);
    expect(screen.getByRole("img", { name: "일자별 추이" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "학생별 순위" })).toBeInTheDocument();
    expect(screen.getByText("10/5 · 4회")).toBeInTheDocument();
    expect(screen.getAllByText("student@skku.edu").length).toBe(2);
    expect(screen.getByText("admin@skku.edu")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "기간" }), { target: { value: "7" } });
    await waitFor(() => expect(apiMocks.getActivityStatistics).toHaveBeenCalledWith(7));

    fireEvent.click(screen.getByRole("button", { name: /^토큰/ }));
    expect(screen.getByText("10/5 · 480")).toBeInTheDocument();
  });
});
