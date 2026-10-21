import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  RotateCw,
  X,
} from "lucide-react";
import {
  ApiError,
  deleteRecord,
  getRecords,
  patchRecord,
  restoreRecord,
} from "../../api";
import type { RecordItem } from "../../api/types";
import { Card } from "../../components/Card";
import { Pill } from "../../components/Pill";
import { T, fill } from "../../content/texts";
import { features } from "../../config/features";
import { groupDate, shortDate, today } from "../../lib/dates";
import { EditRecord } from "../edit/EditRecord";
import { addDays, mondayOf, order, sameTimeIds } from "./week";

interface Failure {
  text: string;
  detail: string;
}
const failureOf = (error: unknown): Failure => ({
  text: error instanceof Error ? error.message : T.err_server,
  detail: error instanceof ApiError ? error.detail : "",
});

/** Д6 Встроенный календарь: неделя записей через REST 15.5 */
export function CalendarPanel({
  token,
  refreshKey,
  onClose,
  onUnauthorized,
}: {
  token: string | null;
  /** Меняется после ответов чата, которые могли изменить записи */
  refreshKey: number;
  onClose: () => void;
  onUnauthorized: () => void;
}) {
  const [week, setWeek] = useState(() => mondayOf(today()));
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Failure | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [rowError, setRowError] = useState<{ id: number } & Failure>();

  const handle = useCallback(
    (failure: unknown, id?: number) => {
      if (failure instanceof ApiError && failure.kind === "unauthorized") {
        onUnauthorized();
        return;
      }
      if (id === undefined) setError(failureOf(failure));
      else setRowError({ id, ...failureOf(failure) });
    },
    [onUnauthorized],
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    getRecords(week, addDays(week, 6), token)
      .then((items) => {
        if (!active) return;
        setRecords(items);
        setEditing(null);
        setRowError(undefined);
      })
      .catch((failure) => {
        if (active) handle(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [week, token, refreshKey, attempt, handle]);

  function replace(record: RecordItem) {
    setRecords((current) =>
      current
        .map((item) => (item.id === record.id ? record : item))
        .sort((a, b) => order(a).localeCompare(order(b))),
    );
  }
  async function run(id: number, action: () => Promise<void>) {
    setBusy(id);
    setRowError(undefined);
    try {
      await action();
    } catch (failure) {
      handle(failure, id);
    } finally {
      setBusy(null);
    }
  }

  const overlap = sameTimeIds(records);
  const days = Array.from({ length: 7 }, (_, index) => addDays(week, index));
  const current = mondayOf(today());

  return (
    <aside className="calendar-panel" aria-label={T.cal_title}>
      <div className="calendar-head">
        <h2>{T.cal_title}</h2>
        <button
          className="icon-plain"
          aria-label={T.cal_close}
          onClick={onClose}
        >
          <X strokeWidth={1.5} />
        </button>
      </div>
      <div className="calendar-nav">
        <button
          className="icon-plain"
          aria-label={T.cal_prev}
          onClick={() => setWeek((value) => addDays(value, -7))}
        >
          <ChevronLeft strokeWidth={1.5} />
        </button>
        <span>
          {shortDate(week)} — {shortDate(addDays(week, 6))}
        </span>
        <button
          className="icon-plain"
          aria-label={T.cal_next}
          onClick={() => setWeek((value) => addDays(value, 7))}
        >
          <ChevronRight strokeWidth={1.5} />
        </button>
        {week !== current && (
          <Pill secondary onClick={() => setWeek(current)}>
            {T.cal_today}
          </Pill>
        )}
      </div>
      <div className="calendar-body">
        {loading ? (
          <p className="calendar-note" role="status">
            {T.cal_loading}
          </p>
        ) : error ? (
          <div className="calendar-error" role="alert">
            <div className="error-text">
              <CircleAlert strokeWidth={1.5} aria-hidden="true" />
              <div>
                <p>{error.text}</p>
                {error.detail && (
                  <p className="tech-detail">
                    {fill(T.tech_detail, { detail: error.detail })}
                  </p>
                )}
              </div>
            </div>
            <Pill onClick={() => setAttempt((value) => value + 1)}>
              <RotateCw strokeWidth={1.5} />
              {T.btn_retry}
            </Pill>
          </div>
        ) : records.length === 0 ? (
          <p className="calendar-note">{T.cal_empty}</p>
        ) : (
          days.map((day) => {
            const items = records.filter((record) => record.date === day);
            if (items.length === 0) return null;
            return (
              <section key={day} className="calendar-day">
                <h3 className="day-heading">{groupDate(day)}</h3>
                {items.map((record) => {
                  const id = record.id;
                  if (id === null) return null;
                  const deleted = record.marks.includes("deleted");
                  // Отметка — только задачи и напоминания (15.5), с допом Д3
                  const checkable =
                    features.d3 &&
                    (record.type === "task" || record.type === "reminder");
                  const locked = busy !== null;
                  return (
                    <div key={id} className="calendar-item">
                      <Card
                        record={record}
                        grouped
                        fresh={false}
                        sameTime={overlap.has(id)}
                      >
                        {editing === id ? null : deleted ? (
                          features.d2 && (
                            <Pill
                              secondary
                              disabled={locked}
                              onClick={() =>
                                run(id, async () =>
                                  replace(await restoreRecord(id, token)),
                                )
                              }
                            >
                              {T.cal_restore}
                            </Pill>
                          )
                        ) : (
                          <>
                            {checkable && (
                              <Pill
                                secondary
                                disabled={locked}
                                onClick={() =>
                                  run(id, async () =>
                                    replace(
                                      await patchRecord(
                                        id,
                                        {
                                          status:
                                            record.status === "done"
                                              ? "open"
                                              : "done",
                                        },
                                        token,
                                      ),
                                    ),
                                  )
                                }
                              >
                                {record.status === "done"
                                  ? T.cal_reopen
                                  : T.cal_complete}
                              </Pill>
                            )}
                            <Pill
                              secondary
                              disabled={locked}
                              onClick={() => {
                                setRowError(undefined);
                                setEditing(id);
                              }}
                            >
                              {T.btn_edit}
                            </Pill>
                            {features.d2 && (
                              <Pill
                                secondary
                                disabled={locked}
                                onClick={() =>
                                  run(id, async () => {
                                    await deleteRecord(id, token);
                                    replace({
                                      ...record,
                                      marks: [...record.marks, "deleted"],
                                    });
                                  })
                                }
                              >
                                {T.cal_delete}
                              </Pill>
                            )}
                          </>
                        )}
                      </Card>
                      {editing === id && (
                        <EditRecord
                          record={record}
                          token={token}
                          onCancel={() => setEditing(null)}
                          onSaved={(saved) => {
                            setEditing(null);
                            replace(saved);
                          }}
                        />
                      )}
                      {rowError?.id === id && (
                        <div className="auth-error" role="alert">
                          <CircleAlert strokeWidth={1.5} />
                          <div>
                            <p>{rowError.text}</p>
                            {rowError.detail && (
                              <p className="tech-detail">
                                {fill(T.tech_detail, {
                                  detail: rowError.detail,
                                })}
                              </p>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </section>
            );
          })
        )}
      </div>
    </aside>
  );
}
