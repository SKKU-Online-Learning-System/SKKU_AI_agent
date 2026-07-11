"use client";

import { useState } from "react";
import { dashboardMetrics, demoCourses, demoLogs, materials } from "./demo-data";
import { MetricCard, PageToolbar, StatusBadge } from "./screen-primitives";
import type { ScreenId } from "./state";

const demoUsers = [
  { id: "user-1", name: "박학생", schoolId: "2026****12", role: "student", label: "학생" },
  { id: "user-2", name: "김교수", schoolId: "P20****04", role: "professor", label: "교수자" },
  { id: "user-3", name: "이관리", schoolId: "A20****01", role: "admin", label: "관리자" }
];

export function AdminScreen({ screen }: { screen: ScreenId }) {
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");
  if (screen === "admin-dashboard") return <section className="content-page"><h1>관리자 대시보드</h1><div className="metric-grid">{dashboardMetrics.map((metric) => <MetricCard {...metric} key={metric.label} />)}</div><div className="dashboard-columns"><div className="canvas-section"><h2>일자별 사용량</h2><div className="bar-chart" aria-label="최근 7일 질문 수"><i style={{ height: "42%" }} /><i style={{ height: "58%" }} /><i style={{ height: "49%" }} /><i style={{ height: "76%" }} /><i style={{ height: "68%" }} /><i style={{ height: "91%" }} /><i style={{ height: "82%" }} /></div></div><aside className="canvas-section"><h2>운영 상태</h2><p><StatusBadge tone="ready">정상</StatusBadge> API 및 로그 저장</p><p><StatusBadge tone="processing">3건</StatusBadge> 자료 처리 대기</p></aside></div></section>;
  if (screen === "admin-courses") return <section className="content-page"><h1>과목 관리</h1><PageToolbar><input aria-label="과목 검색" placeholder="과목명 또는 코드 검색" /><button type="button" className="primary-button">과목 등록</button></PageToolbar><div className="canvas-section">{demoCourses.map((course) => <div className="material-row" key={course.id}><div><strong>{course.title}</strong><span>{course.code} · 2026년 1학기</span></div><StatusBadge tone={course.agentStatus}>{course.agentStatus === "active" ? "활성" : "비활성"}</StatusBadge><button type="button">수정</button></div>)}</div></section>;
  if (screen === "admin-users") {
    const users = demoUsers.filter((user) => role === "all" || user.role === role);
    return <section className="content-page"><h1>사용자 및 권한</h1><PageToolbar><input aria-label="사용자 검색" placeholder="이름 또는 학번 검색" /><select aria-label="역할 필터" value={role} onChange={(event) => setRole(event.target.value)}><option value="all">모든 역할</option><option value="student">학생</option><option value="professor">교수자</option><option value="admin">관리자</option></select></PageToolbar><div className="table-wrap"><table><thead><tr><th>사용자</th><th>식별번호</th><th>역할</th><th>관리</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td>{user.name}</td><td>{user.schoolId}</td><td>{user.label}</td><td><button type="button">역할 변경</button></td></tr>)}</tbody></table></div></section>;
  }
  if (screen === "admin-materials") return <section className="content-page"><h1>전체 자료</h1><PageToolbar><select aria-label="처리 상태 필터"><option>모든 상태</option><option>처리 완료</option><option>처리 중</option><option>실패</option></select></PageToolbar><div className="canvas-section">{materials.map((material) => <div className="material-row" key={material.id}><div><strong>{material.title}</strong><span>{material.fileName}</span></div><StatusBadge tone={material.status}>{material.status}</StatusBadge><div><button type="button">재처리</button><button type="button">삭제</button></div></div>)}</div></section>;
  const logs = demoLogs.filter((log) => log.question.includes(query) || log.user.includes(query));
  return <section className="content-page"><h1>전체 로그</h1><PageToolbar><input aria-label="전체 로그 검색" placeholder="질문 또는 사용자 검색" value={query} onChange={(event) => setQuery(event.target.value)} /><button type="button">CSV 내보내기</button></PageToolbar><div className="table-wrap"><table><thead><tr><th>시각</th><th>역할</th><th>사용자</th><th>과목</th><th>질문</th><th>모델</th><th>응답</th></tr></thead><tbody>{logs.map((log) => <tr key={log.id}><td>{log.createdAt}</td><td>{log.role}</td><td>{log.user}</td><td>{log.course}</td><td>{log.question}</td><td>{log.model}</td><td>{log.responseTime}초</td></tr>)}</tbody></table></div></section>;
}
