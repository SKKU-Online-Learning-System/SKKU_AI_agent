"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { VoicePlotPoint, VoiceVisualization } from "../../lib/voice-api";
import { fetchVoicePdfUrl } from "../../lib/voice-api";

function Plot({ visualization }: { visualization: VoiceVisualization }) {
  const points = visualization.points.filter(
    (point: VoicePlotPoint) => Number.isFinite(point.x) && Number.isFinite(point.y)
  );
  if (points.length < 2) return null;

  let xMin = Math.min(...points.map((point) => point.x));
  let xMax = Math.max(...points.map((point) => point.x));
  let yMin = Math.min(...points.map((point) => point.y));
  let yMax = Math.max(...points.map((point) => point.y));
  if (xMin === xMax) {
    xMin -= 1;
    xMax += 1;
  }
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }

  const left = 64;
  const right = 616;
  const top = 20;
  const bottom = 274;
  const sx = (x: number) => left + ((x - xMin) / (xMax - xMin)) * (right - left);
  const sy = (y: number) => bottom - ((y - yMin) / (yMax - yMin)) * (bottom - top);
  const path = points
    .map((point, index) => `${index ? "L" : "M"}${sx(point.x)} ${sy(point.y)}`)
    .join(" ");
  const midY = (top + bottom) / 2;
  const ticks: Array<[number, number, "start" | "end", number]> = [
    [left, 292, "start", xMin],
    [right, 292, "end", xMax],
    [52, bottom, "end", yMin],
    [52, top + 4, "end", yMax]
  ];

  return (
    <svg
      aria-label={`${visualization.title}: ${visualization.caption}`}
      className="voice-plot"
      role="img"
      viewBox="0 0 640 320"
    >
      <line className="voice-plot-axis" x1={left} x2={right} y1={bottom} y2={bottom} />
      <line className="voice-plot-axis" x1={left} x2={left} y1={top} y2={bottom} />
      <path className="voice-plot-line" d={path} />
      {points.map((point, index) => (
        <circle className="voice-plot-point" cx={sx(point.x)} cy={sy(point.y)} key={index} r={4} />
      ))}
      <text className="voice-plot-label" textAnchor="middle" x={(left + right) / 2} y={310}>
        {visualization.x_label}
      </text>
      <text
        className="voice-plot-label"
        textAnchor="middle"
        transform={`rotate(-90 16 ${midY})`}
        x={16}
        y={midY}
      >
        {visualization.y_label}
      </text>
      {ticks.map(([x, y, anchor, value], index) => (
        <text className="voice-plot-label" key={index} textAnchor={anchor} x={x} y={y}>
          {Number(value.toPrecision(4)).toString()}
        </text>
      ))}
    </svg>
  );
}

export function CourseAgentVisualizationCard({
  courseId,
  visualization
}: {
  courseId: string;
  visualization: VoiceVisualization;
}) {
  const formulaRef = useRef<HTMLDivElement | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  useEffect(() => {
    if (visualization.kind !== "formula" || !formulaRef.current) return;
    void window.MathJax?.typesetPromise?.([formulaRef.current]).catch(() => undefined);
  }, [visualization]);

  useEffect(() => {
    if (visualization.kind !== "pdf" || !visualization.material_id) return;
    let active = true;
    let objectUrl = "";
    fetchVoicePdfUrl(courseId, visualization.material_id)
      .then((url) => {
        objectUrl = url;
        if (active) setPdfUrl(`${url}#page=${visualization.page ?? 1}&view=FitH`);
      })
      .catch(() => {
        if (active) setPdfError("PDF 페이지를 불러오지 못했습니다.");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [courseId, visualization]);

  return (
    <div className="voice-message" data-role="assistant">
      <div className="voice-avatar" />
      <div className="voice-bubble-wrap">
        <div className="voice-bubble voice-visualization">
          <h3 className="voice-visualization-title">{visualization.title}</h3>
          {visualization.kind === "formula" ? (
            <div className="voice-visualization-formula" ref={formulaRef}>
              {`$$${visualization.latex}$$`}
            </div>
          ) : null}
          {visualization.kind === "flow" ? (
            <div className="voice-visualization-flow">
              {visualization.labels.map((label, index) => (
                <Fragment key={`${label}-${index}`}>
                  <div className="voice-visualization-node">{label}</div>
                  {index < visualization.labels.length - 1 ? (
                    <span aria-hidden="true" className="voice-visualization-arrow">
                      →
                    </span>
                  ) : null}
                </Fragment>
              ))}
            </div>
          ) : null}
          {visualization.kind === "plot" ? <Plot visualization={visualization} /> : null}
          {visualization.kind === "pdf" ? (
            pdfUrl ? (
              <iframe
                className="voice-visualization-pdf"
                src={pdfUrl}
                title={`${visualization.file ?? visualization.title} ${visualization.page ?? 1}쪽`}
              />
            ) : (
              <p className="voice-visualization-pdf-status">
                {pdfError ?? "PDF 페이지를 불러오는 중입니다."}
              </p>
            )
          ) : null}
          <p className="voice-visualization-caption">{visualization.caption}</p>
        </div>
      </div>
    </div>
  );
}
