"use client";

import { useState } from "react";
import { ApiError, downloadCourseMaterial } from "../../lib/api";
import type { CourseMaterial } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

const weeks = Array.from({ length: 16 }, (_, index) => index + 1);

export function WeeklyMaterialList({
  activeWeek,
  courseId,
  deletingMaterialId,
  isBusy = false,
  materials,
  onDelete
}: {
  activeWeek?: number;
  courseId: string;
  deletingMaterialId?: string | null;
  isBusy?: boolean;
  materials: CourseMaterial[];
  onDelete?: (material: CourseMaterial) => void;
}) {
  const initiallyOpenWeek = activeWeek ?? materials[0]?.week ?? 1;
  const [openWeeks, setOpenWeeks] = useState<Set<number>>(
    () => new Set([initiallyOpenWeek])
  );
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const openWeek = (week: number) => {
    setOpenWeeks((current) => new Set(current).add(week));
    document.getElementById(`week-${week}`)?.scrollIntoView?.({ behavior: "smooth" });
  };

  const toggleWeek = (week: number) => {
    setOpenWeeks((current) => {
      const next = new Set(current);
      if (next.has(week)) next.delete(week);
      else next.add(week);
      return next;
    });
  };

  const handleDownload = async (material: CourseMaterial) => {
    setDownloadError(null);
    setDownloadingId(material.id);
    try {
      const blob = await downloadCourseMaterial(courseId, material.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = material.originalFileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setDownloadError(
        error instanceof ApiError ? error.message : "강의자료 다운로드에 실패했습니다."
      );
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="weekly-content">
      <nav aria-label="주차 바로가기" className="weekly-content-tabs">
        {weeks.map((week) => (
          <button
            aria-label={`${week}주차로 이동`}
            key={week}
            onClick={() => openWeek(week)}
            type="button"
          >
            {String(week).padStart(2, "0")}
          </button>
        ))}
      </nav>

      {downloadError ? <p className="admin-alert" role="alert">{downloadError}</p> : null}

      <div className="weekly-content-list">
        {weeks.map((week) => {
          const weekMaterials = materials.filter((material) => material.week === week);
          const isOpen = openWeeks.has(week);
          return (
            <section className="weekly-content-section" id={`week-${week}`} key={week}>
              <button
                aria-controls={`week-${week}-panel`}
                aria-expanded={isOpen}
                className="weekly-content-heading"
                onClick={() => toggleWeek(week)}
                type="button"
              >
                <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                <strong>{week}주차</strong>
                <span>{weekMaterials.length}개 자료</span>
              </button>
              {isOpen ? (
                <div
                  aria-label={`${week}주차 강의자료`}
                  className="weekly-content-panel"
                  id={`week-${week}-panel`}
                  role="region"
                >
                  {weekMaterials.length === 0 ? (
                    <p>등록된 강의자료가 없습니다.</p>
                  ) : (
                    <ul>
                      {weekMaterials.map((material) => (
                        <li key={material.id}>
                          <UiIcon name="material" />
                          <button
                            className="weekly-material-download"
                            disabled={downloadingId === material.id}
                            onClick={() => void handleDownload(material)}
                            type="button"
                          >
                            <strong>{material.originalFileName}</strong>
                            <span>
                              {material.fileType.toUpperCase()} · {(material.fileSize / 1024 / 1024).toFixed(2)}MB
                            </span>
                          </button>
                          <span className="material-status" data-status={material.processingStatus}>
                            {material.processingStatus === "failed" ? "업로드 실패" : "게시 완료"}
                          </span>
                          {onDelete ? (
                            <button
                              aria-label={`${material.originalFileName} 삭제`}
                              disabled={isBusy}
                              onClick={() => onDelete(material)}
                              type="button"
                            >
                              {deletingMaterialId === material.id ? "삭제 중..." : "삭제"}
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
