export type IconName =
  | "account" | "dashboard" | "course" | "group" | "calendar" | "message"
  | "posts" | "mypage" | "info" | "timetable" | "school" | "content"
  | "material" | "upload" | "source" | "shield" | "send" | "question"
  | "bolt" | "chart" | "home" | "attendance" | "grade" | "agent"
  | "attachment" | "image" | "close" | "chevron" | "check"
  | "mic" | "mic-off";

export function UiIcon({
  name,
  className = ""
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg aria-hidden="true" className={`ui-icon ${className}`.trim()} fill="none" viewBox="0 0 24 24">
      {name === "account" ? <><circle cx="12" cy="8.1" r="3.1" /><path d="M5.8 19.2c.9-3.7 3.1-5.6 6.2-5.6s5.3 1.9 6.2 5.6" /><circle cx="12" cy="12" r="10" /></> : null}
      {name === "dashboard" ? <><path d="M4.2 14.2a7.8 7.8 0 0 1 15.6 0" /><path d="M12 14.2l3.1-4.2" /><path d="M5.4 18.6h13.2" /><path d="M7 12.4h1.5M15.5 12.4H17" /></> : null}
      {name === "course" ? <><path d="M6 4.8h10.8c.7 0 1.2.5 1.2 1.2v13.2H7.2A2.2 2.2 0 0 1 5 17V5.8c0-.6.4-1 1-1Z" /><path d="M7.2 19.2A2.2 2.2 0 0 1 5 17c0-1.2 1-2.2 2.2-2.2H18" /><path d="M8.3 8h6.4M8.3 10.8h6.4" /></> : null}
      {name === "group" ? <><circle cx="12" cy="8" r="2.6" /><path d="M7.5 18c.7-3 2.2-4.5 4.5-4.5s3.8 1.5 4.5 4.5" /><circle cx="6.5" cy="10" r="2" /><path d="M3.4 18c.4-2 1.4-3.2 3.1-3.5" /><circle cx="17.5" cy="10" r="2" /><path d="M20.6 18c-.4-2-1.4-3.2-3.1-3.5" /></> : null}
      {name === "calendar" ? <><rect x="4.5" y="5.7" width="15" height="14" rx="1.6" /><path d="M8 3.8v4M16 3.8v4M4.5 10h15" /><path d="M8 13h2M12 13h2M16 13h1M8 16h2M12 16h2M16 16h1" /></> : null}
      {name === "message" ? <><rect x="4.8" y="4.2" width="13.2" height="15.6" rx="1.3" /><path d="M8.2 8h6.4M8.2 11.2h7.9M8.2 14.4h5.1" /><path d="M18 7.1h1.4v15.6H7.6v-1.3" /></> : null}
      {name === "posts" ? <><rect x="6.3" y="4.4" width="11.4" height="16" rx="1.4" /><path d="M9.1 4.4c.2-1 1-1.6 2.9-1.6s2.7.6 2.9 1.6" /><path d="M9.2 8.4h5.6M9.2 11.6h5.6M9.2 14.8h4.2" /></> : null}
      {name === "mypage" ? <><rect x="4.4" y="4.2" width="15.2" height="15.2" rx="1.4" /><path d="M8 5.8v5h4.1v-5M15.2 6.2v4.4M13.2 8.4h4" /><path d="M7.3 14.1h4.4M7.3 16.9h9.3" /></> : null}
      {name === "info" ? <><circle cx="12" cy="12" r="9.2" /><path d="M9.3 9.1A2.8 2.8 0 0 1 12 7.5c1.8 0 3 1.1 3 2.7 0 1.3-.7 2-1.8 2.7-.9.6-1.2 1-1.2 2" /><path d="M12 18h.1" /></> : null}
      {name === "timetable" ? <><rect x="4.4" y="5.2" width="15.2" height="14.4" rx="1.4" /><path d="M8 3.6v3.8M16 3.6v3.8M4.4 9.3h15.2" /><path d="M7.6 12.4h2.2M12.4 12.4h2.2M7.6 15.6h2.2" /><circle cx="16.4" cy="16.1" r="2.8" /><path d="M16.4 14.6v1.7l1.2.8" /></> : null}
      {name === "school" ? <><path d="M3.8 10.5 12 5l8.2 5.5" /><path d="M6 10.5v8h12v-8" /><path d="M9 18.5v-4h6v4M8.5 12.2h1.8M13.7 12.2h1.8" /></> : null}
      {name === "content" ? <><rect x="4" y="5" width="6.5" height="6.5" rx="1.1" /><rect x="13.5" y="4.5" width="6.5" height="6.5" rx="1.1" /><rect x="8.8" y="14" width="6.5" height="6.5" rx="1.1" /><path d="M10.5 8.2h3M12 11.5v2.5" /></> : null}
      {name === "material" ? <><path d="M7 3.8h7.2L18 7.6v12.6H7z" /><path d="M14.2 3.8v3.8H18M9.3 11.3h5.4M9.3 14h5.4M9.3 16.7h3.5" /></> : null}
      {name === "upload" ? <><path d="M12 15.5V5.2M8.4 8.8 12 5.2l3.6 3.6" /><path d="M5.5 14.5v4.2h13v-4.2" /></> : null}
      {name === "source" ? <><circle cx="10.5" cy="10.5" r="5.6" /><path d="m15 15 4.6 4.6" /><path d="M8.2 10.5h4.6M10.5 8.2v4.6" /></> : null}
      {name === "shield" ? <><path d="M12 3.8 18.2 6v5.1c0 4.1-2.5 7-6.2 9.1-3.7-2.1-6.2-5-6.2-9.1V6z" /><path d="M12 8.2v5.1M12 16.5v.1" /></> : null}
      {name === "send" ? <><path d="M4 11.7 20 4.8l-6.8 15.7-2.3-6.5z" /><path d="m10.9 14 4.1-4.3" /></> : null}
      {name === "question" ? <><path d="M9.2 9.2A3.1 3.1 0 0 1 12 7.5c1.8 0 3.1 1.1 3.1 2.8 0 1.4-.8 2.1-1.9 2.8-.9.6-1.2 1.1-1.2 2.1" /><path d="M12 18h.1" /></> : null}
      {name === "bolt" ? <path d="M13 3.8 6.4 13h5.1L11 20.2l6.6-9.5h-5z" /> : null}
      {name === "chart" ? <><path d="M4.8 18.8h14.4M6.5 16l3.8-4.1 3.1 2.4 4.1-6" /><path d="M17.5 8.3v4h-4" /></> : null}
      {name === "home" ? <><path d="m3.8 11 8.2-6.5 8.2 6.5" /><path d="M6.2 9.3v10.2h11.6V9.3M9.5 19.5v-6h5v6" /></> : null}
      {name === "attendance" ? <><rect x="4.5" y="5.5" width="15" height="14" rx="1.5" /><path d="M8 3.5v4M16 3.5v4M4.5 9.5h15M8 14l2.2 2.2L16 11" /></> : null}
      {name === "grade" ? <><path d="M5 4.5h14v15H5zM8 8h8M8 12h4" /><path d="m13.8 16 1.4 1.4 2.8-3.2" /></> : null}
      {name === "agent" ? <><rect x="4.5" y="6.5" width="15" height="12" rx="2" /><path d="M12 3.5v3M8.5 11h.1M15.5 11h.1M8.5 15h7M2.8 11v3M21.2 11v3" /></> : null}
      {name === "attachment" ? <path d="m8.2 12.8 6.2-6.2a3 3 0 0 1 4.2 4.2l-8.2 8.2a4.5 4.5 0 0 1-6.4-6.4l8-8" /> : null}
      {name === "image" ? <><rect x="4" y="5" width="16" height="14" rx="1.5" /><circle cx="9" cy="10" r="1.5" /><path d="m5.5 17 4.2-4.2 3.1 3.1 2.1-2.1 3.6 3.2" /></> : null}
      {name === "close" ? <path d="m6 6 12 12M18 6 6 18" /> : null}
      {name === "chevron" ? <path d="m9 5 7 7-7 7" /> : null}
      {name === "check" ? <path d="m5 12.5 4.5 4.5L19 7.5" /> : null}
      {name === "mic" ? <><rect x="9.2" y="2.9" width="5.6" height="11.2" rx="2.8" /><path d="M5.9 11.1a6.1 6.1 0 0 0 12.2 0" /><path d="M12 17.2v3.9M8.9 21.1h6.2" /></> : null}
      {name === "mic-off" ? <><rect x="9.2" y="2.9" width="5.6" height="11.2" rx="2.8" /><path d="M5.9 11.1a6.1 6.1 0 0 0 12.2 0" /><path d="M12 17.2v3.9M8.9 21.1h6.2" /><path d="M4.1 3.4 19.9 20.6" /></> : null}
    </svg>
  );
}
