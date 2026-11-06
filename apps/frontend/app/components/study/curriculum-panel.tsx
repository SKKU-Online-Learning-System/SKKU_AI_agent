"use client";

import { useState } from "react";
import type { CourseMaterial } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

/** File types the ingestion pipeline renders page by page, so the viewer can show them. */
export const VIEWABLE_TYPES = new Set(["pdf", "pptx", "docx"]);

export function isViewable(material: CourseMaterial): boolean {
  return VIEWABLE_TYPES.has(material.fileType.toLowerCase()) && material.processingStatus === "completed";
}

export function pageCount(material: CourseMaterial): number {
  return VIEWABLE_TYPES.has(material.fileType.toLowerCase()) ? material.chunkCount ?? 0 : 0;
}

const statusLabels: Record<CourseMaterial["processingStatus"], string> = {
  pending: "준비 중",
  processing: "준비 중",
  completed: "",
  failed: "열 수 없음"
};

export function groupByWeek(materials: CourseMaterial[]): Array<{ week: number; items: CourseMaterial[] }> {
  const weeks = new Map<number, CourseMaterial[]>();
  for (const material of materials) {
    weeks.set(material.week, [...(weeks.get(material.week) ?? []), material]);
  }
  return [...weeks.entries()]
    .sort(([a], [b]) => a - b)
    .map(([week, items]) => ({
      week,
      items: [...items].sort((a, b) => a.originalFileName.localeCompare(b.originalFileName, "ko"))
    }));
}

export function CurriculumPanel({
  activeMaterialId,
  materials,
  onClose,
  onDownload,
  onSelect
}: {
  activeMaterialId: string | null;
  materials: CourseMaterial[];
  onClose: () => void;
  onDownload: (material: CourseMaterial) => void;
  onSelect: (material: CourseMaterial) => void;
}) {
  const weeks = groupByWeek(materials);
  const activeWeek = materials.find((item) => item.id === activeMaterialId)?.week;
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  const toggle = (week: number) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(week)) next.delete(week);
      else next.add(week);
      return next;
    });

  return (
    <section aria-label="커리큘럼" className="study-panel">
      <header className="study-panel-head">
        <h2>커리큘럼</h2>
        <button aria-label="패널 닫기" onClick={onClose} type="button">
          <UiIcon name="close" />
        </button>
      </header>
      {weeks.length === 0 ? (
        <p className="study-panel-empty">아직 올라온 교안이 없어요.</p>
      ) : null}
      <div className="study-curriculum">
        {weeks.map(({ week, items }) => {
          const isOpen = !collapsed.has(week);
          const pages = items.reduce((sum, item) => sum + pageCount(item), 0);
          return (
            <section className="study-week" data-active={week === activeWeek} key={week}>
              <button
                aria-expanded={isOpen}
                className="study-week-head"
                onClick={() => toggle(week)}
                type="button"
              >
                <UiIcon className="study-week-chevron" name="chevron" />
                <strong>{week}주차</strong>
                <span>
                  {items.length}개 교안{pages ? ` · ${pages}쪽` : ""}
                </span>
              </button>
              {isOpen ? (
                <ul>
                  {items.map((material) => {
                    const viewable = isViewable(material);
                    const active = material.id === activeMaterialId;
                    const count = pageCount(material);
                    return (
                      <li data-active={active} key={material.id}>
                        <button
                          aria-current={active ? "true" : undefined}
                          className="study-lesson"
                          disabled={!viewable}
                          onClick={() => (viewable ? onSelect(material) : onDownload(material))}
                          title={viewable ? undefined : "열 수 있는 형식이 아니어서 내려받기로 열어요"}
                          type="button"
                        >
                          <span className="study-lesson-mark" data-status={material.processingStatus}>
                            {material.processingStatus === "completed" ? (
                              <UiIcon name="check" />
                            ) : (
                              <UiIcon name="material" />
                            )}
                          </span>
                          <span className="study-lesson-text">
                            <strong>{material.originalFileName}</strong>
                            <small>
                              {material.fileType.toUpperCase()}
                              {count ? ` · ${count}쪽` : ""}
                              {material.processingStatus === "processing" && material.pageProgress
                                ? ` · ${material.pageProgress}쪽 준비 중`
                                : statusLabels[material.processingStatus]
                                  ? ` · ${statusLabels[material.processingStatus]}`
                                  : ""}
                            </small>
                          </span>
                        </button>
                        <button
                          aria-label={`${material.originalFileName} 내려받기`}
                          className="study-lesson-download"
                          onClick={() => onDownload(material)}
                          type="button"
                        >
                          <UiIcon name="download" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </section>
          );
        })}
      </div>
    </section>
  );
}
