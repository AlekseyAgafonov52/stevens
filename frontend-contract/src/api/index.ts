import { ZodError } from "zod";
import { apiUrl, featuresHeader } from "../config/features";
import { T } from "../content/texts";
import type {
  AuthRequest,
  AuthResponse,
  ChatRequest,
  ChatResponse,
  RecordItem,
  RecordPatch,
  User,
} from "./types";
import {
  authSchema,
  describeIssue,
  healthSchema,
  parseChatResponse,
  parseRecord,
  recordsSchema,
  userSchema,
} from "./schema";
import { ApiError } from "./errors";
export { ApiError } from "./errors";

const base = apiUrl.replace(/\/+$/, "");

type Method = "GET" | "POST" | "PATCH" | "DELETE";

/**
 * Один запрос к бэку по общим правилам контракта (раздел 3): JSON, таймаут
 * 25 секунд, всё, что не 2xx, — ошибка с кнопкой «Повторить».
 */
async function request(
  method: Method,
  path: string,
  options: {
    token?: string | null;
    body?: unknown;
    headers?: Record<string, string>;
    timeout?: number;
    /** Текст ошибки для 404 и 422 — свой у каждого запроса */
    messages?: Partial<Record<404 | 422, string>>;
  } = {},
): Promise<unknown> {
  const {
    token,
    body,
    headers = {},
    timeout = 25_000,
    messages = {},
  } = options;
  const label = `${method} ${path.split("?")[0]}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(base + path, {
      method,
      signal: controller.signal,
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (response.status === 204) return null;
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = `${label} → ${response.status}`;
      if (response.status === 401 || (response.status === 403 && token))
        throw new ApiError("unauthorized", T.auth_session_expired, detail);
      if (response.status === 404)
        throw new ApiError("not_found", messages[404] ?? T.err_server, detail);
      if (response.status === 422)
        throw new ApiError(
          "validation",
          messages[422] ?? T.request_invalid,
          detail,
        );
      throw new ApiError(
        response.status < 500 ? "validation" : "server",
        T.err_server,
        detail,
      );
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw new ApiError("timeout", T.err_timeout, `${label}: 25 с`);
    throw new ApiError("network", T.err_network, label);
  } finally {
    clearTimeout(timer);
  }
}

/** Разбор ответа: не по контракту — ошибка с указанием, какое поле не сошлось */
function parse<R>(label: string, parser: () => R): R {
  try {
    return parser();
  } catch (error) {
    throw new ApiError(
      "contract",
      T.err_contract,
      `${label}: ${error instanceof ZodError ? describeIssue(error) : "формат ответа"}`,
    );
  }
}

// ── POST /api/chat (разделы 4–7, 15.2) ─────────────────

export async function chat(
  payload: ChatRequest,
  token: string | null,
): Promise<ChatResponse> {
  const flags = featuresHeader();
  const data = await request("POST", "/api/chat", {
    token,
    body: payload,
    headers: flags ? { "X-Stevens-Features": flags } : {},
  });
  return parse("POST /api/chat", () => parseChatResponse(data));
}

// ── REST для календаря и правки (15.5) ────────────────

const recordMessages = { 404: T.err_record_missing, 422: T.err_record_fields };

export async function getRecords(
  from: string,
  to: string,
  token: string | null,
): Promise<RecordItem[]> {
  const data = await request("GET", `/api/records?from=${from}&to=${to}`, {
    token,
    messages: { 422: T.request_invalid },
  });
  return parse("GET /api/records", () => recordsSchema.parse(data).records);
}

export async function patchRecord(
  id: number,
  patch: RecordPatch,
  token: string | null,
): Promise<RecordItem> {
  const data = await request("PATCH", `/api/records/${id}`, {
    token,
    body: patch,
    messages: recordMessages,
  });
  return parse("PATCH /api/records", () => parseRecord(data));
}

export async function deleteRecord(
  id: number,
  token: string | null,
): Promise<void> {
  await request("DELETE", `/api/records/${id}`, {
    token,
    messages: recordMessages,
  });
}

export async function restoreRecord(
  id: number,
  token: string | null,
): Promise<RecordItem> {
  const data = await request("POST", `/api/records/${id}/restore`, {
    token,
    messages: recordMessages,
  });
  return parse("POST /api/records/restore", () => parseRecord(data));
}

// ── GET /api/health (раздел 2) ────────────────────────

export async function health(): Promise<void> {
  const data = await request("GET", "/api/health", { timeout: 60_000 });
  parse("GET /api/health", () => healthSchema.parse(data));
}

// ── Вход: как в текущем бэке, не по разделу 14 ────────

export async function authenticate(
  payload: AuthRequest,
  register: boolean,
): Promise<AuthResponse> {
  try {
    const data = await request(
      "POST",
      `/api/auth/${register ? "register" : "login"}`,
      { body: payload },
    );
    return parse("POST /api/auth", () => authSchema.parse(data));
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unauthorized")
      throw new ApiError("validation", T.auth_err_credentials, error.detail);
    if (error instanceof ApiError && error.detail.endsWith("409"))
      throw new ApiError("validation", T.auth_err_login_taken, error.detail);
    throw error;
  }
}

export async function me(token: string): Promise<User> {
  const data = await request("GET", "/api/auth/me", { token });
  return parse("GET /api/auth/me", () => userSchema.parse(data));
}
