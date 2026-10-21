/**
 * Типы API Stevens — по контракту фронт ↔ бэк v1.2 (docs/reference/contract_v1.2.pdf)
 * Авторизация адаптирована к app/routers/auth.py по указанию владельца.
 * При расхождениях приоритет у существующего backend; см. docs/backend-integration.md.
 * Для проверки ответов в рантайме по этим типам строится схема (zod), см. docs/03-behavior.md.
 */

// ── Общие ─────────────────────────────────────────────

/** "YYYY-MM-DD", местная дата пользователя */
export type LocalDate = string;
/** "HH:MM", 24 часа, с ведущим нулём */
export type LocalTime = string;
/** ISO 8601 со смещением: "2026-10-18T14:05:00+03:00" */
export type IsoMoment = string;

// ── Запрос POST /api/chat ─────────────────────────────

export type MessageSource = "voice" | "text" | "button";

export interface ChatRequest {
  /** UUID, создаёт фронт; новый — при «Новом диалоге», входе, выходе, восстановлении ленты */
  conversation_id: string;
  /** До 300 символов. Для кнопки — send.text или label */
  text: string;
  source: MessageSource;
  /** Только для кнопки-действия */
  action: Action | null;
  client_time: IsoMoment;
  /** IANA, например "Europe/Moscow" — Intl.DateTimeFormat().resolvedOptions().timeZone */
  timezone: string;
}

// ── Ответ POST /api/chat ──────────────────────────────

export type ResponseKind =
  | "created"
  | "list"
  | "found"
  | "clarify"
  | "confirm"
  | "conflict"
  | "cancelled"
  | "not_understood"
  | "off_topic"
  | "help"
  | "thanks"
  | "error"
  // резерв под допы Д1–Д3:
  | "updated"
  | "deleted"
  | "completed";

export interface ChatResponse {
  message_id: string;
  /** Незнакомый kind не ошибка: показываем по общим полям */
  kind: ResponseKind | (string & {});
  text: string;
  /** Для озвучки (доп Д12). null — озвучивать text */
  speech: string | null;
  records: RecordItem[];
  /** Только у пустого list: ближайшая будущая запись */
  nearest: RecordItem | null;
  /** list — число записей периода; found — всего совпадений (records может быть меньше) */
  total: number | null;
  /** Ассистент задал вопрос. Отвечать необязательно */
  awaiting_reply: boolean;
  buttons: Button[];
}

export type RecordType = "task" | "reminder" | "meeting";
export type DateKind = "exact" | "deadline" | "none";
export type RecordMark = "new" | "draft" | "conflict";
export type HighlightField = "date" | "time" | "text";

export interface RecordItem {
  /** null — ещё не сохранена (черновик в confirm / conflict) */
  id: number | null;
  /** null — тип неизвестен (записи из CSV): карточка без значка и слова типа */
  type: RecordType | null;
  text: string;
  date: LocalDate | null;
  time: LocalTime | null;
  date_kind: DateKind;
  status: "open" | "done" | null;
  created_at: IsoMoment | null;
  marks: RecordMark[];
  highlight: HighlightField | null;
  /** резерв, Д7 */
  remind_at?: IsoMoment | null;
}

export interface Button {
  label: string;
  /** Ровно одно из двух */
  send: { text: string } | { action: Action };
  /** По умолчанию primary */
  style?: "primary" | "secondary";
}

export type ActionId =
  | "cancel"
  | "confirm_yes"
  | "confirm_no"
  | "keep_both"
  | "change_new_time"
  | "move_existing"
  // резерв:
  | "undo"
  | "complete"
  | "delete";

export interface Action {
  id: ActionId | (string & {});
  record_id?: number;
}

// ── GET /api/health ───────────────────────────────────

export interface HealthResponse {
  status: "ok";
}

// ── Реализованная авторизация FastAPI ──────────────────
// POST /api/chat и GET /api/auth/me требуют Authorization: Bearer <token>.
// Сервер не поддерживает X-Client-Id, /logout, /sandbox/reset. В mock режиме
// демонстрация работает локально; в real режиме обязательна авторизация.

export interface AuthRequest {
  email: string;
  password: string;
  name?: string;
}

export interface User {
  id: number;
  email: string;
  name: string;
}

/** POST /api/auth/register и POST /api/auth/login → 200 */
export interface AuthResponse {
  token: string;
  user: User;
  expires_at: string;
}

/** FastAPI: 401/409 — строка detail; 422 — массив ошибок валидации. */
export interface AuthError {
  detail: string | { loc: (string | number)[]; msg: string; type: string }[];
}

/** GET /api/auth/me → 200 User без обёртки | 401 */
export interface MeResponse {
  id: number;
  email: string;
  name: string;
}

// Выход удаляет локальный токен. Серверная сессия остаётся до истечения срока.
