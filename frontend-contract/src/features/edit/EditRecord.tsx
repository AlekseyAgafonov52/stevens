import { useState } from "react";
import { CircleAlert } from "lucide-react";
import { ApiError, patchRecord } from "../../api";
import type { RecordItem } from "../../api/types";
import { Pill } from "../../components/Pill";
import { T, fill } from "../../content/texts";
import { buildPatch } from "./patch";

export function EditRecord({
  record,
  token,
  onSaved,
  onCancel,
}: {
  record: RecordItem;
  token: string | null;
  onSaved: (record: RecordItem) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(record.text);
  const [date, setDate] = useState(record.date ?? "");
  const [time, setTime] = useState(record.time ?? "");
  const [noDate, setNoDate] = useState(record.date_kind === "none");
  const [error, setError] = useState("");
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const isTask = record.type !== "meeting" && record.type !== "reminder";

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (record.id === null) return;
    const result = buildPatch(record, { text, date, time, noDate });
    setDetail("");
    if (result.error) {
      setError(result.error);
      return;
    }
    if (Object.keys(result.patch).length === 0) {
      onCancel();
      return;
    }
    setBusy(true);
    setError("");
    try {
      onSaved(await patchRecord(record.id, result.patch, token));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : T.err_server);
      setDetail(failure instanceof ApiError ? failure.detail : "");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="edit-form" onSubmit={save}>
      <label className="form-field">
        {T.edit_text}
        <input
          value={text}
          maxLength={300}
          disabled={busy}
          onChange={(event) => setText(event.target.value)}
          autoFocus
        />
      </label>
      <div className="edit-row">
        <label className="form-field">
          {T.edit_date}
          <input
            type="date"
            value={noDate ? "" : date}
            disabled={busy || noDate}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label className="form-field">
          {T.edit_time}
          <input
            type="time"
            value={noDate ? "" : time}
            disabled={busy || noDate}
            onChange={(event) => setTime(event.target.value)}
          />
        </label>
      </div>
      {isTask && (
        <label className="edit-check">
          <input
            type="checkbox"
            checked={noDate}
            disabled={busy}
            onChange={(event) => setNoDate(event.target.checked)}
          />
          {T.edit_no_date}
        </label>
      )}
      {error && (
        <div className="auth-error" role="alert">
          <CircleAlert strokeWidth={1.5} />
          <div>
            <p>{error}</p>
            {detail && (
              <p className="tech-detail">{fill(T.tech_detail, { detail })}</p>
            )}
          </div>
        </div>
      )}
      <div className="pill-row">
        <Pill type="submit" disabled={busy}>
          {T.edit_save}
        </Pill>
        <Pill secondary disabled={busy} onClick={onCancel}>
          {T.edit_cancel}
        </Pill>
      </div>
    </form>
  );
}
