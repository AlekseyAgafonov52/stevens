import { useEffect, useState, type ReactNode } from "react";
import { Bell, CircleAlert, CircleCheck, Users } from "lucide-react";
import type { RecordItem } from "../api/types";
import { displayDate, isPast } from "../lib/dates";
import { T, fill } from "../content/texts";

export function Card({
  record,
  grouped = false,
  fresh = true,
  sameTime = false,
  note,
  children,
}: {
  record: RecordItem;
  grouped?: boolean;
  fresh?: boolean;
  /** Календарь: другая встреча в то же время — пометку ставит фронт (15.5) */
  sameTime?: boolean;
  /** Короткая подпись справа, например «Изменено» */
  note?: string;
  /** Кнопки действий под текстом (календарь) */
  children?: ReactNode;
}) {
  const [highlight, setHighlight] = useState(
    fresh && record.marks.includes("new"),
  );
  useEffect(() => {
    const timer = setTimeout(() => setHighlight(false), 2000);
    return () => clearTimeout(timer);
  }, []);
  const draft = record.marks.includes("draft");
  const conflict = record.marks.includes("conflict") || sameTime;
  const deleted = record.marks.includes("deleted");
  const Icon =
    record.type === "meeting"
      ? Users
      : record.type === "task"
        ? CircleCheck
        : record.type === "reminder"
          ? Bell
          : null;
  const type =
    record.type === "meeting"
      ? T.type_meeting
      : record.type === "task"
        ? T.type_task
        : record.type === "reminder"
          ? T.type_reminder
          : null;
  const date =
    record.date_kind === "none"
      ? T.date_none
      : record.date_kind === "deadline"
        ? fill(T.date_deadline, { date: displayDate(record.date) })
        : displayDate(record.date);
  return (
    <article
      className={`record-card ${deleted ? "is-deleted" : draft ? "is-draft" : conflict ? "is-conflict" : highlight ? "is-new" : ""} ${isPast(record) ? "is-past" : ""} ${record.status === "done" ? "is-done" : ""}`}
    >
      <div className="record-meta">
        <div className="record-details">
          {Icon && (
            <Icon
              className="record-type-icon"
              strokeWidth={1.5}
              aria-hidden="true"
            />
          )}
          {type && <span>{type}</span>}
          {(!grouped || record.date_kind !== "exact") && (
            <>
              {type && <span aria-hidden="true">·</span>}
              <span className={record.highlight === "date" ? "marked" : ""}>
                {date}
              </span>
            </>
          )}
          {record.time && record.date_kind !== "none" && (
            <>
              <span aria-hidden="true">·</span>
              <span className={record.highlight === "time" ? "marked" : ""}>
                {record.time}
              </span>
            </>
          )}
        </div>
        {deleted ? (
          <span className="record-badge">{T.label_deleted}</span>
        ) : draft ? (
          <span className="record-badge">{T.label_draft}</span>
        ) : conflict ? (
          <span className="record-badge conflict-badge">
            <CircleAlert strokeWidth={1.5} />
            {T.label_conflict}
          </span>
        ) : note ? (
          <span className="record-badge">{note}</span>
        ) : null}
      </div>
      <p className="record-text">
        <span className={record.highlight === "text" ? "marked" : ""}>
          {record.text}
        </span>
      </p>
      {children && <div className="record-actions">{children}</div>}
    </article>
  );
}
