/** Тайминги персонажа */
export const READ_MS = 1200;        // «читает поле»
export const WRITE_MS = 1600;       // письмо: кадры 1 → 2 → 3 → 2 дважды
export const FRAME_MS = 200;        // кадр письма
export const READ_WRITE_FADE_MS = 150;
export const STATE_FADE_MS = 300;
export const TYPING_PAUSE_MS = 1500; // «пишет», пока последнее нажатие было меньше 1,5 с назад
export const FLASH_MS = 3000;        // «готово» и «не понял»
export const WRITE_FRAMES = ['write-1', 'write-2', 'write-3', 'write-2'] as const;

/** Приветственный поклон (вход, открытие чата, «Новый диалог»): глубокий, плавно вниз, держит, плавно вверх (≈2,2 с) */
export const GREET = { down: 700, hold: 700, up: 800, depth: 1.6 };
/** Поклон по клику — чуть короче и мельче (≈1,6 с) */
export const BOW = { down: 550, hold: 450, up: 600, depth: 1.2 };
/** С 4-го клика подряд — мягко качает головой, глаза прикрыты, улыбается (≈1 с) */
export const SHAKE = { duration: 1000, cycles: 2 };
export const BOWS_BEFORE_SHAKE = 3;
/** Без кликов столько — счёт кликов сначала, снова поклон */
export const CLICK_RESET_MS = 10_000;
export const CLICK_COOLDOWN_MS = 1200;
/** «Думает» дольше 1,5 с — по очереди точки, карандаш, сверяется, по 2 с */
export const THINK_LONG_MS = 1500;
export const THINK_STEP_MS = 2000;
export const THINK_FRAMES = ['think', 'think-tap', 'think-read'] as const;
/** Ночь — колпак: с 23:00 до 6:00 по часам устройства */
export const NIGHT_FROM = 23;
export const NIGHT_TO = 6;
