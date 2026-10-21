/**
 * Поклон и покачивание головой без отдельных кадров: фигура считается для доли движения k,
 * поэтому движение плавное. При k = 0 рисунок совпадает с stevens-rest.svg (ночью — с rest-night).
 * Поклон — наклоняется всё тело (k от 0 до глубины поклона). Покачивание — макушка с лицом мягко
 * сдвигается влево-вправо без поворота (k от −1 до 1), низ стоит на месте; глаза прикрыты, улыбка остаётся.
 */
const T = 'var(--c-text)';
const A = 'var(--c-accent)';

const f = (n: number) => Math.round(n * 100) / 100;

/** dx — сдвиг макушки вбок (покачивание): голова целиком, плечи наполовину, низ на месте */
function bodyPath(k: number, dx = 0): string {
  const top = 16 + 9 * k;
  const w = 1.5 * k;
  const h = dx / 2;
  return (
    `M43 128 C37 128 36 122 37 112 L${f(40 - w + h)} ${f(42 + 6 * k)} C${f(41 - w + dx)} ${f(25 + 8 * k)} ${f(49 - w + dx)} ${f(top)} ${f(60 + dx)} ${f(top)} ` +
    `C${f(71 + w + dx)} ${f(top)} ${f(79 + w + dx)} ${f(25 + 8 * k)} ${f(80 + w + h)} ${f(42 + 6 * k)} L83 112 C84 122 83 128 77 128 Z`
  );
}

/** Глаза: открытые → опущенные → закрытые по мере поклона */
function eyes(k: number, night: boolean): string {
  if (k > 0.6) {
    return (
      `<path d="M50.1 36 Q53 37.6 55.9 36" fill="none" stroke="${T}" stroke-width="1.8" stroke-linecap="round"/>` +
      `<path d="M64.1 36 Q67 37.6 69.9 36" fill="none" stroke="${T}" stroke-width="1.8" stroke-linecap="round"/>`
    );
  }
  const y = f(36 + Math.min(1.4, k * 4));
  const ry = night && k < 0.2 ? 1.4 : 2.6;
  return (
    `<path d="M50.5 ${y} L55.5 ${y} A2.5 ${ry} 0 0 1 50.5 ${y} Z" fill="${T}"/>` +
    `<path d="M64.5 ${y} L69.5 ${y} A2.5 ${ry} 0 0 1 64.5 ${y} Z" fill="${T}"/>`
  );
}

export type Gesture = 'bow' | 'shake';

export function gestureSvg(kind: Gesture, k: number, night: boolean): string {
  const shift = kind === 'shake' ? 2.2 * k : 0;
  k = kind === 'bow' ? k : 0;
  const d = bodyPath(k, shift);
  const nightEyesY = night && k < 0.2 ? 0.4 : 0;
  const closed = k > 0.6 || kind === 'shake';
  const mouth =
    k > 0.7
      ? `<path d="M58.2 53.4 L61.8 53.4" stroke="${T}" stroke-width="1.8" stroke-linecap="round"/>`
      : `<path d="M57.2 53 Q60 54.8 62.8 53" fill="none" stroke="${T}" stroke-width="1.8" stroke-linecap="round"/>`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 140" class="stevens stevens--${kind}" aria-hidden="true" focusable="false">` +
    `<path d="${d}" fill="var(--c-surface)"/><clipPath id="stv-bow-clip0"><path d="${d}"/></clipPath>` +
    `<g clip-path="url(#stv-bow-clip0)"><ellipse cx="97" cy="84" rx="24" ry="90" fill="var(--c-mascot-shade)"/></g>` +
    `<path d="${d}" fill="none" stroke="${T}" stroke-width="2.4" stroke-linejoin="round"/>` +
    `<g transform="translate(${f(shift)} ${f(10 * k)})">` +
    `<path d="M50 31.6 Q53 30.2 56 31.6" fill="none" stroke="${T}" stroke-width="1.5" stroke-linecap="round"/>` +
    `<path d="M64 31.2 Q67 30.2 70 31.6" fill="none" stroke="${T}" stroke-width="1.5" stroke-linecap="round"/>` +
    `<g transform="translate(0 ${nightEyesY})">${eyes(closed ? 1 : k, night)}</g>` +
    `<path d="M47.4 43 L58.6 43 Q58.6 48.2 53 48.2 Q47.4 48.2 47.4 43 Z" fill="var(--c-mascot-lens)" stroke="${T}" stroke-width="1.5" stroke-linejoin="round"/>` +
    `<path d="M61.4 43 L72.6 43 Q72.6 48.2 67 48.2 Q61.4 48.2 61.4 43 Z" fill="var(--c-mascot-lens)" stroke="${T}" stroke-width="1.5" stroke-linejoin="round"/>` +
    `<path d="M58.6 43.4 Q60 41.4 61.4 43.4" fill="none" stroke="${T}" stroke-width="1.5"/>` +
    `<path d="M47.4 43.3 L42 41 M72.6 43.3 L78 41" stroke="${T}" stroke-width="1.5" stroke-linecap="round"/>` +
    mouth +
    `</g><g transform="translate(0 ${f(7 * k)})">` +
    `<path d="M60 76 L54.24 72.688 Q53.14 76 54.24 79.312 Z M60 76 L65.76 72.688 Q66.86 76 65.76 79.312 Z" fill="${A}" stroke="${A}" stroke-width="1.1" stroke-linejoin="round"/>` +
    `<ellipse cx="60" cy="76" rx="1.5" ry="1.8" fill="${A}"/></g></svg>`
  );
}

/** Куда сдвигается макушка (единицы viewBox) — колпак едет вместе с ней */
export const capShift = (kind: Gesture, k: number) => (kind === 'bow' ? { x: 0, y: 9 * k } : { x: 2.2 * k, y: 0 });

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

/** Доля движения во времени: плавно вниз, держит, плавно вверх */
export function gestureAt(ms: number, plan: { down: number; hold: number; up: number; depth: number }): number | null {
  const { down, hold, up, depth } = plan;
  if (ms < down) return depth * ease(ms / down);
  if (ms < down + hold) return depth;
  if (ms < down + hold + up) return depth * (1 - ease((ms - down - hold) / up));
  return null;
}

/** Покачивание: два мягких «туда-обратно», размах нарастает и гаснет */
export function shakeAt(ms: number, plan: { duration: number; cycles: number }): number | null {
  if (ms >= plan.duration) return null;
  const t = ms / plan.duration;
  return Math.sin(2 * Math.PI * plan.cycles * t) * Math.sin(Math.PI * t);
}
