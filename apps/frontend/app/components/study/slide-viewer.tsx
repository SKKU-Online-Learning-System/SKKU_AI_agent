"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchMaterialPageImage } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

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
  onSelect,
  page
}: {
  active: boolean;
  load: (page: number) => Promise<string>;
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
      aria-label={`${page}쪽으로 이동`}
      className="study-thumb"
      onClick={() => onSelect(page)}
      ref={ref}
      type="button"
    >
      {/* Authorized blob URL, not a static asset. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {url ? <img alt="" src={url} /> : <span aria-hidden="true" />}
      <small>{page}</small>
    </button>
  );
}

export function SlideViewer({
  courseId,
  materialId,
  onPageChange,
  page,
  pages,
  title
}: {
  courseId: string;
  materialId: string;
  onPageChange: (page: number) => void;
  page: number;
  pages: number[];
  title: string;
}) {
  const load = usePageImageCache(courseId, materialId);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<{ page: number; message: string } | null>(null);
  const [zoomed, setZoomed] = useState(false);
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
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, onPageChange, previous]);

  return (
    <section aria-label="교안 보기" className="study-viewer">
      <div className="study-stage" data-zoomed={zoomed}>
        {error?.page === page ? (
          <p className="study-stage-error" role="alert">{error.message}</p>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img alt={`${title} ${page}쪽`} onClick={() => setZoomed((value) => !value)} src={url} />
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
        <button
          aria-pressed={zoomed}
          className="study-zoom"
          onClick={() => setZoomed((value) => !value)}
          type="button"
        >
          <UiIcon name="image" /> {zoomed ? "맞춤" : "크게"}
        </button>
        <span className="study-page-count">
          {index + 1} / {pages.length}
        </span>
      </div>
      <p className="study-pager-hint">키보드 ← → 로 페이지 이동 · 슬라이드를 누르면 확대</p>
      <div aria-label="페이지 미리보기" className="study-thumbs" role="list">
        {pages.map((number) => (
          <Thumbnail
            active={number === page}
            key={number}
            load={load}
            onSelect={onPageChange}
            page={number}
          />
        ))}
      </div>
    </section>
  );
}
