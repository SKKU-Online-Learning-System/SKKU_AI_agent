"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  getAdminChatLog,
  getCourseChatLog,
  listAdminChatLogs,
  listAdminUsers,
  listCourseChatLogs,
  listCourses
} from "../../lib/api";
import type {
  AnswerSourceType,
  AdminUser,
  ChatLogDetail,
  ChatLogListItem,
  CourseSummary,
  SafetyCategory
} from "../../lib/api";

const answerSourceLabels: Record<AnswerSourceType, string> = {
  rag: "강의자료 기반",
  general_llm: "일반 설명",
  no_material: "자료 부족",
  safety_response: "안전 응답"
};

const safetyCategoryLabels: Record<SafetyCategory, string> = {
  normal: "일반",
  assignment_direct_answer: "과제 정답 요청",
  exam_direct_answer: "시험 정답 요청",
  privacy_request: "개인정보 요청",
  prompt_injection: "프롬프트 탈취",
  unsafe_content: "위험 요청"
};

type ChatLogClientProps = {
  audience: "professor" | "admin";
};

type AppliedFilters = {
  from: string;
  keyword: string;
  isGrounded: boolean | null;
  to: string;
  userId: string;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleString("ko-KR");
}

export function ChatLogClient({ audience }: ChatLogClientProps) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [groundedFilter, setGroundedFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [userId, setUserId] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({
    from: "",
    keyword: "",
    isGrounded: null,
    to: "",
    userId: ""
  });
  const [logs, setLogs] = useState<ChatLogListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [detail, setDetail] = useState<ChatLogDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const isProfessor = audience === "professor";

  useEffect(() => {
    let isCancelled = false;

    async function loadCourses() {
      try {
        const [courseList, userList] = await Promise.all([
          listCourses(),
          isProfessor ? Promise.resolve([]) : listAdminUsers()
        ]);
        if (isCancelled) return;
        setCourses(courseList);
        setUsers(userList);
        if (isProfessor) {
          setSelectedCourseId(courseList[0]?.id ?? "");
          if (courseList.length === 0) setIsLoading(false);
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(apiErrorMessage(error, "과목 목록을 불러오지 못했습니다."));
          setIsLoading(false);
        }
      }
    }

    void loadCourses();

    return () => {
      isCancelled = true;
    };
  }, [isProfessor]);

  useEffect(() => {
    if (isProfessor && !selectedCourseId) return;

    let isCancelled = false;

    async function loadLogs() {
      setIsLoading(true);
      setErrorMessage(null);
      const filters = {
        from: appliedFilters.from || undefined,
        keyword: appliedFilters.keyword || undefined,
        isGrounded: appliedFilters.isGrounded,
        to: appliedFilters.to || undefined,
        userId: appliedFilters.userId || undefined
      };

      try {
        const response = isProfessor
          ? await listCourseChatLogs(selectedCourseId, filters)
          : await listAdminChatLogs({ ...filters, courseId: selectedCourseId || undefined });
        if (isCancelled) return;
        setLogs(response.logs);
        setTotal(response.total);
      } catch (error) {
        if (isCancelled) return;
        setErrorMessage(apiErrorMessage(error, "질문 로그를 불러오지 못했습니다."));
        setLogs([]);
        setTotal(0);
      } finally {
        if (!isCancelled) setIsLoading(false);
      }
    }

    void loadLogs();

    return () => {
      isCancelled = true;
    };
  }, [appliedFilters, isProfessor, selectedCourseId]);

  const handleFilterSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedFilters({
      from: fromDate ? `${fromDate}T00:00:00` : "",
      keyword: keyword.trim(),
      isGrounded: groundedFilter === "" ? null : groundedFilter === "true",
      to: toDate ? `${toDate}T23:59:59.999` : "",
      userId
    });
  };

  const handleOpenDetail = async (logId: string) => {
    setErrorMessage(null);
    try {
      setDetail(isProfessor ? await getCourseChatLog(logId) : await getAdminChatLog(logId));
    } catch (error) {
      setErrorMessage(apiErrorMessage(error, "로그 상세를 불러오지 못했습니다."));
    }
  };

  return (
    <section className="log-page">
      <header>
        <h1>질문 로그</h1>
        <p>
          {isProfessor
            ? "담당 과목에서 발생한 질문과 답변을 확인합니다."
            : "전체 과목의 질문과 답변을 확인합니다."}
        </p>
      </header>

      <form className="log-filters" onSubmit={handleFilterSubmit}>
        <label>
          과목
          <select
            onChange={(event) => setSelectedCourseId(event.target.value)}
            value={selectedCourseId}
          >
            {!isProfessor ? <option value="">전체 과목</option> : null}
            {courses.length === 0 && isProfessor ? (
              <option value="">담당 과목이 없습니다.</option>
            ) : null}
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          검색어
          <input
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="질문 또는 답변 내용"
            value={keyword}
          />
        </label>
        <label>
          자료 기반 여부
          <select
            onChange={(event) => setGroundedFilter(event.target.value)}
            value={groundedFilter}
          >
            <option value="">전체</option>
            <option value="true">강의자료 기반</option>
            <option value="false">자료 근거 없음</option>
          </select>
        </label>
        <label>
          시작일
          <input onChange={(event) => setFromDate(event.target.value)} type="date" value={fromDate} />
        </label>
        <label>
          종료일
          <input onChange={(event) => setToDate(event.target.value)} type="date" value={toDate} />
        </label>
        {!isProfessor ? (
          <label>
            사용자
            <select onChange={(event) => setUserId(event.target.value)} value={userId}>
              <option value="">전체 사용자</option>
              {users.map((user) => <option key={user.id} value={user.id}>{user.name} ({user.email})</option>)}
            </select>
          </label>
        ) : null}
        <button type="submit">검색</button>
      </form>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      <p className="log-total">전체 {total}건</p>

      <div className="course-table-wrap">
        <table className="course-table">
          <thead>
            <tr>
              <th scope="col">질문</th>
              <th scope="col">답변 미리보기</th>
              <th scope="col">과목</th>
              <th scope="col">사용자</th>
              <th scope="col">자료 기반</th>
              <th scope="col">안전 분류</th>
              <th scope="col">시각</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7}>질문 로그를 불러오고 있습니다.</td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td className="empty-state" colSpan={7}>
                  조회된 질문 로그가 없습니다.
                </td>
              </tr>
            ) : (
              logs.map((log) => (
                <tr key={log.id}>
                  <td>
                    <button
                      className="log-link"
                      onClick={() => void handleOpenDetail(log.id)}
                      type="button"
                    >
                      {log.question}
                    </button>
                  </td>
                  <td>{log.answerPreview}</td>
                  <td>{log.courseName}</td>
                  <td>{log.userLabel}</td>
                  <td>{answerSourceLabels[log.answerSourceType]}</td>
                  <td>{safetyCategoryLabels[log.safetyCategory]}</td>
                  <td>{formatDateTime(log.createdAt)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {detail ? (
        <article className="log-detail">
          <header>
            <h2>로그 상세</h2>
            <button onClick={() => setDetail(null)} type="button">
              닫기
            </button>
          </header>
          <dl>
            <dt>질문</dt>
            <dd>{detail.question}</dd>
            <dt>답변</dt>
            <dd>{detail.answer}</dd>
            <dt>출처</dt>
            <dd>
              {detail.referencedDocuments.length === 0 ? (
                "출처 없음"
              ) : (
                <ul>
                  {detail.referencedDocuments.map((source) => (
                    <li key={`${source.materialId}-${source.chunkIndex}`}>
                      {source.documentName} (
                      {source.pageNumber === null || source.pageNumber === undefined
                        ? "페이지 정보 없음"
                        : `p.${source.pageNumber}`}
                      )
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            <dt>안전 검사</dt>
            <dd>{JSON.stringify(detail.safetyResult)}</dd>
            <dt>검색 요약</dt>
            <dd>{JSON.stringify(detail.retrievalResult)}</dd>
            <dt>모델</dt>
            <dd>{detail.modelName ?? "-"}</dd>
            <dt>응답 시간</dt>
            <dd>{detail.responseTimeMs ?? "-"}ms</dd>
          </dl>
        </article>
      ) : null}
    </section>
  );
}
