import { describe, expect, it } from "vitest";
import { parseChatResponse } from "./schema";

const base = {
  message_id: "1",
  kind: "clarify",
  text: "Во сколько?",
  records: [],
  awaiting_reply: true,
  buttons: [],
};
describe("разбор ответа /api/chat по контракту", () => {
  it("ключ send со значением null считается отсутствующим (так пишет Pydantic)", () => {
    const result = parseChatResponse({
      ...base,
      buttons: [
        { label: "10:00", send: { text: "в 10:00", action: null } },
        {
          label: "Отменить",
          send: { text: null, action: { id: "cancel", record_id: null } },
          style: "secondary",
        },
      ],
    });
    expect(result.buttons[0].send).toEqual({ text: "в 10:00" });
    expect(result.buttons[1].send).toEqual({
      action: { id: "cancel", record_id: undefined },
    });
  });
  it("send без text и action или с обоими — не по контракту", () => {
    expect(() =>
      parseChatResponse({ ...base, buttons: [{ label: "?", send: {} }] }),
    ).toThrow();
    expect(() =>
      parseChatResponse({
        ...base,
        buttons: [
          { label: "?", send: { text: "a", action: { id: "cancel" } } },
        ],
      }),
    ).toThrow();
  });
  it("незнакомый kind не ошибка (Р-38)", () => {
    expect(parseChatResponse({ ...base, kind: "future-kind" }).kind).toBe(
      "future-kind",
    );
  });
  it("принимает метку deleted (15.3) и отвергает запись без обязательных полей", () => {
    const deleted = {
      id: 693,
      type: "meeting",
      text: "Встреча с Марией по интеграции",
      date: "2026-10-24",
      time: "20:45",
      date_kind: "exact",
      status: null,
      created_at: null,
      marks: ["deleted"],
      highlight: null,
    };
    expect(
      parseChatResponse({ ...base, kind: "deleted", records: [deleted] })
        .records[0].marks,
    ).toEqual(["deleted"]);
    expect(() => parseChatResponse({ ...base, records: [{}] })).toThrow();
    expect(() =>
      parseChatResponse({ ...base, records: [{ ...deleted, time: "9:00" }] }),
    ).toThrow();
  });
});
