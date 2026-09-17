// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CourseWeakConceptStatistics, WeakConceptStatistics } from "../../lib/api";
import { WeakConceptStatisticsPanel } from "./weak-concept-statistics";

const apiMocks = vi.hoisted(() => ({
  getCourseWeakConceptStatistics: vi.fn(),
  getWeakConceptStatistics: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    getCourseWeakConceptStatistics: apiMocks.getCourseWeakConceptStatistics,
    getWeakConceptStatistics: apiMocks.getWeakConceptStatistics
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const seenAt = "2026-09-14T04:04:33+00:00";
const aiCounts = { new: 2, practicing: 1, mastered: 1 };
const noCounts = { new: 0, practicing: 0, mastered: 0 };

const overview: WeakConceptStatistics = {
  totals: {
    recordCount: 4,
    conceptCount: 3,
    studentCount: 3,
    statusCounts: aiCounts,
    averageMastery: 34,
    dueReviewCount: 2,
    lastActivityAt: seenAt,
    courseCount: 1
  },
  courses: [
    {
      courseId: "course-1",
      courseName: "인공지능개론",
      recordCount: 4,
      conceptCount: 3,
      studentCount: 3,
      statusCounts: aiCounts,
      averageMastery: 34,
      dueReviewCount: 2,
      lastActivityAt: seenAt
    },
    {
      courseId: "course-2",
      courseName: "소프트웨어공학",
      recordCount: 0,
      conceptCount: 0,
      studentCount: 0,
      statusCounts: noCounts,
      averageMastery: 0,
      dueReviewCount: 0,
      lastActivityAt: null
    }
  ]
};

const detail: CourseWeakConceptStatistics = {
  ...overview.courses[0],
  concepts: [
    {
      concept: "학습률 - 너무 크면 발산하는 이유",
      topic: "학습률",
      detail: "너무 크면 발산하는 이유",
      studentCount: 2,
      failureCount: 3,
      successCount: 1,
      statusCounts: { new: 1, practicing: 1, mastered: 0 },
      averageMastery: 17,
      lastSeenAt: seenAt,
      sampleNotes: ["학습률과 발산의 관계를 혼동함"]
    }
  ],
  topics: [{ topic: "학습률", conceptCount: 1, studentCount: 2, failureCount: 3, averageMastery: 17 }],
  students: [
    {
      studentId: "student-1",
      label: "ch***@skku.edu",
      conceptCount: 2,
      statusCounts: { new: 1, practicing: 0, mastered: 1 },
      averageMastery: 50,
      dueReviewCount: 1,
      lastSeenAt: seenAt,
      weakestConcepts: ["학습률 - 너무 크면 발산하는 이유"]
    }
  ],
  savedByDate: [{ date: "2026-09-14", count: 4 }],
  recentCaptures: [
    {
      concept: "학습률 - 너무 크면 발산하는 이유",
      status: "practicing",
      difficultyNote: "학습률과 발산의 관계를 혼동함",
      studentLabel: "ch***@skku.edu",
      masteryPercent: 34,
      lastSeenAt: seenAt
    }
  ]
};

describe("WeakConceptStatisticsPanel", () => {
  it("shows totals, the course table and opens the first course with records", async () => {
    apiMocks.getWeakConceptStatistics.mockResolvedValue(overview);
    apiMocks.getCourseWeakConceptStatistics.mockResolvedValue(detail);

    render(<WeakConceptStatisticsPanel audience="professor" />);

    expect(await screen.findByRole("heading", { name: "인공지능개론 상세" })).toBeInTheDocument();
    // The detail request fires from an effect after the heading appears.
    await waitFor(() =>
      expect(apiMocks.getCourseWeakConceptStatistics).toHaveBeenCalledWith("course-1")
    );
    // Once in the totals, once in the course row.
    expect(screen.getAllByText("3명")).toHaveLength(2);
    expect(screen.getByText("상태 분포: 신규 2 · 학습 중 1 · 학습 완료 1")).toBeInTheDocument();

    expect(screen.getByRole("cell", { name: "학습률" })).toBeInTheDocument();
    expect(screen.getByText("학습률과 발산의 관계를 혼동함", { selector: "small" })).toBeInTheDocument();
    expect(screen.getAllByText("ch***@skku.edu").length).toBeGreaterThan(0);
    expect(screen.getByText(/일자별 포착: 2026-09-14 4건/)).toBeInTheDocument();

    const buttons = screen.getAllByRole("button", { name: /자세히/ });
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[1]).toBeDisabled();
  });

  it("explains an empty overview without fetching a course detail", async () => {
    apiMocks.getWeakConceptStatistics.mockResolvedValue({
      totals: { ...overview.totals, recordCount: 0, courseCount: 0 },
      courses: [overview.courses[1]]
    });

    render(<WeakConceptStatisticsPanel audience="admin" />);

    expect(await screen.findByText("아직 포착된 취약 개념이 없습니다.")).toBeInTheDocument();
    expect(apiMocks.getCourseWeakConceptStatistics).not.toHaveBeenCalled();
  });

  it("loads another course when its detail button is pressed", async () => {
    const twoCourses: WeakConceptStatistics = {
      ...overview,
      courses: [overview.courses[0], { ...overview.courses[1], recordCount: 1, conceptCount: 1 }]
    };
    apiMocks.getWeakConceptStatistics.mockResolvedValue(twoCourses);
    apiMocks.getCourseWeakConceptStatistics.mockImplementation((courseId: string) =>
      Promise.resolve(
        courseId === "course-1"
          ? detail
          : { ...detail, ...twoCourses.courses[1], concepts: [], topics: [], students: [], recentCaptures: [], savedByDate: [] }
      )
    );

    render(<WeakConceptStatisticsPanel audience="admin" />);
    await screen.findByRole("heading", { name: "인공지능개론 상세" });

    fireEvent.click(screen.getByRole("button", { name: "소프트웨어공학 자세히" }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "소프트웨어공학 상세" })).toBeInTheDocument()
    );
    expect(apiMocks.getCourseWeakConceptStatistics).toHaveBeenLastCalledWith("course-2");
  });

  it("surfaces an API error", async () => {
    const { ApiError } = await import("../../lib/api");
    apiMocks.getWeakConceptStatistics.mockRejectedValue(new ApiError(503, "통계 서비스를 사용할 수 없습니다."));

    render(<WeakConceptStatisticsPanel audience="professor" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("통계 서비스를 사용할 수 없습니다.");
  });
});
