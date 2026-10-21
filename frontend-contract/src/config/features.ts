/**
 * Флаги функций (Р-149): один код, два набора — «минимальный» и «полный».
 * Набор задаётся при сборке: `vite build --mode minimal` / `vite build --mode full`
 * (файлы .env.minimal и .env.full в корне, примеры — внизу).
 * Выключенная функция не рисуется и места не занимает: интерфейс в точности как без неё.
 * Флаги читают только точки расширения (docs/09-extensions.md) и модуль src/api/ (заголовок X-Stevens-Features, заглушки).
 */
const on = (name: string): boolean => import.meta.env[`VITE_FEATURE_${name}`] === 'true';

export const features = {
  /** Экран входа и аккаунты — часть первого варианта, не доп. Выключено — приложение сразу открывается в песочнице */
  auth: on('AUTH'),

  // ── Допы: docs/07-extras.md и docs/08-mascot.md; как встраивать — docs/09-extensions.md.
  //    Все флаги допов выключены = в точности первый вариант. ──
  /** Д2 Удаление */
  d2_delete: on('D2_DELETE'),
  /** Д3 Отметка выполненной */
  d3_complete: on('D3_COMPLETE'),
  /** Д6 Календарная панель — справа на широком экране, на телефоне по кнопке в шапке */
  d6_calendar: on('D6_CALENDAR'),
  /** Д10 «Исправить» (добавляет фронт) и «Отменить» (присылает бэк) у созданной записи */
  d10_undo: on('D10_UNDO'),
  /** Д12 Озвучка ответов */
  d12_speech: on('D12_SPEECH'),
  /** Д13 Автослушание после уточнения */
  d13_autolisten: on('D13_AUTOLISTEN'),
  /** Д14 Персонаж Stevens — docs/08-mascot.md; подключает src/styles/mascot.css */
  d14_mascot: on('D14_MASCOT'),
} as const;

/** Откуда берём ответы: 'mock' — локальные заглушки (src/api/mocks.json), 'real' — бэк по VITE_API_URL */
export const apiMode: 'mock' | 'real' = import.meta.env.VITE_API_MODE === 'real' ? 'real' : 'mock';
export const apiUrl: string = import.meta.env.VITE_API_URL ?? '';

/*
.env.development  — разработка
  VITE_API_MODE=mock
  VITE_FEATURE_AUTH=true

.env.minimal      — запасной деплой: первый вариант без входа, все допы выключены (как в первом пакете)
  VITE_API_MODE=real
  VITE_API_URL=https://<бэк>
  VITE_FEATURE_AUTH=false

.env.full         — ссылка для жюри: первый вариант + вход + допы, прошедшие проверку
  VITE_API_MODE=real
  VITE_API_URL=https://<бэк>
  VITE_FEATURE_AUTH=true
  # допы включаются по мере готовности и проверки:
  # VITE_FEATURE_D2_DELETE=true
  # VITE_FEATURE_D10_UNDO=true
  # VITE_FEATURE_D3_COMPLETE=true
  # VITE_FEATURE_D6_CALENDAR=true
  # VITE_FEATURE_D12_SPEECH=true
  # VITE_FEATURE_D13_AUTOLISTEN=true
  # VITE_FEATURE_D14_MASCOT=true

Эталон «первый вариант» для снимков (docs/09-extensions.md, раздел 3) — .env.development: auth включён, все допы выключены.
*/
