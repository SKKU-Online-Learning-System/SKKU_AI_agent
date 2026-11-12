"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchMaterialPageImage } from "../../lib/api";

const ZOOM_STEP = 0.25;
const ZOOM_MAX = 3;

/**
 * One authorized blob URL per (material, page), shared by the stage and the
 * thumbnail strip, revoked when the viewer unmounts.
 */
function usePageImageCache(courseId: string, materialId: string) {
  const cache = useRef(new Map<string, Promise<string>>());

  useEffect(() => {
    const current = cache.current;
    return () => {
      current.forEach((promise) => void promise.then((url) => URL.revokeObjectURL(url), () => {}));
      current.clear();
    };
  }, [courseId, materialId]);

  return useCallback(
    (page: number): Promise<string> => {
      const key = `${materialId}:${page}`;
      let promise = cache.current.get(key);
      if (!promise) {
        promise = fetchMaterialPageImage(courseId, materialId, page).then((blob) =>
          URL.createObjectURL(blob)
        );
        promise.catch(() => cache.current.delete(key));
        cache.current.set(key, promise);
      }
      return promise;
    },
    [courseId, materialId]
  );
}

function Thumbnail({
  active,
  load,
  noted,
  onSelect,
  page
}: {
  active: boolean;
  load: (page: number) => Promise<string>;
  /** The AI 해설 for this page is already written, so it opens at once. */
  noted: boolean;
  onSelect: (page: number) => void;
  page: number;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      void load(page).then(setUrl, () => {});
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void load(page).then(setUrl, () => {});
        observer.disconnect();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [load, page]);

  useEffect(() => {
    if (active) ref.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [active]);

  return (
    <button
      aria-current={active ? "true" : undefined}
      aria-label={`${page}쪽으로 이동${noted ? " · 해설 있음" : ""}`}
      className="study-thumb"
      data-noted={noted}
      onClick={() => onSelect(page)}
      ref={ref}
      type="button"
    >
      {/* Authorized blob URL, not a static asset. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {url ? <img alt="" src={url} /> : <span aria-hidden="true" />}
      <small>
        {page}
        {noted ? <i aria-hidden="true" className="study-thumb-noted" title="해설 있음" /> : null}
      </small>
    </button>
  );
}

export function SlideViewer({
  courseId,
  materialId,
  notedPages,
  onPageChange,
  page,
  pages,
  title
}: {
  courseId: string;
  materialId: string;
  /** Pages whose 해설 is already written; marked on the thumbnails. */
  notedPages: ReadonlySet<number>;
  onPageChange: (page: number) => void;
  page: number;
  pages: number[];
  title: string;
}) {
  const load = usePageImageCache(courseId, materialId);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<{ page: number; message: string } | null>(null);
  // 1 = fit to the stage; above it the image grows and the stage scrolls, dragged by mouse.
  const [zoom, setZoom] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const zoomIn = () =>
    setZoom((value) => Math.min(ZOOM_MAX, Math.round((value + ZOOM_STEP) * 100) / 100));
  const zoomOut = () =>
    setZoom((value) => Math.max(1, Math.round((value - ZOOM_STEP) * 100) / 100));

  const startDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    if (!stage || zoom === 1 || event.button !== 0) return;
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      left: stage.scrollLeft,
      top: stage.scrollTop
    };
    stage.dataset.dragging = "true";
    event.preventDefault();
  };
  const moveDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    const stage = stageRef.current;
    const drag = dragRef.current;
    if (!stage || !drag) return;
    stage.scrollLeft = drag.left - (event.clientX - drag.x);
    stage.scrollTop = drag.top - (event.clientY - drag.y);
  };
  const endDrag = () => {
    dragRef.current = null;
    if (stageRef.current) delete stageRef.current.dataset.dragging;
  };
  const index = pages.indexOf(page);
  const previous = index > 0 ? pages[index - 1] : null;
  const next = index >= 0 && index < pages.length - 1 ? pages[index + 1] : null;

  useEffect(() => {
    let cancelled = false;
    void load(page).then(
      (value) => {
        if (!cancelled) setUrl(value);
      },
      (reason) => {
        if (!cancelled) {
          setError({
            page,
            message: reason instanceof ApiError ? reason.message : "페이지 이미지를 불러오지 못했습니다."
          });
        }
      }
    );
    // The neighbours are what the student opens next.
    if (next) void load(next).catch(() => {});
    if (previous) void load(previous).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [load, next, page, previous]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (target?.isContentEditable) return;
      if (event.key === "ArrowRight" && next) onPageChange(next);
      if (event.key === "ArrowLeft" && previous) onPageChange(previous);
      if (event.key === "+" || event.key === "=") zoomIn();
      if (event.key === "-") zoomOut();
      if (event.key === "0") setZoom(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, onPageChange, previous]);

  return (
    <section aria-label="교안 보기" className="study-viewer">
      <div
        className="study-stage"
        data-zoomed={zoom > 1}
        onMouseDown={startDrag}
        onMouseLeave={endDrag}
        onMouseMove={moveDrag}
        onMouseUp={endDrag}
        ref={stageRef}
      >
        {error?.page === page ? (
          <p className="study-stage-error" role="alert">{error.message}</p>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt={`${title} ${page}쪽`}
            draggable={false}
            onDoubleClick={() => setZoom((value) => (value > 1 ? 1 : 2))}
            src={url}
            style={zoom > 1 ? { width: `${zoom * 100}%` } : undefined}
          />
        ) : (
          <p className="study-stage-loading">페이지를 불러오는 중…</p>
        )}
      </div>
      <div className="study-pager">
        <button disabled={previous === null} onClick={() => previous && onPageChange(previous)} type="button">
          ← 이전
        </button>
        <label className="study-page-select">
          <span className="sr-only">페이지 선택</span>
          <select onChange={(event) => onPageChange(Number(event.target.value))} value={page}>
            {pages.map((number) => (
              <option key={number} value={number}>
                p.{number}
              </option>
            ))}
          </select>
        </label>
        <button disabled={next === null} onClick={() => next && onPageChange(next)} type="button">
          다음 →
        </button>
        <div aria-label="확대 조절" className="study-zoom" role="group">
          <button aria-label="축소" disabled={zoom <= 1} onClick={zoomOut} type="button">
            −
          </button>
          <button
            aria-label="원래 크기로"
            className="study-zoom-level"
            disabled={zoom === 1}
            onClick={() => setZoom(1)}
            title="원래 크기로"
            type="button"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button aria-label="확대" disabled={zoom >= ZOOM_MAX} onClick={zoomIn} type="button">
            +
          </button>
        </div>
        <span className="study-page-count">
          {index + 1} / {pages.length}
        </span>
      </div>
      <p className="study-pager-hint">
        ← → 페이지 이동 · + − 확대/축소 · 확대한 슬라이드는 마우스로 끌어서 이동 · 더블클릭으로
        확대/원래 크기 · <i aria-hidden="true" className="study-thumb-noted" /> 해설이 작성된 페이지
      </p>
      <div aria-label="페이지 미리보기" className="study-thumbs" role="list">
        {pages.map((number) => (
          <Thumbnail
            active={number === page}
            key={number}
            load={load}
            noted={notedPages.has(number)}
            onSelect={onPageChange}
            page={number}
          />
        ))}
      </div>
    </section>
  );
}
