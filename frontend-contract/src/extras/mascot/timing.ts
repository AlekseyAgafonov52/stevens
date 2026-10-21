/** Тайминги персонажа — 08-mascot.md, раздел 4 (AGENTS.md, правило 15). */
export const READ_MS = 1200;        // «читает поле»
export const WRITE_MS = 1600;       // письмо: кадры 1 → 2 → 3 → 2 дважды
export const FRAME_MS = 200;        // кадр письма
export const READ_WRITE_FADE_MS = 150;
export const STATE_FADE_MS = 300;
export const TYPING_PAUSE_MS = 1500; // «пишет», пока последнее нажатие было меньше 1,5 с назад
export const FLASH_MS = 3000;        // «готово» и «не понял»
export const WRITE_FRAMES = ['write-1', 'write-2', 'write-3', 'write-2'] as const;

/** Поклон: покой → середина → поклон (держит) → середина → покой, всего ≈1,2 с */
export const BOW_STEPS = [
  { frame: 'bow-1', at: 0, fade: 180 },
  { frame: 'bow-2', at: 180, fade: 180 },
  { frame: 'bow-1', at: 780, fade: 180 },
  { frame: 'rest', at: 960, fade: 240 },
] as const;
/** Кивок по клику: только середина поклона */
export const NOD_STEPS = [
  { frame: 'bow-1', at: 0, fade: 160 },
  { frame: 'rest', at: 460, fade: 200 },
] as const;
export const GESTURE_MS = 1200;
export const CLICK_COOLDOWN_MS = 2000;
/** «Думает» дольше 1,5 с — по очереди точки, карандаш, сверяется, по 2 с */
export const THINK_LONG_MS = 1500;
export const THINK_STEP_MS = 2000;
export const THINK_FRAMES = ['think', 'think-tap', 'think-read'] as const;
/** Ночь — колпак: с 23:00 до 6:00 по часам устройства */
export const NIGHT_FROM = 23;
export const NIGHT_TO = 6;
