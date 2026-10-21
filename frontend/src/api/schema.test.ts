import { describe, expect, it } from "vitest";
import { parseChatResponse } from "./schema";
import data from "./mocks.json";

const base = {
  message_id: "1",
  kind: "clarify",
  text: "Во сколько?",
  records: [],
  awaiting_reply: true,
  buttons: [],
};
describe("responses from the existing Pydantic backend and package fixtures", () => {
  it("accepts Pydantic ButtonSend null keys without losing the button", () => {
    const result = parseChatResponse({
      ...base,
      buttons: [
        {
          label: "10:00",
          send: { text: "в 10:00", action: null },
          style: "primary",
        },
        {
          label: "Отменить",
          send: { text: null, action: { id: "cancel", record_id: null } },
        },
      ],
    });
    expect(result.buttons).toHaveLength(2);
    expect(result.buttons[0].send).toEqual({ text: "в 10:00" });
    expect(result.buttons[1].send).toEqual({
      action: { id: "cancel", record_id: undefined },
    });
  });
  it("preserves unknown kinds", () => {
    expect(parseChatResponse({ ...base, kind: "future-kind" }).kind).toBe(
      "future-kind",
    );
  });
  it("falls back to text for malformed records, but rejects a missing text", () => {
    expect(parseChatResponse({ ...base, records: [{}] })).toMatchObject({
      text: base.text,
      records: [],
      buttons: [],
    });
    expect(() => parseChatResponse({ records: [] })).toThrow();
  });
  it("renders every fixture without silently discarding valid records or buttons", () => {
    for (const scenario of data.scenarios) {
      const result = parseChatResponse(scenario.response);
      expect(result.kind, scenario.note).toBe(scenario.response.kind);
      expect(result.records.length, scenario.note).toBe(
        scenario.response.records.length,
      );
      expect(result.buttons.length, scenario.note).toBe(
        scenario.response.buttons.length,
      );
    }
  });
});
