/**
 * Флаги функций (Р-149): один код, два набора — «минимальный» и «полный».
 * Набор задаётся при сборке: `vite build --mode minimal` / `vite build --mode full`
 * (файлы .env.minimal и .env.full в корне, примеры — внизу).
 * Выключенная функция не видна совсем, а её место в интерфейсе остаётся пустым.
 */
const on = (name: string): boolean =>
  import.meta.env[`VITE_FEATURE_${name}`] === "true";

export const features = {
  /** Экран входа и аккаунты (Р-179). Выключено — приложение сразу открывается в песочнице */
  auth: on("AUTH"),

  // ── Допы: место зарезервировано, описание придёт позже ──
  /** Д1 Изменение и перенос */
  d1_update: on("D1_UPDATE"),
  /** Д2 Удаление */
  d2_delete: on("D2_DELETE"),
  /** Д3 Отметка выполненной */
  d3_complete: on("D3_COMPLETE"),
  /** Д5 Повторяющиеся */
  d5_recurring: on("D5_RECURRING"),
  /** Д6 Календарная панель — справа на широком экране, на телефоне по кнопке в шапке (Р-87) */
  d6_calendar: on("D6_CALENDAR"),
  /** Д7 Пуш-уведомления */
  d7_push: on("D7_PUSH"),
  /** Д10 Отмена только что созданного */
  d10_undo: on("D10_UNDO"),
  /** Д12 Озвучка ответов */
  d12_speech: on("D12_SPEECH"),
  /** Д13 Автослушание после уточнения */
  d13_autolisten: on("D13_AUTOLISTEN"),
  /** Д14 Персонаж Stevens */
  d14_mascot: on("D14_MASCOT"),
} as const;

/** Откуда берём ответы: 'mock' — локальные заглушки (src/api/mocks.json), 'real' — бэк по VITE_API_URL */
export const apiMode: "mock" | "real" =
  import.meta.env.VITE_API_MODE === "mock" ? "mock" : "real";
export const apiUrl: string = import.meta.env.VITE_API_URL ?? "";

/*
.env.development  — разработка с существующим backend
  VITE_API_MODE=real
  VITE_API_URL=http://localhost:8000
  VITE_FEATURE_AUTH=true

.env.minimal      — только демонстрация, без реального backend
  VITE_API_MODE=mock
  VITE_FEATURE_AUTH=false

.env.production / .env.full — реальный API; адрес задаётся до сборки
  VITE_API_MODE=real
  VITE_API_URL=http://localhost:8000
  VITE_FEATURE_AUTH=true

Docker always builds in real mode with an explicit public VITE_API_URL.
Only pnpm dev:mock / build:minimal explicitly opt into demonstration responses.
*/
