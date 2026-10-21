import { describe, expect, it, vi } from "vitest";
vi.mock("./clock", () => ({
  now: () => new Date("2026-10-21T10:00:00+03:00"),
  userTimezone: () => "Europe/Moscow",
}));
import { displayDate, groupDate, isPast } from "./dates";
import type { RecordItem } from "../api/types";

const record: RecordItem = {
  id: 1,
  type: "task",
  text: "Тест",
  date: "2026-10-21",
  time: "08:00",
  date_kind: "exact",
  status: "open",
  created_at: null,
  marks: [],
  highlight: null,
};
describe("calendar rules at the contract test clock (Moscow)", () => {
  it("recognizes local today, tomorrow and yesterday", () => {
    expect(displayDate("2026-10-21")).toBe("сегодня");
    expect(displayDate("2026-10-22")).toBe("завтра");
    expect(displayDate("2026-10-20")).toBe("вчера");
    expect(groupDate("2026-10-21")).toBe("Сегодня, ср 21 окт");
  });
  it("includes a different year and handles year boundaries", () => {
    expect(displayDate("2027-01-05")).toBe("вт, 5 янв 2027");
    expect(
      displayDate("2027-01-01", new Date("2026-12-31T22:00:00+03:00")),
    ).toBe("завтра");
  });
  it("distinguishes exact times from deadlines on the same day", () => {
    expect(isPast(record)).toBe(true);
    expect(isPast({ ...record, time: "10:15" })).toBe(false);
    expect(isPast({ ...record, date_kind: "deadline" })).toBe(false);
    expect(isPast({ ...record, time: null })).toBe(false);
    expect(isPast({ ...record, marks: ["draft"] })).toBe(false);
    expect(isPast({ ...record, date: "2026-10-20", date_kind: "none" })).toBe(
      false,
    );
  });
});
