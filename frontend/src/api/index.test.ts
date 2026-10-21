import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("../config/features", () => ({
  apiMode: "real",
  apiUrl: "http://localhost:8000",
}));
import { authenticate, chat, health, me } from "./index";
import type { ChatRequest } from "./types";

const user = { id: 7, email: "alex@example.com", name: "Алексей" };
const payload: ChatRequest = {
  conversation_id: "test",
  text: "Мои планы",
  source: "text",
  action: null,
  client_time: "2026-10-21T10:00:00+03:00",
  timezone: "Europe/Moscow",
};
afterEach(() => vi.unstubAllGlobals());
describe("adapter to the actual FastAPI routes", () => {
  it.each(["text", "voice"] as const)(
    "posts a %s message with the complete backend contract and preserves records",
    async (source) => {
      const response = {
        message_id: "m-created",
        kind: "created",
        text: "Записал задачу",
        speech: null,
        records: [
          {
            id: 12,
            type: "task",
            text: "Проверить интеграцию",
            date: "2026-10-22",
            time: "10:00",
            date_kind: "exact",
            status: "open",
            created_at: null,
            marks: ["new"],
            highlight: null,
          },
        ],
        nearest: null,
        total: null,
        awaiting_reply: false,
        buttons: [],
      };
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(response)));
      vi.stubGlobal("fetch", fetch);
      const request = { ...payload, source };
      expect(await chat(request, "secret")).toEqual(response);
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch.mock.calls[0][0]).toBe("http://localhost:8000/api/chat");
      const options = fetch.mock.calls[0][1];
      expect(options.method).toBe("POST");
      expect(options.headers).toMatchObject({
        Authorization: "Bearer secret",
        "Content-Type": "application/json",
      });
      expect(JSON.parse(options.body)).toEqual(request);
    },
  );
  it("registers with email and name, and reads the actual auth response", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          token: "secret",
          user,
          expires_at: "2026-10-28T10:00:00Z",
        }),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await authenticate(
      { email: user.email, name: user.name, password: "password" },
      true,
    );
    expect(result.user).toEqual(user);
    expect(fetch.mock.calls[0][0]).toBe(
      "http://localhost:8000/api/auth/register",
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      email: user.email,
      name: user.name,
      password: "password",
    });
  });
  it("accepts /me without a user wrapper and sends Bearer", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(user)));
    vi.stubGlobal("fetch", fetch);
    expect(await me("secret")).toEqual(user);
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer secret");
  });
  it("checks GET / rather than calling a missing /api/health", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    await health();
    expect(fetch.mock.calls[0][0]).toBe("http://localhost:8000/");
  });
  it("does not send a fake guest token or unsupported actions", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(chat(payload, null)).rejects.toMatchObject({
      kind: "unauthorized",
    });
    await expect(
      chat({ ...payload, action: { id: "cancel" } }, "secret"),
    ).rejects.toMatchObject({ kind: "validation" });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("keeps FastAPI detail errors and identifies an expired token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Email уже занят" }), {
          status: 409,
        }),
      ),
    );
    await expect(
      authenticate(
        { email: user.email, password: "password", name: user.name },
        true,
      ),
    ).rejects.toThrow("Email уже занят");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await expect(chat(payload, "expired")).rejects.toMatchObject({
      kind: "unauthorized",
    });
  });
});
