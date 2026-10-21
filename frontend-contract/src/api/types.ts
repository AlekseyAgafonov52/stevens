/**
 * Типы API Stevens — строго по контракту фронт ↔ бэк v1.4 с допами
 * (docs/reference/contract_v1.4_s_dopami.pdf).
 * Единственное отступление — вход и регистрация: они как в текущем бэке
 * (email, имя, пароль), а не по логину из раздела 14. Песочницы нет.
 */

// ── Общие ─────────────────────────────────────────────

/** "YYYY-MM-DD", местная дата пользователя */
export type LocalDate = string;
/** "HH:MM", 24 часа, с ведущим нулём */
export type LocalTime = string;
/** ISO 8601 со смещением: "2026-10-18T14:05:00+03:00" */
export type IsoMoment = string;

// ── Запрос POST /api/chat (раздел 4) ──────────────────

export type MessageSource = "voice" | "text" | "button";

export interface ChatRequest {
  /** UUID, создаёт фронт */
  conversation_id: string;
  /** До 300 символов. Для кнопки — send.text или label */
  text: string;
  source: MessageSource;
  /** Только для кнопки-действия: тогда бэк ориентируется на action, а не на text */
  action: Action | null;
  client_time: IsoMoment;
  /** IANA, например "Europe/Moscow" */
  timezone: string;
}

// ── Ответ POST /api/chat (разделы 5, 7, 15.3) ─────────

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
  // допы (15.3):
  | "deleted"
  | "completed";

export interface ChatResponse {
  message_id: string;
  /** Незнакомый kind не ошибка: показываем по общим полям (Р-38) */
  kind: ResponseKind | (string & {});
  text: string;
  /** Для озвучки (Д12). null — озвучивать text */
  speech: string | null;
  records: RecordItem[];
  /** Только у пустого list: ближайшая будущая запись */
  nearest: RecordItem | null;
  /** list — число записей периода; found — всего совпадений */
  total: number | null;
  /** Ассистент задал вопрос. Отвечать необязательно */
  awaiting_reply: boolean;
  buttons: Button[];
}

export type RecordType = "task" | "reminder" | "meeting";
export type DateKind = "exact" | "deadline" | "none";
/** deleted — доп Д2/Д10 (15.3) */
export type RecordMark = "new" | "draft" | "conflict" | "deleted";
export type HighlightField = "date" | "time" | "text";
export type RecordStatus = "open" | "done";

export interface RecordItem {
  /** null — ещё не сохранена (черновик в confirm / conflict) */
  id: number | null;
  /** null — тип неизвестен (записи из CSV) */
  type: RecordType | null;
  text: string;
  date: LocalDate | null;
  time: LocalTime | null;
  date_kind: DateKind;
  status: RecordStatus | null;
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
  // допы (15.3):
  | "undo"
  | "complete"
  | "delete"
  | "restore";

export interface Action {
  id: ActionId | (string & {});
  record_id?: number;
}

// ── GET /api/health (раздел 2) ────────────────────────

export interface HealthResponse {
  status: "ok";
}

// ── REST для календаря и правки (15.5) ────────────────

/** GET /api/records?from=&to= → 200 */
export interface RecordsResponse {
  records: RecordItem[];
}
/** PATCH /api/records/{id}, POST /api/records/{id}/restore → 200 */
export interface RecordResponse {
  record: RecordItem;
}
/** Тело PATCH: любые из полей, меняются только присланные */
export interface RecordPatch {
  text?: string;
  date?: LocalDate | null;
  time?: LocalTime | null;
  status?: RecordStatus;
}

// ── Вход: как в текущем бэке (app/routers/auth.py) ─────

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
