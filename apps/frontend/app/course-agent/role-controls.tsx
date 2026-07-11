"use client";

import type { CourseMaterial } from "@skku-course-agent/shared";
import { useEffect, useRef, useState } from "react";
import type React from "react";
import { personalityOptions } from "./demo-data";
import type {
  AgentRole,
  AttachmentItem,
  CourseAgentAction,
  CourseAgentState
} from "./state";
import { validateAttachment } from "./state";

type AttachmentControlProps = {
  role: AgentRole;
  attachments: AttachmentItem[];
  dispatch: React.Dispatch<CourseAgentAction>;
};

type AttachmentListProps = AttachmentControlProps;

export function AttachmentList({ role, attachments, dispatch }: AttachmentListProps) {
  const removeAttachment = (attachment: AttachmentItem) => {
    if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    dispatch({ type: "remove-attachment", role, attachmentId: attachment.id });
  };

  return (
    <ul className="attachment-list">
      {attachments.map((attachment) => (
        <li key={attachment.id}>
          {attachment.previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={attachment.previewUrl} alt="" />
          ) : null}
          <span>{attachment.name}</span>
          <button type="button" onClick={() => removeAttachment(attachment)}>
            삭제
          </button>
        </li>
      ))}
    </ul>
  );
}

function AttachmentControl({ role, attachments, dispatch }: AttachmentControlProps) {
  const [error, setError] = useState<string | null>(null);
  const createdUrls = useRef(new Set<string>());
  const accept =
    role === "student"
      ? ".pdf,.docx,.txt,.png,.jpg,.jpeg,image/png,image/jpeg"
      : ".pdf,.pptx,.docx,.txt";

  useEffect(() => {
    const urls = createdUrls.current;
    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
      urls.clear();
    };
  }, []);

  const addAttachments = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    const firstError = files.map((file) => validateAttachment(file, role)).find(Boolean);
    setError(firstError ?? null);

    const validAttachments = files.flatMap((file) => {
      if (validateAttachment(file, role)) return [];
      const previewUrl =
        role === "student" && file.type.startsWith("image/")
          ? URL.createObjectURL(file)
          : undefined;
      if (previewUrl) createdUrls.current.add(previewUrl);
      return [
        {
          id: crypto.randomUUID(),
          name: file.name,
          size: file.size,
          type: file.type,
          previewUrl
        }
      ];
    });

    if (validAttachments.length > 0) {
      dispatch({ type: "add-attachments", role, attachments: validAttachments });
    }
    event.target.value = "";
  };

  return (
    <div className="attachment-control">
      <label className="attachment-picker">
        파일 첨부
        <input type="file" multiple accept={accept} hidden onChange={addAttachments} />
      </label>
      {error ? <p role="alert">{error}</p> : null}
      <AttachmentList role={role} attachments={attachments} dispatch={dispatch} />
    </div>
  );
}

type StudentControlsProps = {
  state: CourseAgentState;
  dispatch: React.Dispatch<CourseAgentAction>;
};

export function StudentControls({ state, dispatch }: StudentControlsProps) {
  return (
    <section>
      <fieldset>
        <legend>답변 성격</legend>
        {personalityOptions.map((option) => (
          <label key={option.id}>
            <input
              type="radio"
              name="personality"
              value={option.id}
              checked={state.student.personality === option.id}
              onChange={() => dispatch({ type: "set-personality", personality: option.id })}
            />
            <span>{option.label}</span>
            <small>{option.description}</small>
          </label>
        ))}
      </fieldset>
      <AttachmentControl
        role="student"
        attachments={state.student.attachments}
        dispatch={dispatch}
      />
    </section>
  );
}

type ProfessorControlsProps = {
  materials: CourseMaterial[];
  state: CourseAgentState;
  dispatch: React.Dispatch<CourseAgentAction>;
};

export function ProfessorControls({ materials, state, dispatch }: ProfessorControlsProps) {
  const readyMaterialIds = materials
    .filter((material) => material.status === "ready")
    .map((material) => material.id);

  return (
    <section>
      <div>
        <button
          type="button"
          onClick={() => dispatch({ type: "set-materials", materialIds: readyMaterialIds })}
        >
          전체 선택
        </button>
        <button
          type="button"
          onClick={() => dispatch({ type: "set-materials", materialIds: [] })}
        >
          전체 해제
        </button>
      </div>
      <ul>
        {materials.map((material) => {
          const ready = material.status === "ready";
          return (
            <li key={material.id}>
              <label>
                <input
                  id={material.id}
                  type="checkbox"
                  checked={state.professor.selectedMaterialIds.includes(material.id)}
                  disabled={!ready}
                  onChange={() =>
                    dispatch({
                      type: "toggle-material",
                      materialId: material.id,
                      selectable: ready
                    })
                  }
                />
                <span>{material.title}</span>
                {!ready ? <span> ({material.status})</span> : null}
              </label>
            </li>
          );
        })}
      </ul>
      <AttachmentControl
        role="professor"
        attachments={state.professor.attachments}
        dispatch={dispatch}
      />
    </section>
  );
}
