import { Fragment, useState } from "react";
import { CircleAlert, RotateCw } from "lucide-react";
import type { Button, RecordItem } from "../../api/types";
import type { Message } from "./types";
import { Card } from "../../components/Card";
import { Pill } from "../../components/Pill";
import { groupDate } from "../../lib/dates";
import { T, fill } from "../../content/texts";

export function Answer({
  message,
  active,
  onButton,
  onRetry,
}: {
  message: Message;
  active: boolean;
  onButton: (button: Button, index: number) => void;
  onRetry: () => void;
}) {
  const response = message.response;
  const isList = response?.kind === "list";
  const isFound = response?.kind === "found";
  const [visible, setVisible] = useState(isList ? 20 : isFound ? 5 : Infinity);
  const records = response?.records ?? [];
  const sorted = isList
    ? [
        ...records.filter((r) => r.date && r.date_kind !== "none"),
        ...records.filter((r) => !r.date || r.date_kind === "none"),
      ]
    : records;
  const groupKey = (record: RecordItem) =>
    record.date_kind === "none" ? null : record.date;
  return (
    <div className="answer">
      <div className={message.error ? "error-text" : ""}>
        {message.error && <CircleAlert strokeWidth={1.5} aria-hidden="true" />}
        <p>{message.text}</p>
      </div>
      {sorted.slice(0, visible).map((record, index) => (
        <Fragment key={`${record.id ?? "draft"}-${index}`}>
          {isList &&
            (index === 0 ||
              groupKey(record) !== groupKey(sorted[index - 1])) && (
              <h3 className="day-heading">{groupDate(groupKey(record))}</h3>
            )}
          <Card record={record} grouped={isList} fresh={!message.restored} />
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
      {!!response?.buttons.length && (
        <div className="pill-row">
          {response.buttons.map((button, index) => (
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
