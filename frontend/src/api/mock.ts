import data from "./mocks.json";
import type {
  AuthRequest,
  AuthResponse,
  ChatRequest,
  ChatResponse,
  User,
} from "./types";
import { parseChatResponse } from "./schema";
import { MOCK_TIME } from "../lib/clock";
import { T } from "../content/texts";

export class ApiError extends Error {
  constructor(
    public kind:
      "network" | "timeout" | "server" | "unauthorized" | "validation",
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export const pause = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
export async function mockChat(request: ChatRequest): Promise<ChatResponse> {
  const text = request.text.trim().toLowerCase();
  if (text === "#network") {
    await pause(700);
    throw new ApiError("network", T.err_network);
  }
  if (text === "#timeout") {
    await pause(25_000);
    throw new ApiError("timeout", T.err_timeout);
  }
  if (text === "#401") {
    await pause(700);
    throw new ApiError("unauthorized", T.auth_session_expired);
  }
  if (text === "#500") {
    await pause(700);
    throw new ApiError("server", T.err_server);
  }
  await pause(text === "#slow" ? 10_000 : text === "#wake" ? 8_000 : 700);
  const scenarios = data.scenarios as Array<{
    note?: string;
    match: { text?: string[]; action?: string[] };
    response: unknown;
  }>;
  const matchText =
    text === "#slow" || text === "#wake" ? "что у меня сегодня?" : text;
  const match = scenarios.find((item) =>
    request.action
      ? item.match.action?.includes(request.action.id)
      : item.match.text?.includes(matchText),
  );
  const fallback =
    scenarios.find((item) => item.note === "not_understood") ??
    scenarios.find((item) => item.match.text?.includes("сделай что-нибудь"));
  const result = parseChatResponse(match?.response ?? fallback?.response);
  return { ...result, message_id: crypto.randomUUID() };
}

const mockUser = (email: string, name?: string): User => ({
  id: 1,
  email,
  name: name || email.split("@")[0],
});
export async function mockAuth(
  request: AuthRequest,
  register: boolean,
): Promise<AuthResponse> {
  await pause(700);
  if (register && request.email.split("@")[0] === "taken")
    throw new ApiError("validation", T.auth_err_login_taken);
  if (!register && request.password === "wrong")
    throw new ApiError("validation", T.auth_err_credentials);
  return {
    token: "mock-token",
    user: mockUser(request.email, request.name),
    expires_at: MOCK_TIME,
  };
}
