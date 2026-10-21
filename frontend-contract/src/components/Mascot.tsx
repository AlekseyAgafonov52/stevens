import { T } from "../content/texts";

export type MascotState = "idle" | "listening" | "thinking" | "speaking";

/**
 * Д14 Персонаж: Стивенс — сдержанный дворецкий. Только фронт.
 * Состояние показывает, что происходит: слушает, думает, говорит.
 */
export function Mascot({
  state = "idle",
  size = 32,
}: {
  state?: MascotState;
  size?: number;
}) {
  return (
    <svg
      className={`mascot mascot-${state}`}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={T.mascot_label}
    >
      <circle cx="32" cy="32" r="31" className="mascot-bg" />
      {/* голова */}
      <ellipse cx="32" cy="29" rx="15" ry="17" className="mascot-face" />
      {/* причёска с пробором */}
      <path
        d="M17 26c0-11 7-16 15-16s15 5 15 16c-3-5-8-8-14-8l-3 4-1-4c-5 1-9 4-12 8z"
        className="mascot-hair"
      />
      {/* глаза */}
      <g className="mascot-eyes">
        <ellipse cx="26" cy="29" rx="1.8" ry="2" />
        <ellipse cx="38" cy="29" rx="1.8" ry="2" />
      </g>
      {/* усы */}
      <path
        d="M24 37c3-2 6-2 8 0 2-2 5-2 8 0-3 1-5 1-8 0-3 1-5 1-8 0z"
        className="mascot-hair"
      />
      {/* рот: в разговоре открывается */}
      <ellipse cx="32" cy="41" rx="3" ry="1" className="mascot-mouth" />
      {/* воротник и бабочка */}
      <path d="M18 56c3-6 8-9 14-9s11 3 14 9z" className="mascot-coat" />
      <path d="M26 49l6 3 6-3v6l-6-3-6 3z" className="mascot-tie" />
    </svg>
  );
}
