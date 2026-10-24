/** Импорт и выгрузка v1.6 §9 Ф26: проверка, атомарное применение, отмена в ленте. */
import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, ApiFailure, errorKey } from '../api';
import type { TransferResult } from '../api/types';
import { T, fill } from '../content/texts';
import { showImport } from '../state/imports';
import { sessionExpired } from '../state/session';
import { store } from '../state/store';
import { Modal } from './Modal';
import { Pill } from './Pill';

function issue(code: string): string {
  if (code === 'invalid_time') return T.transfer_invalid_time;
  if (code === 'invalid_text') return T.edit_err_text;
  if (['invalid_date', 'date_time_required', 'time_without_date'].includes(code)) return T.edit_err_datetime;
  return T.err_server;
}

export function TransferScreen({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<TransferResult | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !confirm && !busy && closeRef.current();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [confirm, busy]);

  const run = async (job: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try { await job(); }
    catch (error) {
      if (error instanceof ApiFailure && error.error.type === 'unauthorized') { sessionExpired(); return; }
      if (error instanceof ApiFailure && error.error.type === 'http') {
        if (error.error.errors) {
          setPreview({ add: 0, update: 0, delete: 0, errors: error.error.errors });
          return;
        }
        if (error.error.code === 'bad_json') { setNote(T.transfer_bad_json); return; }
        if (error.error.code === 'empty_import') { setNote(T.transfer_empty); return; }
      }
      setNote(T[errorKey(error)]);
    } finally { setBusy(false); }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); }
    catch { setNote(T.err_server); }
  };
  const apply = () => run(async () => {
    const owner = `${store.get().mode}:${store.get().userId}`;
    const result = await api.importRecords(text, true);
    if (owner === `${store.get().mode}:${store.get().userId}`) showImport(result);
    closeRef.current();
  });
  const errors = preview?.errors ?? [];

  return createPortal(
    <div className="overlay overlay--transfer" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="transfer" role="dialog" aria-modal="true" aria-labelledby="transfer-title">
        <div className="transfer__row">
          <div className="transfer__title" id="transfer-title">{T.transfer_title}</div>
          <button type="button" className="icon-btn" aria-label={T.transfer_close} disabled={busy} onClick={onClose}>
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
          </button>
        </div>
        <div className="transfer__hint">{T.transfer_hint}</div>
        <textarea className="transfer__field" value={text} placeholder={T.transfer_placeholder} spellCheck={false}
          disabled={busy} onChange={(e) => { setText(e.target.value); setPreview(null); setNote(null); setCopied(false); }} />
        <div className="transfer__row">
          <Pill variant="secondary" disabled={busy} onClick={() => void run(async () => {
            setText(await api.exportRecords()); setPreview(null); setCopied(false);
          })}>{T.transfer_export}</Pill>
          <Pill variant="secondary" disabled={busy || !text.trim()} onClick={() => void copy()}>
            {copied ? T.transfer_copied : T.transfer_copy}
          </Pill>
          <Pill variant="secondary" disabled={busy || !text.trim()} onClick={() => void run(async () => {
            setPreview(await api.importRecords(text, false));
          })}>{T.transfer_apply}</Pill>
        </div>
        {busy && <div className="transfer__note">{T.transfer_loading}</div>}
        {note && <div className="transfer__note">{note}</div>}
        {preview && <div className="transfer__preview">
          <div className="transfer__sum">{fill(T.transfer_preview, { add: preview.add, update: preview.update, delete: preview.delete })}</div>
          {errors.length > 0 && <ul className="transfer__list">
            {errors.map((e, i) => <li className="transfer__item transfer__item--error" key={i}>
              {fill(T.transfer_row, { index: e.index })}: {issue(e.code)}
            </li>)}
          </ul>}
          <div className="transfer__buttons"><button type="button" className="pill pill--selected pill--action"
            disabled={busy || errors.length > 0 || preview.add + preview.update + preview.delete === 0}
            onClick={() => preview.delete > 10 ? setConfirm(true) : void apply()}>{T.transfer_confirm}</button></div>
        </div>}
        {confirm && <Modal title={fill(T.transfer_delete_confirm, { count: preview?.delete ?? 0 })}
          text={T.transfer_hint} confirm={T.transfer_confirm} cancel={T.new_dialog_cancel}
          onCancel={() => setConfirm(false)} onConfirm={() => { setConfirm(false); void apply(); }} />}
      </div>
    </div>, document.body,
  );
}
