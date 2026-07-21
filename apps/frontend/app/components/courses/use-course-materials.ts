"use client";

import { useEffect, useState } from "react";
import { ApiError, listCourseMaterials } from "../../lib/api";
import type { CourseMaterial } from "../../lib/api";

const refreshIntervalMs = 5000;

export function useCourseMaterials(courseId: string) {
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isCancelled = false;
    let requestInFlight = false;

    async function refreshMaterials(showLoading = false) {
      if (requestInFlight) return;
      requestInFlight = true;
      if (showLoading) setIsLoading(true);
      try {
        const materialList = await listCourseMaterials(courseId);
        if (!isCancelled) {
          setMaterials(materialList);
          setErrorMessage(null);
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "강의자료를 불러오지 못했습니다."
          );
        }
      } finally {
        requestInFlight = false;
        if (!isCancelled) setIsLoading(false);
      }
    }

    void refreshMaterials(true);
    const intervalId = window.setInterval(() => void refreshMaterials(), refreshIntervalMs);
    const handleFocus = () => void refreshMaterials();
    window.addEventListener("focus", handleFocus);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleFocus);
    };
  }, [courseId]);

  return { errorMessage, isLoading, materials };
}
