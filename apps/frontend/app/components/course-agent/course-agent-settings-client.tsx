"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CourseMaterial } from "../../lib/api";
import {
  ApiError,
  deleteCourseMaterial,
  listCourseMaterials,
  processCourseMaterial,
  uploadCourseMaterial
} from "../../lib/api";
import type { VoiceConfig } from "../../lib/voice-api";
import {
  addVoiceTrustedSite,
  getVoiceConfig,
  listVoiceTrustedSites,
  removeVoiceTrustedSite
} from "../../lib/voice-api";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function CourseAgentSettingsClient({ courseId }: { courseId: string }) {
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [sites, setSites] = useState<string[]>([]);
  const [week, setWeek] = useState(1);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadFeedback, setUploadFeedback] = useState("");
  const [uploadFailed, setUploadFailed] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [siteInput, setSiteInput] = useState("");
  const [siteFeedback, setSiteFeedback] = useState("");
  const [siteFailed, setSiteFailed] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const reload = useCallback(async () => {
    const [materialList, siteList] = await Promise.all([
      listCourseMaterials(courseId),
      listVoiceTrustedSites(courseId)
    ]);
    setMaterials(materialList);
    setSites(siteList.sites);
  }, [courseId]);

  useEffect(() => {
    let isCancelled = false;
    Promise.all([getVoiceConfig(courseId), listCourseMaterials(courseId), listVoiceTrustedSites(courseId)])
      .then(([voiceConfig, materialList, siteList]) => {
        if (isCancelled) return;
        setConfig(voiceConfig);
        setMaterials(materialList);
        setSites(siteList.sites);
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setUploadFailed(true);
        setUploadFeedback(
          error instanceof ApiError ? error.message : "설정 정보를 불러오지 못했습니다."
        );
      });
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    const invalid = files.find((file) => file.size > MAX_UPLOAD_BYTES);
    if (invalid) {
      setSelectedFiles([]);
      setUploadFailed(true);
      setUploadFeedback(`${invalid.name} 파일이 20MB를 넘습니다.`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setSelectedFiles(files);
    setUploadFailed(false);
    setUploadFeedback("");
  };

  const clearSelection = () => {
    setSelectedFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setUploadFeedback("파일 선택을 취소했습니다.");
    setUploadFailed(false);
  };

  const handleUpload = async () => {
    if (!selectedFiles.length) return;
    setIsUploading(true);
    const failures: string[] = [];
    let uploaded = 0;

    for (const [index, file] of selectedFiles.entries()) {
      setUploadFeedback(`${index + 1}/${selectedFiles.length} 업로드 중: ${file.name}`);
      try {
        const material = await uploadCourseMaterial(courseId, file, week);
        // Index immediately so the agent can cite the material on the next turn.
        await processCourseMaterial(courseId, material.id).catch(() => undefined);
        uploaded += 1;
      } catch (error) {
        failures.push(
          `${file.name}: ${error instanceof ApiError ? error.message : "업로드 실패"}`
        );
      }
    }

    clearSelection();
    setUploadFailed(failures.length > 0);
    setUploadFeedback(
      failures.length
        ? `${uploaded}개 반영, ${failures.length}개 실패: ${failures.join(", ")}`
        : `${uploaded}개 자료를 반영했습니다.`
    );
    await reload().catch(() => undefined);
    setIsUploading(false);
  };

  const handleDeleteMaterial = async (material: CourseMaterial) => {
    if (!window.confirm(`${material.originalFileName} 자료를 삭제할까요?`)) return;
    try {
      await deleteCourseMaterial(courseId, material.id);
      setUploadFailed(false);
      setUploadFeedback(`${material.originalFileName} 자료를 삭제했습니다.`);
      await reload();
    } catch (error) {
      setUploadFailed(true);
      setUploadFeedback(error instanceof ApiError ? error.message : "삭제에 실패했습니다.");
    }
  };

  const handleAddSite = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = siteInput.trim();
    if (!value) return;
    try {
      const result = await addVoiceTrustedSite(courseId, value);
      setSites(result.sites);
      setSiteInput("");
      setSiteFailed(false);
      setSiteFeedback("신뢰 사이트를 추가했습니다.");
    } catch (error) {
      setSiteFailed(true);
      setSiteFeedback(error instanceof ApiError ? error.message : "추가에 실패했습니다.");
    }
  };

  const handleRemoveSite = async (site: string) => {
    try {
      const result = await removeVoiceTrustedSite(courseId, site);
      setSites(result.sites);
      setSiteFailed(false);
      setSiteFeedback("신뢰 사이트를 삭제했습니다.");
    } catch (error) {
      setSiteFailed(true);
      setSiteFeedback(error instanceof ApiError ? error.message : "삭제에 실패했습니다.");
    }
  };

  return (
    <section className="course-agent-page">
      <div className="icampus-breadcrumb">
        과목 &gt; {config?.course_name ?? "강의"} &gt; <b>COURSE AGENT</b>
      </div>

      <div className="icampus-page-heading">
        <div>
          <h1>COURSE AGENT 설정</h1>
          <p>{config?.course_name ?? "이 과목"}의 AI 조교 근거와 검색 정책을 관리합니다.</p>
        </div>
        <span className="icampus-term-badge">교수자 화면</span>
      </div>

      <div className="icampus-notice">
        업로드한 강의자료는 색인이 끝나는 대로 과목 지식베이스에 반영됩니다. 외부 웹 검색은 아래
        신뢰 사이트로만 제한됩니다.
      </div>

      <div className="voice-settings-grid">
        <section className="icampus-card">
          <div className="icampus-card-head">
            <h2>강의 자료 관리</h2>
            <small>PDF · DOCX · PPTX · TXT · 최대 20MB</small>
          </div>
          <div className="icampus-card-body">
            <p className="voice-setting-intro">
              강의안, 읽기자료, FAQ를 업로드하면 학생 답변의 우선 근거로 사용합니다.
            </p>
            <div className="voice-site-form">
              <label>
                <span className="sr-only">주차</span>
                <input
                  aria-label="주차"
                  max={16}
                  min={1}
                  onChange={(event) => setWeek(Number(event.target.value) || 1)}
                  style={{ width: 80 }}
                  type="number"
                  value={week}
                />
              </label>
              <input
                aria-label="강의자료 파일 선택"
                multiple
                onChange={handleFileChange}
                ref={fileInputRef}
                type="file"
              />
            </div>
            <div className="voice-controls" style={{ justifyContent: "flex-start", marginTop: 12 }}>
              <button
                className="voice-primary"
                disabled={!selectedFiles.length || isUploading}
                onClick={handleUpload}
                type="button"
              >
                {selectedFiles.length > 1
                  ? `${selectedFiles.length}개 자료 업로드`
                  : "선택한 자료 업로드"}
              </button>
              <button
                className="voice-secondary"
                disabled={!selectedFiles.length || isUploading}
                onClick={clearSelection}
                type="button"
              >
                전체 선택 취소
              </button>
            </div>
            <div className="voice-feedback" data-tone={uploadFailed ? "error" : undefined} role="status">
              {uploadFeedback}
            </div>
            <ul className="voice-list">
              {materials.length === 0 ? (
                <li className="voice-empty">업로드된 강의자료가 없습니다.</li>
              ) : null}
              {materials.map((material) => (
                <li key={material.id}>
                  <span className="voice-file-meta">
                    <span className="material-status" data-status={material.processingStatus}>
                      {material.fileType.toUpperCase()}
                    </span>
                    <span className="voice-file-name">{material.originalFileName}</span>
                  </span>
                  <span className="voice-file-meta">
                    <span className="voice-file-size">
                      {material.week}주차 · {formatBytes(material.fileSize)}
                    </span>
                    <button
                      className="voice-danger"
                      onClick={() => handleDeleteMaterial(material)}
                      type="button"
                    >
                      삭제
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="icampus-card">
          <div className="icampus-card-head">
            <h2>신뢰 사이트 관리</h2>
            <small>외부 검색 허용 목록</small>
          </div>
          <div className="icampus-card-body">
            <p className="voice-setting-intro">
              강의자료에 근거가 부족할 때만 아래 도메인에서 보충 근거를 찾습니다.
            </p>
            <form className="voice-site-form" onSubmit={handleAddSite}>
              <input
                aria-label="신뢰 사이트 주소"
                maxLength={500}
                onChange={(event) => setSiteInput(event.target.value)}
                placeholder="예: kosis.kr"
                type="text"
                value={siteInput}
              />
              <button className="voice-primary" type="submit">
                추가
              </button>
            </form>
            <div className="voice-feedback" data-tone={siteFailed ? "error" : undefined} role="status">
              {siteFeedback}
            </div>
            <ul className="voice-list">
              {sites.length === 0 ? (
                <li className="voice-empty">등록된 신뢰 사이트가 없습니다.</li>
              ) : null}
              {sites.map((site) => (
                <li key={site}>
                  <a
                    className="voice-site-link"
                    href={`https://${site}`}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {site}
                  </a>
                  <button
                    className="voice-danger"
                    onClick={() => handleRemoveSite(site)}
                    type="button"
                  >
                    삭제
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </section>
  );
}
