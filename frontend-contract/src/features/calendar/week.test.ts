import { describe, expect, it } from "vitest";
import { addDays, mondayOf, sameTimeIds } from "./week";
import type { RecordItem } from "../../api/types";

const meeting = (id: number, time: string, marks: RecordItem["marks"] = []) =>
  ({
    id,
    type: "meeting",
    text: "Встреча",
    date: "2026-10-24",
    time,
    date_kind: "exact",
    status: null,
    created_at: null,
    marks,
    highlight: null,
  }) satisfies RecordItem;

describe("календарь", () => {
  it("неделя с понедельника", () => {
    expect(mondayOf("2026-10-21")).toBe("2026-10-19");
    expect(mondayOf("2026-10-25")).toBe("2026-10-19");
    expect(addDays("2026-10-19", 6)).toBe("2026-10-25");
    expect(addDays("2026-12-28", 7)).toBe("2027-01-04");
  });
  it("«В то же время» — только встречи с одинаковым началом, без удалённых", () => {
    const ids = sameTimeIds([
      meeting(1, "20:45"),
      meeting(2, "20:45"),
      meeting(3, "21:00"),
      meeting(4, "21:00", ["deleted"]),
      { ...meeting(5, "20:45"), type: "task" },
    ]);
    expect([...ids].sort()).toEqual([1, 2]);
  });
});
