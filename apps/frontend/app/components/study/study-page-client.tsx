"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, downloadCourseMaterial, listCourses, listMaterialPages } from "../../lib/api";
import type { CourseMaterial, CourseSummary } from "../../lib/api";
import { useAuth } from "../auth/auth-provider";
import { CourseAgentClient } from "../course-agent/course-agent-client";
import type { PageFocus } from "../course-agent/course-agent-client";
import { WeakConceptsPanel } from "../course-agent/weak-concepts-panel";
import { useCourseMaterials } from "../courses/use-course-materials";
import { CourseAgentSymbol } from "../ui/course-agent-symbol";
import { UiIcon } from "../ui/ui-icon";
import { CurriculumPanel, groupByWeek, isViewable, pageCount } from "./curriculum-panel";
import { PageNotePane } from "./page-note";
import { SlideViewer } from "./slide-viewer";

type Panel = "curriculum" | "agent" | "weak" | null;

const EMPTY_PAGES: ReadonlySet<number> = new Set();

/** Keep the open 교안 and page in the URL so a reload or a shared link lands on the same slide. */
function writeLocation(materialId: string | null, page: number | null, panel: Panel, sessionId: string | null) {
  const params = new URLSearchParams();
  if (materialId) params.set("m", materialId);
  if (materialId && page) params.set("p", String(page));
  if (panel) params.set("panel", panel);
  if (sessionId) params.set("sessionId", sessionId);
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

export function StudyPageClient({ courseId }: { courseId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { logout, user } = useAuth();
  const { errorMessage, isLoading, materials } = useCourseMaterials(courseId);
  const [course, setCourse] = useState<CourseSummary | null>(null);
  const [courseError, setCourseError] = useState<string | null>(null);
  const sessionId = searchParams.get("sessionId");
  const [chosenMaterialId, setMaterialId] = useState<string | null>(searchParams.get("m"));
  const [page, setPage] = useState<number>(Number(searchParams.get("p")) || 1);
  const [pageList, setPageList] = useState<{
    materialId: string;
    pages: number[];
    noted: Set<number>;
    error: string | null;
  } | null>(null);
  const [panel, setPanel] = useState<Panel>(() => {
    const requested = searchParams.get("panel");
    if (requested === "agent" || sessionId) return "agent";
    if (requested === "weak") return "weak";
    return "curriculum";
  });
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCourses().then(
      (list) => {
        const found = list.find((item) => item.id === courseId);
        if (cancelled) return;
        if (found) setCourse(found);
        else setCourseError("과목을 찾을 수 없습니다.");
      },
      (error) => {
        if (!cancelled) {
          setCourseError(error instanceof ApiError ? error.message : "과목 정보를 불러오지 못했습니다.");
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const viewable = useMemo(() => materials.filter(isViewable), [materials]);
  // Nothing chosen yet: the first 교안 of the earliest week.
  const materialId = chosenMaterialId ?? groupByWeek(viewable)[0]?.items[0]?.id ?? null;
  const material = materials.find((item) => item.id === materialId) ?? null;
  const pages = pageList?.materialId === materialId ? pageList.pages : [];
  const notedPages = pageList?.materialId === materialId ? pageList.noted : EMPTY_PAGES;
  const pagesError = pageList?.materialId === materialId ? pageList.error : null;

  useEffect(() => {
    if (!materialId) return;
    let cancelled = false;
    listMaterialPages(courseId, materialId).then(
      (result) => {
        if (cancelled) return;
        setPageList({
          materialId,
          pages: result.pages,
          noted: new Set(result.noted ?? []),
          error: null
        });
        setPage((current) => (result.pages.includes(current) ? current : (result.pages[0] ?? 1)));
      },
      (error) => {
        if (!cancelled) {
          setPageList({
            materialId,
            pages: [],
            noted: new Set(),
            error: error instanceof ApiError ? error.message : "교안 페이지를 불러오지 못했습니다."
          });
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, [courseId, materialId]);

  useEffect(() => {
    writeLocation(materialId, page, panel, sessionId);
  }, [materialId, page, panel, sessionId]);

  const markNoted = useCallback((noted: number) => {
    setPageList((current) =>
      current && !current.noted.has(noted)
        ? { ...current, noted: new Set(current.noted).add(noted) }
        : current
    );
  }, []);

  const selectMaterial = useCallback((item: CourseMaterial) => {
    setMaterialId(item.id);
    setPage(1);
  }, []);

  const download = async (item: CourseMaterial) => {
    setDownloadError(null);
    try {
      const blob = await downloadCourseMaterial(courseId, item.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = item.originalFileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setDownloadError(error instanceof ApiError ? error.message : "교안 다운로드에 실패했습니다.");
    }
  };

  const togglePanel = (next: Exclude<Panel, null>) =>
    setPanel((current) => (current === next ? null : next));

  const focus: PageFocus | null =
    material && pages.length
      ? { materialId: material.id, page, label: `${material.originalFileName} p.${page}` }
      : null;

  const weekCount = groupByWeek(materials).length;
  const totalPages = materials.reduce((sum, item) => sum + pageCount(item), 0);
  const alert = courseError ?? errorMessage ?? downloadError;

  return (
    <div className="study-page" data-panel={panel ?? "none"}>
      <header className="study-topbar">
        <Link className="study-back" href="/student/courses">
          <UiIcon name="chevron" />
          <span>내 학습</span>
        </Link>
        <div className="study-title">
          <strong>{course?.title ?? "과목을 불러오는 중"}</strong>
          {material ? (
            <span>
              {material.week}주차 · {material.originalFileName}
            </span>
          ) : null}
        </div>
        <div className="study-stats" aria-label="과목 요약">
          <span>{weekCount}개 주차</span>
          <span>{materials.length}개 교안</span>
          <span>{totalPages}쪽</span>
        </div>
        <div className="study-user">
          {user ? <span>{user.name}</span> : null}
          <button
            aria-label="로그아웃"
            onClick={() => {
              logout();
              router.replace("/login");
            }}
            title="로그아웃"
            type="button"
          >
            <UiIcon name="logout" />
          </button>
        </div>
      </header>

      <div className="study-body">
        <main className="study-main">
          {alert ? <p className="admin-alert" role="alert">{alert}</p> : null}
          {!isLoading && !materialId && !alert ? (
            <div className="study-empty">
              <CourseAgentSymbol size={56} state="presence" />
              <h2>아직 열 수 있는 교안이 없어요</h2>
              <p>교수자가 PDF 교안을 올리고 처리가 끝나면 이곳에서 페이지별 AI 해설과 함께 볼 수 있어요.</p>
            </div>
          ) : null}
          {material && pagesError ? <p className="admin-alert" role="alert">{pagesError}</p> : null}
          {material && !pagesError && pages.length === 0 ? (
            <p className="study-stage-loading">교안 페이지를 준비하는 중…</p>
          ) : null}
          {material && pages.length ? (
            <div className="study-reader">
              <SlideViewer
                courseId={courseId}
                materialId={material.id}
                notedPages={notedPages}
                onPageChange={setPage}
                page={page}
                pages={pages}
                title={material.originalFileName}
              />
              <PageNotePane
                courseId={courseId}
                materialId={material.id}
                onAsk={() => setPanel("agent")}
                onNoted={markNoted}
                page={page}
                week={material.week}
              />
            </div>
          ) : null}
        </main>

        {panel === "curriculum" ? (
          <CurriculumPanel
            activeMaterialId={materialId}
            materials={materials}
            onClose={() => setPanel(null)}
            onDownload={(item) => void download(item)}
            onSelect={selectMaterial}
          />
        ) : null}
        {panel === "agent" ? (
          <section aria-label="COURSE AGENT" className="study-panel study-panel--agent">
            <header className="study-panel-head">
              <h2>
                <CourseAgentSymbol size={22} state="presence" /> COURSE AGENT
              </h2>
              <button aria-label="패널 닫기" onClick={() => setPanel(null)} type="button">
                <UiIcon name="close" />
              </button>
            </header>
            <div className="study-agent-body">
              <CourseAgentClient
                courseId={courseId}
                embedded
                focus={focus}
                initialSessionId={sessionId}
              />
            </div>
          </section>
        ) : null}

        {panel === "weak" ? (
          <section aria-label="취약 개념" className="study-panel">
            <header className="study-panel-head">
              <h2>내 취약 개념</h2>
              <button aria-label="패널 닫기" onClick={() => setPanel(null)} type="button">
                <UiIcon name="close" />
              </button>
            </header>
            <div className="study-panel-scroll">
              <WeakConceptsPanel courseId={courseId} variant="panel" />
            </div>
          </section>
        ) : null}

        <nav aria-label="학습 도구" className="study-rail">
          <button
            aria-pressed={panel === "curriculum"}
            onClick={() => togglePanel("curriculum")}
            type="button"
          >
            <UiIcon name="list" />
            <span>커리큘럼</span>
          </button>
          <button
            aria-pressed={panel === "agent"}
            className="study-rail-agent"
            onClick={() => togglePanel("agent")}
            type="button"
          >
            <CourseAgentSymbol size={26} state="presence" />
            <span>에이전트</span>
          </button>
          <button aria-pressed={panel === "weak"} onClick={() => togglePanel("weak")} type="button">
            <UiIcon name="chart" />
            <span>취약 개념</span>
          </button>
          <Link href="/student/chat-history">
            <UiIcon name="note" />
            <span>대화 이력</span>
          </Link>
        </nav>
      </div>
    </div>
  );
}
