"use client";

import { useEffect, useState } from "react";
import { ApiError, listCourseMaterials } from "../../lib/api";
import type { CourseMaterial } from "../../lib/api";

const processingLabels: Record<CourseMaterial["processingStatus"], string> = {
  completed: "처리 완료",
  failed: "처리 실패",
  pending: "처리 대기",
  processing: "처리 중"
};

export function CourseMaterialsClient({ courseId }: { courseId: string }) {
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isCancelled = false;
    async function loadMaterials() {
      try {
        const materialList = await listCourseMaterials(courseId);
        if (!isCancelled) setMaterials(materialList);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "강의자료를 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) setIsLoading(false);
      }
    }
    void loadMaterials();
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  return (
    <section className="material-manager">
      <header>
        <h1>강의자료</h1>
        <p>이 과목에 등록된 강의자료와 AI 처리 상태를 확인합니다.</p>
      </header>
      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {!errorMessage ? (
        <div className="course-table-wrap">
          <table className="course-table">
            <thead>
              <tr>
                <th scope="col">파일명</th>
                <th scope="col">형식</th>
                <th scope="col">크기</th>
                <th scope="col">처리 상태</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={4}>강의자료를 불러오고 있습니다.</td></tr>
              ) : materials.length === 0 ? (
                <tr><td className="empty-state" colSpan={4}>등록된 강의자료가 없습니다.</td></tr>
              ) : (
                materials.map((material) => (
                  <tr key={material.id}>
                    <td><strong>{material.originalFileName}</strong></td>
                    <td>{material.fileType.toUpperCase()}</td>
                    <td>{(material.fileSize / 1024 / 1024).toFixed(2)}MB</td>
                    <td>
                      <span className="material-status" data-status={material.processingStatus}>
                        {processingLabels[material.processingStatus]}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
