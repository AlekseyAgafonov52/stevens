import { describe, expect, it } from "vitest";
import { buildPatch } from "./patch";
import type { RecordItem } from "../../api/types";

const task: RecordItem = {
  id: 1,
  type: "task",
  text: "Отчёт",
  date: "2026-10-23",
  time: null,
  date_kind: "exact",
  status: "open",
  created_at: null,
  marks: [],
  highlight: null,
};
const values = { text: "Отчёт", date: "2026-10-23", time: "", noDate: false };

describe("правила PATCH (15.5)", () => {
  it("шлёт только изменённые поля", () => {
    expect(buildPatch(task, { ...values, text: "Отчёт v2" })).toEqual({
      patch: { text: "Отчёт v2" },
      error: null,
    });
    expect(buildPatch(task, values).patch).toEqual({});
  });
  it("задача без срока: date и time = null", () => {
    expect(buildPatch(task, { ...values, noDate: true }).patch).toEqual({
      date: null,
    });
  });
  it("время без даты у задачи — нельзя", () => {
    expect(
      buildPatch(
        { ...task, date: null, date_kind: "none" },
        {
          ...values,
          date: "",
          time: "10:00",
        },
      ).error,
    ).toBeTruthy();
  });
  it("у встречи и напоминания дата и время обязательны", () => {
    const meeting = { ...task, type: "meeting" as const, time: "10:00" };
    expect(buildPatch(meeting, { ...values, time: "" }).error).toBeTruthy();
  });
  it("пустой или длинный текст — нельзя", () => {
    expect(buildPatch(task, { ...values, text: " " }).error).toBeTruthy();
    expect(
      buildPatch(task, { ...values, text: "x".repeat(301) }).error,
    ).toBeTruthy();
  });
});
