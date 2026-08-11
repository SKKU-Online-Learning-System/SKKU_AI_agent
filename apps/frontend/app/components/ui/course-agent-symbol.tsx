/**
 * Course Agent symbol — React port of the `course-agent-symbol` web component
 * from the Course Agent. The animation states map to the agent lifecycle:
 * presence (idle), resonance (heard you), flow (working), bloom (answered),
 * sustain (settled), error.
 *
 * The gradient/mask ids are shared across instances on purpose: every instance
 * defines them identically, so resolving to the first one is correct.
 */

export type CourseAgentSymbolState =
  | "presence"
  | "resonance"
  | "flow"
  | "bloom"
  | "sustain"
  | "error";

const PETALS = [
  "M49.2 83C46 71 41 61 33 53C26 46 20 44 13 45C6 46 3 41 5 35C7 28 14 25 21 27C31 30 39 40 44 52C47 61 48.5 73 49.2 83Z",
  "M49.6 83C48 67 45 51 39 38C35 31 29 27 24 25C18 22 17 16 21 12C25 7 33 8 37 12C43 18 45 26 47 36C50 52 50 69 49.6 83Z",
  "M50 83C50 64 48 44 44 26C42 18 39 12 41 7C43 2 47 1 50 1C53 1 57 2 59 7C61 12 58 18 56 26C52 44 50 64 50 83Z",
  "M50.4 83C50 69 50 52 53 36C55 26 57 18 63 12C67 8 75 7 79 12C83 16 82 22 76 25C71 27 65 31 61 38C55 51 52 67 50.4 83Z",
  "M50.8 83C51.5 73 53 61 56 52C61 40 69 30 79 27C86 25 93 28 95 35C97 41 94 46 87 45C80 44 74 46 67 53C59 61 54 71 50.8 83Z"
];
const DELAYS = ["0.24s", "0.08s", "0s", "0.16s", "0.32s"];
const ENERGY_PATHS = [
  "M50 92Q39 65 12 39",
  "M50 92Q45 48 29 16",
  "M50 92Q50 44 50 7",
  "M50 92Q55 48 71 16",
  "M50 92Q61 65 88 39"
];
const TIPS: Array<[number, number, string]> = [
  [12, 39, "0.12s"],
  [29, 16, "0.04s"],
  [50, 7, "0s"],
  [71, 16, "0.08s"],
  [88, 39, "0.16s"]
];

export function CourseAgentSymbol({
  animated = false,
  label,
  size = 48,
  state = "presence"
}: {
  animated?: boolean;
  label?: string;
  size?: number;
  state?: CourseAgentSymbolState;
}) {
  return (
    <span
      aria-hidden={label ? undefined : "true"}
      aria-label={label}
      className="course-agent-symbol"
      data-animated={animated ? "true" : undefined}
      data-state={state}
      role={label ? "img" : undefined}
      style={{ height: size, width: size }}
    >
      <svg aria-hidden="true" focusable="false" viewBox="0 0 100 100">
        <defs>
          <linearGradient
            gradientUnits="userSpaceOnUse"
            id="course-agent-petal-gradient"
            x1="10"
            x2="86"
            y1="78"
            y2="12"
          >
            <stop offset="0" stopColor="#0a3d34" />
            <stop offset=".32" stopColor="#00664f" />
            <stop offset=".62" stopColor="#1e7a5e" />
            <stop offset=".84" stopColor="#8ad26a" />
            <stop offset="1" stopColor="#d6e85a" />
          </linearGradient>
          <radialGradient id="course-agent-core-aura">
            <stop offset="0" stopColor="#d6e85a" stopOpacity=".72" />
            <stop offset=".48" stopColor="#d6e85a" stopOpacity=".36" />
            <stop offset="1" stopColor="#d6e85a" stopOpacity="0" />
          </radialGradient>
          {PETALS.map((path, index) => (
            <path d={path} id={`course-agent-petal-${index + 1}`} key={index} />
          ))}
          <mask
            height="100"
            id="course-agent-fan-mask"
            maskUnits="userSpaceOnUse"
            width="100"
            x="0"
            y="0"
          >
            <rect fill="white" height="100" width="100" />
            <path
              d="M49.35 83C47 61 42 43 34 29M49.75 83C49 55 46 30 42 8M50.25 83C51 55 54 30 58 8M50.65 83C53 61 58 43 66 29"
              fill="none"
              stroke="black"
              strokeLinecap="round"
              strokeWidth="2.4"
            />
          </mask>
        </defs>
        <g className="course-agent-mark">
          <g mask="url(#course-agent-fan-mask)">
            {PETALS.map((_, index) => (
              <use
                className="course-agent-petal"
                href={`#course-agent-petal-${index + 1}`}
                key={index}
              />
            ))}
          </g>
          <g mask="url(#course-agent-fan-mask)">
            {PETALS.map((_, index) => (
              <use
                className="course-agent-growth-petal"
                href={`#course-agent-petal-${index + 1}`}
                key={index}
                style={{ ["--delay" as string]: DELAYS[index] }}
              />
            ))}
          </g>
          <g pathLength={1}>
            {ENERGY_PATHS.map((path, index) => (
              <path
                className="course-agent-energy"
                d={path}
                key={index}
                pathLength={1}
                style={{ ["--delay" as string]: DELAYS[index] }}
              />
            ))}
          </g>
          {TIPS.map(([cx, cy, delay], index) => (
            <circle
              className="course-agent-tip"
              cx={cx}
              cy={cy}
              key={index}
              r="2.2"
              style={{ ["--delay" as string]: delay }}
            />
          ))}
          <circle className="course-agent-core-aura" cx="50" cy="92" r="9" />
          <circle className="course-agent-halo" cx="50" cy="92" r="11" />
          <circle className="course-agent-ring" cx="50" cy="92" r="9" />
          <circle className="course-agent-ring course-agent-ring--second" cx="50" cy="92" r="14" />
          <circle className="course-agent-core" cx="50" cy="92" r="4.8" />
        </g>
      </svg>
    </span>
  );
}
