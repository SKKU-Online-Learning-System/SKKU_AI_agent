"use client";

import { useEffect, useState } from "react";
import { ApiError, getActivityStatistics } from "../../lib/api";
import type { ActivityDay, ActivityStatistics, ActivityUserRow } from "../../lib/api";

type Metric = "loginCount" | "activeMinutes" | "turnCount" | "totalTokens";
type DayKey = Exclude<keyof ActivityDay, "date">;

const METRICS: Array<{ key: Metric; label: string; unit: string; byDate: DayKey; hint: string }> = [
  { key: "loginCount", label: "접속", unit: "회", byDate: "logins", hint: "로그인 횟수" },
  { key: "activeMinutes", label: "활성 시간", unit: "분", byDate: "activeMinutes", hint: "접속·대화가 이어진 시간" },
  { key: "turnCount", label: "대화 turn", unit: "회", byDate: "turns", hint: "질문-답변 왕복 수" },
  { key: "totalTokens", label: "토큰", unit: "", byDate: "tokens", hint: "입력 + 출력 토큰" }
];

const RANGES = [7, 30, 90];
const TOP_USERS = 10;

const numberFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });

function formatNumber(value: number): string {
  return numberFormat.format(value);
}

function formatCompact(value: number): string {
  if (value >= 10000) return `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}만`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}천`;
  return formatNumber(value);
}

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatDay(date: string): string {
  const [, month, day] = date.split("-");
  return `${Number(month)}/${Number(day)}`;
}

/** Every day in the window, zero-filled, so the axis is continuous. */
function fillDays(since: string, days: ActivityDay[]): ActivityDay[] {
  const byDate = new Map(days.map((day) => [day.date, day]));
  const result: ActivityDay[] = [];
  const cursor = new Date(since);
  const today = new Date();
  while (cursor <= today) {
    const date = cursor.toISOString().slice(0, 10);
    result.push(byDate.get(date) ?? { date, logins: 0, turns: 0, tokens: 0, activeMinutes: 0 });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return result;
}

function Sparkline({ values }: { values: number[] }) {
  const width = 120;
  const height = 32;
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => `${index * step},${height - 2 - ((height - 6) * value) / max}`);
  return (
    <svg aria-hidden="true" className="activity-sparkline" viewBox={`0 0 ${width} ${height}`}>
      <polygon points={`0,${height} ${points.join(" ")} ${width},${height}`} />
      <polyline points={points.join(" ")} />
    </svg>
  );
}

function DailyChart({
  days,
  metric,
  unit
}: {
  days: ActivityDay[];
  metric: DayKey;
  unit: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const height = 230;
  const top = 28;
  const bottom = 196;
  const left = 34;
  const values = days.map((day) => day[metric]);
  const max = Math.max(...values, 1);
  const slot = (width - left) / Math.max(days.length, 1);
  const barWidth = Math.max(3, Math.min(26, slot - 4));
  const labelEvery = Math.max(1, Math.ceil(days.length / 9));
  const peak = values.indexOf(max);
  const ticks = [0.5, 1];

  if (values.every((value) => value === 0)) {
    return <p className="activity-chart-empty">이 기간에는 기록이 없습니다.</p>;
  }

  return (
    <svg
      aria-label="일자별 추이"
      className="activity-chart"
      onMouseLeave={() => setHover(null)}
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      {ticks.map((tick) => {
        const y = bottom - (bottom - top) * tick;
        return (
          <g className="activity-chart-grid" key={tick}>
            <line x1={left} x2={width} y1={y} y2={y} />
            <text textAnchor="end" x={left - 6} y={y + 4}>{formatCompact(max * tick)}</text>
          </g>
        );
      })}
      <line className="activity-chart-baseline" x1={left} x2={width} y1={bottom} y2={bottom} />
      {days.map((day, index) => {
        const value = values[index];
        const barHeight = ((bottom - top) * value) / max;
        const x = left + index * slot + (slot - barWidth) / 2;
        const active = hover === index || (hover === null && index === peak);
        return (
          <g
            className={`activity-chart-mark${active ? " is-active" : ""}`}
            key={day.date}
            onMouseEnter={() => setHover(index)}
          >
            <rect className="activity-chart-hit" height={bottom - top} width={slot} x={left + index * slot} y={top} />
            <rect className="activity-chart-bar" height={barHeight} rx={3} width={barWidth} x={x} y={bottom - barHeight} />
            {index % labelEvery === 0 ? (
              <text className="activity-chart-label" textAnchor="middle" x={x + barWidth / 2} y={bottom + 18}>
                {formatDay(day.date)}
              </text>
            ) : null}
          </g>
        );
      })}
      {(() => {
        const index = hover ?? peak;
        const value = values[index];
        if (value === undefined) return null;
        const barHeight = ((bottom - top) * value) / max;
        const cx = left + index * slot + slot / 2;
        const label = `${formatDay(days[index].date)} · ${formatNumber(value)}${unit}`;
        const boxWidth = label.length * 7.2 + 16;
        const x = Math.min(Math.max(cx - boxWidth / 2, left), width - boxWidth);
        const y = Math.max(bottom - barHeight - 30, 0);
        return (
          <g className="activity-chart-tooltip" pointerEvents="none">
            <rect height={22} rx={4} width={boxWidth} x={x} y={y} />
            <text textAnchor="middle" x={x + boxWidth / 2} y={y + 15}>{label}</text>
          </g>
        );
      })()}
    </svg>
  );
}

function RankedUsers({
  rows,
  metric,
  unit
}: {
  rows: ActivityUserRow[];
  metric: Metric;
  unit: string;
}) {
  if (rows.length === 0) {
    return <p className="activity-chart-empty">이 기간에 이용한 학생이 없습니다.</p>;
  }
  const max = Math.max(...rows.map((row) => row[metric]), 1);
  return (
    <ol className="activity-rank" aria-label="학생별 순위">
      {rows.map((row, index) => (
        <li key={row.userId} title={row.email}>
          <span className="activity-rank-no">{index + 1}</span>
          <span className="activity-rank-name">
            {row.name}
            <small>{row.email}</small>
          </span>
          <span className="activity-rank-bar">
            <span style={{ width: `${(100 * row[metric]) / max}%` }} />
          </span>
          <span className="activity-rank-value">
            {formatNumber(row[metric])}
            {unit}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function ActivityStatisticsClient() {
  const [days, setDays] = useState(30);
  const [metric, setMetric] = useState<Metric>("turnCount");
  const [data, setData] = useState<ActivityStatistics | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getActivityStatistics(days)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setErrorMessage(null);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setErrorMessage(
          error instanceof ApiError ? error.message : "이용 통계를 불러오지 못했습니다."
        );
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const current = METRICS.find((item) => item.key === metric) ?? METRICS[0];
  const filledDays = data ? fillDays(data.since, data.byDate) : [];
  const ranked: ActivityUserRow[] = data
    ? [...data.users].filter((row) => row[metric] > 0).sort((a, b) => b[metric] - a[metric])
    : [];
  const totalFor = (item: (typeof METRICS)[number]): number =>
    data ? data.totals[item.key] : 0;

  return (
    <section className="role-page activity-page">
      <header className="activity-header">
        <div>
          <h1>이용 통계</h1>
          <p>학생들이 COURSE AGENT를 얼마나 쓰는지, 접속·활성 시간·대화 turn·토큰 로그로 집계합니다.</p>
        </div>
        <form className="log-filters" onSubmit={(event) => event.preventDefault()}>
          <label>
            기간
            <select onChange={(event) => setDays(Number(event.target.value))} value={days}>
              {RANGES.map((range) => (
                <option key={range} value={range}>
                  최근 {range}일
                </option>
              ))}
            </select>
          </label>
        </form>
      </header>

      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {!data && !errorMessage ? <p className="activity-chart-empty">불러오는 중…</p> : null}

      {data ? (
        <>
          <div className="activity-tiles" role="group" aria-label="지표 선택">
            {METRICS.map((item) => (
              <button
                aria-pressed={metric === item.key}
                className="activity-tile"
                key={item.key}
                onClick={() => setMetric(item.key)}
                type="button"
              >
                <span className="activity-tile-label">{item.label}</span>
                <span className="activity-tile-value">
                  {formatNumber(totalFor(item))}
                  <small>{item.unit}</small>
                </span>
                <Sparkline values={filledDays.map((day) => day[item.byDate])} />
                <span className="activity-tile-hint">
                  {item.key === "totalTokens"
                    ? `입력 ${formatCompact(data.totals.promptTokens)} · 출력 ${formatCompact(data.totals.completionTokens)}`
                    : item.hint}
                </span>
              </button>
            ))}
          </div>

          <div className="activity-charts">
            <section>
              <h2>
                일자별 {current.label}
                <span>전체 학생 합계</span>
              </h2>
              <DailyChart days={filledDays} metric={current.byDate} unit={current.unit} />
            </section>
            <section>
              <h2>
                학생별 {current.label}
                <span>상위 {Math.min(TOP_USERS, ranked.length)}명</span>
              </h2>
              <RankedUsers metric={metric} rows={ranked.slice(0, TOP_USERS)} unit={current.unit} />
            </section>
          </div>

          <section className="activity-table-section">
            <h2>
              학생별 상세
              <span>{formatNumber(data.users.length)}명</span>
            </h2>
            <div className="course-table-wrap">
              <table className="course-table activity-table">
                <thead>
                  <tr>
                    <th>학생</th>
                    <th>접속</th>
                    <th>마지막 접속</th>
                    <th>활성 시간</th>
                    <th>대화 turn</th>
                    <th>입력 토큰</th>
                    <th>출력 토큰</th>
                    <th>총 토큰</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((row) => {
                    const idle = row.loginCount === 0 && row.turnCount === 0;
                    return (
                      <tr className={idle ? "is-idle" : undefined} key={row.userId}>
                        <td>
                          <span className="activity-table-name">
                            {row.name}
                            <small>{row.email}</small>
                          </span>
                        </td>
                        <td>{formatNumber(row.loginCount)}</td>
                        <td>{formatDateTime(row.lastLoginAt)}</td>
                        <td>{formatNumber(row.activeMinutes)}분</td>
                        <td>{formatNumber(row.turnCount)}</td>
                        <td>{formatNumber(row.promptTokens)}</td>
                        <td>{formatNumber(row.completionTokens)}</td>
                        <td>
                          <strong>{formatNumber(row.totalTokens)}</strong>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
