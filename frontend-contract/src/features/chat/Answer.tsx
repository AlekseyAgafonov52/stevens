import { Fragment, useState } from "react";
import { CircleAlert, RotateCw } from "lucide-react";
import type { Button, RecordItem } from "../../api/types";
import type { Message } from "./types";
import { Card } from "../../components/Card";
import { Pill } from "../../components/Pill";
import { groupDate } from "../../lib/dates";
import { T, fill } from "../../content/texts";
import { features } from "../../config/features";
import { EditRecord } from "../edit/EditRecord";

export function Answer({
  message,
  active,
  locked,
  token,
  onButton,
  onRetry,
  onRecordSaved,
}: {
  message: Message;
  /** Последний ответ: его кнопки ещё можно нажать (Р-33) */
  active: boolean;
  /** Идёт запрос или запись голоса */
  locked: boolean;
  token: string | null;
  onButton: (button: Button, index: number) => void;
  onRetry: () => void;
  onRecordSaved: (record: RecordItem) => void;
}) {
  const response = message.response;
  const isList = response?.kind === "list";
  const isFound = response?.kind === "found";
  const [visible, setVisible] = useState(isList ? 20 : isFound ? 5 : Infinity);
  const [editing, setEditing] = useState(false);
  const records = response?.records ?? [];
  const sorted = isList
    ? [
        ...records.filter((r) => r.date && r.date_kind !== "none"),
        ...records.filter((r) => !r.date || r.date_kind === "none"),
      ]
    : records;
  const groupKey = (record: RecordItem) =>
    record.date_kind === "none" ? null : record.date;
  // Д10: «Исправить» рядом с «Отменить» под created с одной сохранённой записью (15.4)
  const editable =
    features.d10 &&
    response?.kind === "created" &&
    records.length === 1 &&
    records[0].id !== null &&
    !records[0].marks.includes("deleted")
      ? records[0]
      : null;
  return (
    <div className="answer">
      <div className={message.error ? "error-text" : ""}>
        {message.error && <CircleAlert strokeWidth={1.5} aria-hidden="true" />}
        <div>
          <p>{message.text}</p>
          {message.detail && (
            <p className="tech-detail">
              {fill(T.tech_detail, { detail: message.detail })}
            </p>
          )}
        </div>
      </div>
      {sorted.slice(0, visible).map((record, index) => (
        <Fragment key={`${record.id ?? "draft"}-${index}`}>
          {isList &&
            (index === 0 ||
              groupKey(record) !== groupKey(sorted[index - 1])) && (
              <h3 className="day-heading">{groupDate(groupKey(record))}</h3>
            )}
          <Card
            record={record}
            grouped={isList}
            fresh={!message.restored}
            note={
              record.id !== null && message.edited?.includes(record.id)
                ? T.edit_saved
                : undefined
            }
          />
        </Fragment>
      ))}
      {sorted.length > visible && (
        <Pill
          secondary
          onClick={() => setVisible((value) => value + (isFound ? 10 : 20))}
        >
          {fill(T.show_more, {
            count: Math.min(sorted.length - visible, isFound ? 10 : 20),
          })}
        </Pill>
      )}
      {isFound &&
        response.total !== null &&
        response.total > records.length && (
          <p className="limit-caption">
            {fill(T.limit_caption, {
              shown: records.length,
              total: response.total,
            })}
          </p>
        )}
      {response?.nearest && (
        <>
          <h3 className="day-heading">{T.label_nearest}</h3>
          <Card record={response.nearest} fresh={false} />
        </>
      )}
      {editing && editable && (
        <EditRecord
          record={editable}
          token={token}
          onCancel={() => setEditing(false)}
          onSaved={(record) => {
            setEditing(false);
            onRecordSaved(record);
          }}
        />
      )}
      {(!!response?.buttons.length || editable) && !editing && (
        <div className="pill-row">
          {response?.buttons.map((button, index) => (
            <Pill
              key={index}
              secondary={button.style === "secondary"}
              selected={message.selectedButton === index}
              disabled={
                !active ||
                message.restored ||
                message.selectedButton !== undefined
              }
              onClick={() => onButton(button, index)}
            >
              {button.label}
            </Pill>
          ))}
          {editable && (
            <Pill
              secondary
              disabled={locked || message.restored}
              onClick={() => setEditing(true)}
            >
              {T.btn_edit}
            </Pill>
          )}
        </div>
      )}
      {message.error && (
        <div className="pill-row">
          <Pill disabled={!active || message.restored} onClick={onRetry}>
            <RotateCw strokeWidth={1.5} />
            {T.btn_retry}
          </Pill>
        </div>
      )}
    </div>
  );
}
