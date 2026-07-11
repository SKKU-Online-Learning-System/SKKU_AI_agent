"use client";

import { useState } from "react";
import { dashboardMetrics, demoLogs, materials } from "./demo-data";
import { MetricCard, PageToolbar, StatusBadge } from "./screen-primitives";
import type { ScreenId } from "./state";

const statusLabel = { ready: "처리 완료", processing: "처리 중", failed: "실패", uploaded: "업로드됨" } as const;

export function ProfessorScreen({ screen }: { screen: ScreenId }) {
  const [active, setActive] = useState(true);
  const [policy, setPolicy] = useState("sources");
  const [query, setQuery] = useState("");
  if (screen === "professor-dashboard") return <section className="content-page"><h1>교수자 대시보드</h1><div className="metric-grid">{dashboardMetrics.slice(1, 5).map((metric) => <MetricCard {...metric} key={metric.label} />)}</div><div className="canvas-section"><h2>담당 과목 운영 현황</h2><p>문제해결 SWE2026_41 · 자료 3개 · 최근 질문 48개</p><StatusBadge tone={active ? "active" : "inactive"}>{active ? "에이전트 활성" : "에이전트 비활성"}</StatusBadge></div></section>;
  if (screen === "professor-materials") return <section className="content-page"><h1>강의자료</h1><PageToolbar><label className="upload-button">자료 업로드<input type="file" hidden accept=".pdf,.pptx,.docx,.txt" /></label><span>PDF, PPTX, DOCX, TXT · 파일당 20MB</span></PageToolbar><div className="canvas-section"><h2>업로드 자료</h2>{materials.map((material) => <div className="material-row" key={material.id}><div><strong>{material.title}</strong><span>{material.fileName}</span></div><StatusBadge tone={material.status}>{statusLabel[material.status]}</StatusBadge><button type="button" disabled={material.status !== "failed"}>재처리</button></div>)}</div></section>;
  if (screen === "professor-settings") return <section className="content-page"><h1>에이전트 설정</h1><div className="settings-panel"><label className="switch-row"><span><strong>코스 에이전트 활성화</strong><small>비활성화하면 학생이 채팅을 사용할 수 없습니다.</small></span><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} /></label><fieldset><legend>기본 응답 정책</legend>{[["sources", "강의자료 기반 답변 우선"], ["strict", "출처 없는 답변 제한"], ["hint", "힌트 중심 답변"], ["direct", "직접 설명 중심 답변"]].map(([value, label]) => <label key={value}><input type="radio" name="policy" value={value} checked={policy === value} onChange={() => setPolicy(value)} />{label}</label>)}</fieldset><p aria-live="polite">현재 정책: {policy}</p></div></section>;
  const logs = demoLogs.filter((log) => log.question.includes(query) || log.course.includes(query));
  return <section className="content-page"><h1>질문 로그</h1><PageToolbar><input aria-label="질문 로그 검색" placeholder="질문 또는 과목 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></PageToolbar><div className="table-wrap"><table><thead><tr><th>시각</th><th>질문</th><th>출처</th><th>응답 시간</th></tr></thead><tbody>{logs.map((log) => <tr key={log.id}><td>{log.createdAt}</td><td>{log.question}</td><td>{log.source}</td><td>{log.responseTime}초</td></tr>)}</tbody></table></div></section>;
}
