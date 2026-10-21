import { apiMode, apiUrl } from "../config/features";
import { T } from "../content/texts";
import type {
  AuthRequest,
  AuthResponse,
  ChatRequest,
  ChatResponse,
  User,
} from "./types";
import { authSchema, parseChatResponse, userSchema } from "./schema";
import { ApiError, mockAuth, mockChat } from "./mock";
export { ApiError } from "./mock";

const base = apiUrl.replace(/\/+$/, "");
if (apiMode === "real" && !/^https?:\/\//.test(base)) {
  console.warn("VITE_API_URL must be an absolute HTTP(S) URL in real mode.");
}
async function request(
  path: string,
  token?: string,
  body?: unknown,
  timeout = 25_000,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(base + path, {
      method: body === undefined ? "GET" : "POST",
      signal: controller.signal,
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        typeof data === "object" && data !== null && "detail" in data
          ? data.detail
          : null;
      const text =
        typeof detail === "string"
          ? detail
          : response.status === 422
            ? T.request_invalid
            : T.err_server;
      if (response.status === 401 || (response.status === 403 && token))
        throw new ApiError("unauthorized", T.auth_session_expired);
      throw new ApiError(response.status < 500 ? "validation" : "server", text);
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw new ApiError("timeout", T.err_timeout);
    throw new ApiError("network", T.err_network);
  } finally {
    clearTimeout(timer);
  }
}

export async function chat(
  payload: ChatRequest,
  token: string | null,
): Promise<ChatResponse> {
  if (apiMode === "mock") return mockChat(payload);
  if (!token) throw new ApiError("unauthorized", T.auth_required);
  // The current server ignores action; never turn a click into an unrelated LLM command.
  if (payload.action) throw new ApiError("validation", T.action_unavailable);
  try {
    return parseChatResponse(await request("/api/chat", token, payload));
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("server", T.network_invalid);
  }
}

export async function authenticate(
  payload: AuthRequest,
  register: boolean,
): Promise<AuthResponse> {
  if (apiMode === "mock") return mockAuth(payload, register);
  try {
    const data = await request(
      `/api/auth/${register ? "register" : "login"}`,
      undefined,
      payload,
    );
    return authSchema.parse(data);
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unauthorized")
      throw new ApiError("validation", T.auth_err_credentials);
    if (error instanceof ApiError) throw error;
    throw new ApiError("server", T.network_invalid);
  }
}

export async function me(token: string): Promise<User | null> {
  if (apiMode === "mock") return null;
  const data = await request("/api/auth/me", token);
  const parsed = userSchema.safeParse(data);
  if (!parsed.success) throw new ApiError("server", T.network_invalid);
  return parsed.data;
}

// Existing backend has GET /, not /api/health. This only verifies HTTP reachability.
export async function health(): Promise<void> {
  if (apiMode === "mock") return;
  await request("/", undefined, undefined, 60_000);
}
