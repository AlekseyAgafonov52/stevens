/** Импорт и выгрузка: все записи одним JSON — разобрать расписание в другой ИИ и вернуть правки разом. */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, ApiFailure, errorKey } from '../api';
import type { TransferItem, TransferResult } from '../api/types';
import { T, fill } from '../content/texts';
import { shortDate } from '../lib/dates';
import { emitRecordsChanged } from '../state/events';
import { sessionExpired } from '../state/session';
import { Pill } from './Pill';

const TYPE_WORD: Record<string, string> = {
  meeting: T.type_meeting, task: T.type_task, reminder: T.type_reminder, note: T.type_note, busy: T.type_busy,
};
const ACTION_WORD = { add: T.transfer_add, update: T.transfer_update, delete: T.transfer_delete };

/** «Занятость · вт, 27 окт · 16:40–19:50» или «Занятость · по вт · 16:40–19:50» */
function when(item: TransferItem): string {
  const parts = [TYPE_WORD[item.type] ?? item.type];
  if (item.repeat) parts.push(fill(T.repeat_days, { days: item.repeat.weekdays.map((d) => T.weekdays_short[d]).join(', ') }));
  else if (item.date) parts.push(shortDate(item.date));
  else if (item.type === 'task') parts.push(T.date_none);
  if (item.time) parts.push(item.end_time ? `${item.time}–${item.end_time}` : item.time);
  if (item.status === 'done') parts.push('✓');
  return parts.join(' · ');
}

function failText(error: unknown): string {
  if (error instanceof ApiFailure && error.error.type === 'http') {
    const code = error.error.code;
    if (code === 'bad_json') return T.transfer_bad_json;
    if (code === 'empty') return T.transfer_empty;
    if (code === 'too_many') return T.transfer_too_many;
  }
  return T[errorKey(error)];
}

export function TransferScreen({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<TransferResult | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const run = async (job: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await job();
    } catch (error) {
      if (error instanceof ApiFailure && error.error.type === 'unauthorized') {
        sessionExpired();
        return;
      }
      setNote(failText(error));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* без доступа к буферу — текст и так в поле */
    }
  };

  const exportAll = () => run(async () => {
    const json = await api.exportRecords();
    setText(json);
    setPreview(null);
    await copy(json);
  });

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `stevens-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const check = () => run(async () => setPreview(await api.importRecords(text, false)));

  const apply = () => run(async () => {
    const done = await api.importRecords(text, true);
    setPreview(null);
    setText(''); // второй раз то же самое не применить — новые записи задвоились бы
    setNote(fill(T.transfer_done, { add: done.add, update: done.update, delete: done.delete }));
    emitRecordsChanged();
  });

  const changes = preview ? preview.add + preview.update + preview.delete : 0;

  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="transfer" role="dialog" aria-modal="true" aria-labelledby="transfer-title">
        <div className="transfer__title" id="transfer-title">{T.transfer_title}</div>
        <div className="transfer__hint">{T.transfer_hint}</div>
        <div className="transfer__row">
          <Pill variant="secondary" disabled={busy} onClick={() => void exportAll()}>{T.transfer_export}</Pill>
          {text && <Pill variant="secondary" onClick={() => void copy(text)}>{copied ? T.transfer_copied : T.transfer_copy}</Pill>}
          {text && <Pill variant="secondary" onClick={download}>{T.transfer_download}</Pill>}
        </div>
        <textarea
          className="transfer__field"
          value={text}
          placeholder={T.transfer_placeholder}
          spellCheck={false}
          onChange={(e) => { setText(e.target.value); setPreview(null); setNote(null); }}
        />
        {busy && <div className="transfer__note">{T.transfer_loading}</div>}
        {note && <div className="transfer__note">{note}</div>}
        {preview && (
          <div className="transfer__preview">
            <div className="transfer__sum">
              {changes
                ? fill(T.transfer_preview, { add: preview.add, update: preview.update, delete: preview.delete })
                : T.transfer_nothing}
              {preview.unchanged > 0 && changes > 0 && ` ${fill(T.transfer_unchanged, { count: preview.unchanged })}`}
            </div>
            {preview.items.length > 0 && (
              <ul className="transfer__list">
                {preview.items.map((item, i) => (
                  <li key={i} className={`transfer__item transfer__item--${item.action}`}>
                    <span className="transfer__action">{ACTION_WORD[item.action]}</span>
                    <span className="transfer__text">{item.record.text}</span>
                    <span className="transfer__meta">
                      {item.before && when(item.before) !== when(item.record) && `${T.transfer_was}: ${when(item.before)} → `}
                      {when(item.record)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {preview.errors.length > 0 && (
              <>
                <div className="transfer__sum transfer__sum--alarm">{T.transfer_errors}</div>
                <ul className="transfer__list">
                  {preview.errors.map((e) => (
                    <li key={e.index} className="transfer__item transfer__item--error">
                      <span className="transfer__action">{fill(T.transfer_row, { index: e.index })}</span>
                      {e.text && <span className="transfer__text">{e.text}</span>}
                      <span className="transfer__meta">{e.error}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
        <div className="transfer__buttons">
          <Pill variant="secondary" onClick={onClose}>{T.transfer_close}</Pill>
          {preview && changes > 0 ? (
            <button type="button" className="pill pill--selected pill--action" disabled={busy} onClick={() => void apply()}>
              {T.transfer_confirm}
            </button>
          ) : (
            <button type="button" className="pill pill--selected pill--action" disabled={busy || !text.trim() || !!preview}
                    onClick={() => void check()}>
              {T.transfer_apply}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
