import type { ChatHistoryAttachment } from "../../lib/api";
import type { VoiceAttachment } from "../../lib/voice-api";
import { UiIcon } from "../ui/ui-icon";

// Files one typed question may carry. The server enforces its own limit too;
// this only keeps the composer from offering more than it will accept.
export const MAX_ATTACHMENTS = 4;
const ATTACHMENT_EXTENSIONS = /\.(png|jpe?g|webp|gif|bmp|pdf)$/i;
export const ATTACHMENT_HINT_TYPES = "이미지 또는 PDF만 첨부할 수 있어요.";
// How often the composer asks how far a long PDF's index is.
export const INDEX_POLL_MS = 1500;

/** An attachment as it appears on a sent message; the preview is a local object URL. */
export type SentAttachment = VoiceAttachment & { previewUrl?: string | null };

/**
 * A file in the composer, from the moment it is picked until the turn is sent --
 * or, for a long PDF that is read by excerpt, until the student removes it: such
 * a file stays pinned across turns so every question can look things up in it.
 */
export type PendingAttachment = {
  localId: number;
  file: File;
  previewUrl: string | null;
  status: "uploading" | "indexing" | "ready" | "error";
  attachment?: VoiceAttachment;
  error?: string;
  pinned?: boolean;
};

export function isAttachable(file: File): boolean {
  return (
    ATTACHMENT_EXTENSIONS.test(file.name) ||
    file.type.startsWith("image/") ||
    file.type === "application/pdf"
  );
}

/** Object URL for an image preview; jsdom and older browsers may not have it. */
export function previewUrlFor(file: File): string | null {
  if (!file.type.startsWith("image/") || typeof URL.createObjectURL !== "function") return null;
  try {
    return URL.createObjectURL(file);
  } catch {
    return null;
  }
}

export function revokePreview(url: string | null | undefined): void {
  if (url && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

export function attachmentMeta(attachment: VoiceAttachment): string {
  if (attachment.kind === "pdf" && attachment.mode === "excerpt") {
    return `PDF · ${attachment.pages}쪽 · 질문마다 관련 쪽 참고`;
  }
  if (attachment.kind === "pdf") return `PDF · ${attachment.pages}쪽`;
  return `이미지 · ${formatBytes(attachment.size)}`;
}

export function indexMeta(attachment: VoiceAttachment): string {
  const index = attachment.index;
  if (!index) return "색인 중";
  return `색인 중 ${index.pages_done}/${index.pages}쪽`;
}

export function isExcerpted(attachment: VoiceAttachment | undefined): boolean {
  return attachment?.mode === "excerpt";
}

/** Stored history carries the attachment shape of the log; the live agent uses the wire shape. */
export function toSentAttachment(attachment: ChatHistoryAttachment): SentAttachment {
  return {
    chars: 0,
    id: attachment.id,
    kind: attachment.kind === "pdf" ? "pdf" : "image",
    name: attachment.name,
    pages: attachment.pages,
    size: attachment.size
  };
}

export function AttachmentChips({ attachments }: { attachments: SentAttachment[] }) {
  if (!attachments.length) return null;
  return (
    <ul aria-label="첨부 파일" className="voice-attachment-list">
      {attachments.map((attachment) => (
        <li className="voice-attachment" data-kind={attachment.kind} key={attachment.id}>
          {attachment.previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL, not an asset
            <img alt="" className="voice-attachment-thumb" src={attachment.previewUrl} />
          ) : (
            <UiIcon
              className="voice-attachment-icon"
              name={attachment.kind === "pdf" ? "material" : "image"}
            />
          )}
          <span className="voice-attachment-name" title={attachment.name}>
            {attachment.name}
          </span>
          <span className="voice-attachment-meta">
            {attachment.mode === "excerpt" && attachment.pages_used?.length
              ? `PDF · ${attachment.pages_used.join(", ")}쪽 참고`
              : attachment.mode === "vision"
                ? `${attachment.kind === "pdf" ? "PDF" : "이미지"} · 모델이 직접 봄`
                : attachmentMeta(attachment)}
          </span>
        </li>
      ))}
    </ul>
  );
}
