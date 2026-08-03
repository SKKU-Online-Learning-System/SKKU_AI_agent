"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, listCourses, searchRagDebug } from "../../lib/api";
import type { CourseSummary, RagSearchResponse } from "../../lib/api";

export function RagDebugClient({ courseId }: { courseId?: string } = {}) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState(courseId ?? "");
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [response, setResponse] = useState<RagSearchResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoadingCourses, setIsLoadingCourses] = useState(!courseId);
  const [isSearching, setIsSearching] = useState(false);
  const searchingRef = useRef(false);

  useEffect(() => {
    if (courseId) return;
    let isCancelled = false;

    void listCourses()
      .then((items) => {
        if (isCancelled) return;
        setCourses(items);
        setSelectedCourseId(items[0]?.id ?? "");
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "담당 과목을 불러오지 못했습니다."
          );
        }
      })
      .finally(() => {
        if (!isCancelled) setIsLoadingCourses(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedCourseId || !question.trim() || searchingRef.current) return;

    searchingRef.current = true;
    setIsSearching(true);
    setErrorMessage(null);
    try {
      setResponse(await searchRagDebug(selectedCourseId, question.trim(), topK));
    } catch (error) {
      setResponse(null);
      setErrorMessage(
        error instanceof ApiError ? error.message : "검색을 실행하지 못했습니다."
      );
    } finally {
      searchingRef.current = false;
      setIsSearching(false);
    }
  }

  return (
    <section className="rag-debug-page">
      <header>
        <h1>RAG 검색 디버그</h1>
        <p>답변 생성 없이 과목별 검색 청크와 유사도 점수를 확인합니다.</p>
      </header>

      <form className="rag-debug-form" onSubmit={handleSubmit}>
        {!courseId ? (
          <label>
            과목
            <select
              disabled={isLoadingCourses || isSearching}
              onChange={(event) => {
                setSelectedCourseId(event.target.value);
                setResponse(null);
              }}
              value={selectedCourseId}
            >
              {courses.length === 0 ? <option value="">담당 과목 없음</option> : null}
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.title} ({course.term})
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="rag-debug-question">
          질문
          <textarea
            disabled={isSearching}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="예: 경사하강법이 뭐야?"
            required
            rows={3}
            value={question}
          />
        </label>
        <label>
          top_k
          <select
            disabled={isSearching}
            onChange={(event) => setTopK(Number(event.target.value))}
            value={topK}
          >
            {[1, 3, 5, 10, 20].map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>
        <button disabled={isSearching || !selectedCourseId} type="submit">
          {isSearching ? "검색 중..." : "검색 실행"}
        </button>
      </form>

      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {response?.debug ? (
        <dl className="rag-debug-diagnostics">
          <div><dt>임베딩 모델</dt><dd>{response.debug.embeddingModel ?? "미기록"}</dd></div>
          <div><dt>검색 모드</dt><dd>{response.debug.searchMode}</dd></div>
          <div><dt>점수 임계값</dt><dd>{response.debug.scoreThreshold ?? "없음"}</dd></div>
          <div><dt>후보 청크</dt><dd>{response.debug.totalCandidateChunks}</dd></div>
        </dl>
      ) : null}

      {response ? (
        <section className="rag-debug-results" aria-live="polite">
          <h2>검색 결과 {response.results.length}개</h2>
          {response.results.length === 0 ? <p>검색 가능한 처리 완료 청크가 없습니다.</p> : null}
          {response.results.map((result) => (
            <article key={result.chunkId}>
              <header>
                <strong>{result.documentName}</strong>
                <span>score {result.score.toFixed(4)}</span>
              </header>
              <dl>
                <div><dt>page</dt><dd>{result.pageNumber ?? "-"}</dd></div>
                <div><dt>chunk_index</dt><dd>{result.chunkIndex}</dd></div>
                <div><dt>material_id</dt><dd>{result.materialId}</dd></div>
                <div><dt>chunk_id</dt><dd>{result.chunkId}</dd></div>
              </dl>
              <details>
                <summary>청크 텍스트 미리보기</summary>
                <p>{result.chunkText}</p>
              </details>
            </article>
          ))}
        </section>
      ) : null}
    </section>
  );
}
