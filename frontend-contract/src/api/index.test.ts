import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("../config/features", () => ({
  apiUrl: "http://localhost:8000",
  featuresHeader: () => "d2,d3,d10",
}));
import {
  authenticate,
  chat,
  deleteRecord,
  getRecords,
  health,
  me,
  patchRecord,
  restoreRecord,
} from "./index";
import type { ChatRequest, RecordItem } from "./types";

const user = { id: 7, email: "alex@example.com", name: "Алексей" };
const payload: ChatRequest = {
  conversation_id: "test",
  text: "Мои планы",
  source: "text",
  action: null,
  client_time: "2026-10-21T10:00:00+03:00",
  timezone: "Europe/Moscow",
};
const record: RecordItem = {
  id: 1001,
  type: "reminder",
  text: "Позвонить Ивану",
  date: "2026-10-22",
  time: "10:00",
  date_kind: "exact",
  status: "open",
  created_at: "2026-10-21T10:00:05+03:00",
  marks: ["new"],
  highlight: null,
};
// Пример m-204 из раздела 15.7
const created = {
  message_id: "m-204",
  kind: "created",
  text: "Записал напоминание на завтра в 10:00: «Позвонить Ивану».",
  speech: "Напоминание — завтра в 10:00.",
  records: [record],
  nearest: null,
  total: null,
  awaiting_reply: false,
  buttons: [
    {
      label: "Отменить",
      send: { action: { id: "undo", record_id: 1001 } },
      style: "secondary",
    },
  ],
};
const ok = (body: unknown, status = 200) =>
  vi
    .fn()
    .mockResolvedValue(
      new Response(body === null ? null : JSON.stringify(body), { status }),
    );
afterEach(() => vi.unstubAllGlobals());

describe("POST /api/chat по контракту v1.4", () => {
  it.each(["text", "voice"] as const)(
    "шлёт %s-сообщение с Bearer и X-Stevens-Features",
    async (source) => {
      const fetch = ok(created);
      vi.stubGlobal("fetch", fetch);
      const request = { ...payload, source };
      expect(await chat(request, "secret")).toEqual(created);
      expect(fetch.mock.calls[0][0]).toBe("http://localhost:8000/api/chat");
      const options = fetch.mock.calls[0][1];
      expect(options.method).toBe("POST");
      expect(options.headers).toMatchObject({
        Authorization: "Bearer secret",
        "Content-Type": "application/json",
        "X-Stevens-Features": "d2,d3,d10",
      });
      expect(JSON.parse(options.body)).toEqual(request);
    },
  );
  it("отправляет нажатие кнопки-действия как есть: text = надпись, action", async () => {
    const fetch = ok({ ...created, kind: "deleted", buttons: [] });
    vi.stubGlobal("fetch", fetch);
    const request: ChatRequest = {
      ...payload,
      text: "Отменить",
      source: "button",
      action: { id: "undo", record_id: 1001 },
    };
    await chat(request, "secret");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(request);
  });
  it("ответ не по контракту — ошибка с указанием поля", async () => {
    vi.stubGlobal("fetch", ok({ ...created, awaiting_reply: undefined }));
    await expect(chat(payload, "secret")).rejects.toMatchObject({
      kind: "contract",
      detail: expect.stringContaining("awaiting_reply"),
    });
  });
  it("401 — сессия закончилась, 500 — сбой с технической подписью", async () => {
    vi.stubGlobal("fetch", ok({}, 401));
    await expect(chat(payload, "expired")).rejects.toMatchObject({
      kind: "unauthorized",
    });
    vi.stubGlobal("fetch", ok({}, 500));
    await expect(chat(payload, "secret")).rejects.toMatchObject({
      kind: "server",
      detail: "POST /api/chat → 500",
    });
  });
});

describe("REST 15.5", () => {
  it("GET /api/records с периодом", async () => {
    const fetch = ok({ records: [{ ...record, marks: [] }] });
    vi.stubGlobal("fetch", fetch);
    expect(await getRecords("2026-10-19", "2026-10-25", "secret")).toHaveLength(
      1,
    );
    expect(fetch.mock.calls[0][0]).toBe(
      "http://localhost:8000/api/records?from=2026-10-19&to=2026-10-25",
    );
    expect(fetch.mock.calls[0][1].method).toBe("GET");
  });
  it("PATCH шлёт только изменённые поля и читает {record}", async () => {
    const fetch = ok({ record: { ...record, status: "done", marks: [] } });
    vi.stubGlobal("fetch", fetch);
    const saved = await patchRecord(1001, { status: "done" }, "secret");
    expect(saved.status).toBe("done");
    expect(fetch.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      status: "done",
    });
  });
  it("DELETE ждёт 204, restore возвращает запись", async () => {
    const fetch = ok(null, 204);
    vi.stubGlobal("fetch", fetch);
    await deleteRecord(1001, "secret");
    expect(fetch.mock.calls[0][1].method).toBe("DELETE");
    vi.stubGlobal("fetch", ok({ record }));
    expect((await restoreRecord(1001, "secret")).id).toBe(1001);
  });
  it("404 — записи нет или она чужая, с технической подписью", async () => {
    vi.stubGlobal("fetch", ok({ detail: "Not Found" }, 404));
    await expect(
      patchRecord(5, { text: "Новый текст" }, "secret"),
    ).rejects.toMatchObject({
      kind: "not_found",
      message: "Записи нет или она чужая.",
      detail: "PATCH /api/records/5 → 404",
    });
  });
});

describe("служебное", () => {
  it("GET /api/health ждёт {status: ok}", async () => {
    const fetch = ok({ status: "ok" });
    vi.stubGlobal("fetch", fetch);
    await health();
    expect(fetch.mock.calls[0][0]).toBe("http://localhost:8000/api/health");
    vi.stubGlobal("fetch", ok({ detail: "Not Found" }, 404));
    await expect(health()).rejects.toMatchObject({ kind: "not_found" });
  });
  it("вход как в текущем бэке: email, имя, пароль; /me без обёртки", async () => {
    const fetch = ok({ token: "secret", user, expires_at: "2026-10-28" });
    vi.stubGlobal("fetch", fetch);
    const result = await authenticate(
      { email: user.email, name: user.name, password: "password" },
      true,
    );
    expect(result.user).toEqual(user);
    expect(fetch.mock.calls[0][0]).toBe(
      "http://localhost:8000/api/auth/register",
    );
    vi.stubGlobal("fetch", ok(user));
    expect(await me("secret")).toEqual(user);
  });
  it("занятый email и неверный пароль — понятные тексты", async () => {
    vi.stubGlobal("fetch", ok({ detail: "занят" }, 409));
    await expect(
      authenticate({ email: user.email, password: "password" }, true),
    ).rejects.toThrow("Этот email уже зарегистрирован.");
    vi.stubGlobal("fetch", ok({ detail: "нет" }, 401));
    await expect(
      authenticate({ email: user.email, password: "password" }, false),
    ).rejects.toThrow("Неверный email или пароль.");
  });
});
