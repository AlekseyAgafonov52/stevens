/** Тайминги персонажа — 08-mascot.md, раздел 4 (AGENTS.md, правило 15). */
export const READ_MS = 1200;        // «читает поле»
export const WRITE_MS = 1600;       // письмо: кадры 1 → 2 → 3 → 2 дважды
export const FRAME_MS = 200;        // кадр письма
export const READ_WRITE_FADE_MS = 150;
export const STATE_FADE_MS = 300;
export const TYPING_PAUSE_MS = 1500; // «пишет», пока последнее нажатие было меньше 1,5 с назад
export const FLASH_MS = 3000;        // «готово» и «не понял»
export const WRITE_FRAMES = ['write-1', 'write-2', 'write-3', 'write-2'] as const;
