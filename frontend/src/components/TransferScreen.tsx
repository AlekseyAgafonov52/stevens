/** Импорт и выгрузка: вкладки, файл календаря или ответ нейросети, предпросмотр, отмена в ленте. */
import { Check, Copy, Download, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { createPortal } from 'react-dom';
import { api, ApiFailure, errorKey } from '../api';
import type { TransferItem, TransferResult } from '../api/types';
import { importPrompt } from '../content/importPrompt';
import { T, fill } from '../content/texts';
import { pluralKey, shortDate } from '../lib/dates';
import { showImport } from '../state/imports';
import { sessionExpired } from '../state/session';
import { store } from '../state/store';
import { Modal } from './Modal';
import { Pill } from './Pill';

type Tab = 'import' | 'export';
type Source = { kind: 'file'; name: string; ics: string } | { kind: 'text'; name: string; text: string };

const KINDS = ['meeting', 'task', 'reminder', 'busy', 'note', 'repeat'] as const;
const touch = typeof window !== 'undefined' && window.matchMedia?.('(hover: none)').matches;
const isIcs = (text: string) => /BEGIN:VCALENDAR|BEGIN:VEVENT/i.test(text.slice(0, 20000));

function issue(code: string): string {
  if (code === 'invalid_time') return T.transfer_invalid_time;
  if (code === 'invalid_text') return T.edit_err_text;
  if (['invalid_date', 'date_time_required', 'time_without_date'].includes(code)) return T.edit_err_datetime;
  return T.err_server;
}

function when(item: TransferItem): string {
  if (item.repeat) {
    const days = [...item.repeat.weekdays].sort();
    const rule = days.length === 7 ? T.transfer_repeat_daily
      : days.join() === '0,1,2,3,4' ? T.transfer_repeat_workdays
        : days.map((d) => T.weekdays_short[d]).join(', ');
    return [rule, item.time && (item.end_time ? `${item.time}–${item.end_time}` : item.time)].filter(Boolean).join(' · ');
  }
  if (!item.date) return item.type === 'note' ? T.type_note : T.date_none;
  const time = item.time ? (item.end_time ? `${item.time}–${item.end_time}` : item.time) : '';
  return [shortDate(item.date), time].filter(Boolean).join(' · ');
}

export function TransferScreen({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('import');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  // Импорт
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [preview, setPreview] = useState<TransferResult | null>(null);
  const [dragging, setDragging] = useState(false);
  const [promptCopied, setPromptCopied] = useState(false);
  // Выгрузка
  const [exported, setExported] = useState<string | null>(null);
  const [exportCopied, setExportCopied] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const checkRef = useRef(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !confirm && !busy && closeRef.current();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [confirm, busy]);

  const fail = (error: unknown) => {
    if (error instanceof ApiFailure && error.error.type === 'unauthorized') { sessionExpired(); return; }
    if (error instanceof ApiFailure && error.error.type === 'http') {
      if (error.error.errors) { setPreview({ add: 0, update: 0, delete: 0, errors: error.error.errors }); return; }
      const code = error.error.code;
      if (code === 'bad_json') { setNote(T.transfer_bad_json); return; }
      if (code === 'empty_import') { setNote(T.transfer_empty); return; }
      if (code === 'bad_ics') { setNote(T.transfer_bad_file); return; }
      if (code === 'empty_ics') { setNote(T.transfer_empty_file); return; }
    }
    setNote(T[errorKey(error)]);
  };

  const check = (next: Source, apply: boolean) => next.kind === 'file'
    ? api.importCalendar(next.ics, apply) : api.importRecords(next.text, apply);

  /** Проверка сразу, без отдельной кнопки: файл — при выборе, текст — когда перестали печатать. */
  const inspect = async (next: Source) => {
    const ticket = ++checkRef.current;
    setSource(next);
    setPreview(null);
    setNote(null);
    setBusy(true);
    try {
      const result = await check(next, false);
      if (ticket === checkRef.current) setPreview(result);
    } catch (error) {
      if (ticket === checkRef.current) fail(error);
    } finally {
      if (ticket === checkRef.current) setBusy(false);
    }
  };

  useEffect(() => {
    if (!pasting) return;
    const value = text.trim();
    if (!value) { checkRef.current++; setPreview(null); setNote(null); setBusy(false); return; }
    const timer = window.setTimeout(() => void inspect(isIcs(value)
      ? { kind: 'file', name: '', ics: value } : { kind: 'text', name: '', text: value }), 600);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, pasting]);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    const content = await file.text().catch(() => '');
    setPasting(false);
    if (isIcs(content)) void inspect({ kind: 'file', name: file.name, ics: content });
    else void inspect({ kind: 'text', name: file.name, text: content });
  };

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void pick(e.dataTransfer.files?.[0]);
  };

  const apply = async () => {
    if (!source || busy) return;
    setBusy(true);
    try {
      const owner = `${store.get().mode}:${store.get().userId}`;
      const result = await check(source, true);
      if (owner === `${store.get().mode}:${store.get().userId}`) showImport(result);
      closeRef.current();
    } catch (error) { fail(error); }
    finally { setBusy(false); }
  };

  const reset = () => {
    checkRef.current++;
    setSource(null); setPreview(null); setNote(null); setBusy(false);
    if (!pasting) fileRef.current?.click();
  };

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(importPrompt(new Date().toLocaleDateString('sv-SE')));
      setPromptCopied(true);
    } catch { setNote(T.err_server); }
  };

  useEffect(() => {
    if (tab !== 'export' || exported !== null) return;
    let alive = true;
    api.exportRecords().then((value) => alive && setExported(value)).catch((error) => alive && fail(error));
    return () => { alive = false; };
  }, [tab, exported]);

  const exportCount = (() => {
    try { return (JSON.parse(exported ?? '{}') as { records?: unknown[] }).records?.length ?? 0; }
    catch { return 0; }
  })();
  const download = () => {
    if (!exported) return;
    const url = URL.createObjectURL(new Blob([exported], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `stevens-${new Date().toLocaleDateString('sv-SE')}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const copyExport = async () => {
    if (!exported) return;
    try { await navigator.clipboard.writeText(exported); setExportCopied(true); }
    catch { setNote(T.err_server); }
  };

  const switchTab = (next: Tab) => { setTab(next); setNote(null); };

  const errors = preview?.errors ?? [];
  const replacing = !!preview && (preview.update > 0 || preview.delete > 0);
  const total = preview ? preview.add + preview.update + preview.delete : 0;
  const kinds = KINDS.filter((k) => preview?.kinds?.[k])
    .map((k) => `${T[`transfer_kind_${k}`]} ${preview?.kinds?.[k]}`).join(' · ');
  const items = preview?.items ?? [];
  const more = preview ? preview.add + preview.update + preview.delete - items.length : 0;

  const summary = preview && errors.length === 0 && (
    <div className="transfer__preview">
      {total === 0 ? <div className="transfer__sum">{T.transfer_all_same}</div> : <>
        <div className={`transfer__sum ${preview.delete > 0 ? 'transfer__sum--alarm' : ''}`}>
          {replacing ? fill(T.transfer_replace, { add: preview.add, update: preview.update, delete: preview.delete })
            : fill(T[`transfer_add_${pluralKey(preview.add)}`], { count: preview.add })}
        </div>
        {kinds && !replacing && <div className="transfer__note">{kinds}</div>}
        {replacing && <div className="transfer__note">{T.transfer_replace_note}</div>}
        {items.length > 0 && <ul className="transfer__list">
          {items.map((item, i) => <li key={i} className={`transfer__item transfer__item--${item.action}`}>
            <span className="transfer__when">{when(item)}</span>
            <span className="transfer__text">{item.text}</span>
          </li>)}
          {more > 0 && <li className="transfer__more">{fill(T.transfer_more, { count: more })}</li>}
        </ul>}
      </>}
      {(preview.same || preview.skipped || preview.past) ? <div className="transfer__note">
        {[preview.past && fill(T.transfer_past, { count: preview.past }),
          preview.same && fill(T.transfer_same, { count: preview.same }),
          preview.skipped && fill(T.transfer_skipped, { count: preview.skipped })].filter(Boolean).join(' ')}
      </div> : null}
    </div>
  );

  const failed = errors.length > 0 && (
    <div className="transfer__preview">
      <div className="transfer__sum transfer__sum--alarm">{T.transfer_has_errors}</div>
      <ul className="transfer__list">
        {errors.map((e, i) => <li className="transfer__item transfer__item--error" key={i}>
          <span className="transfer__when">{fill(T.transfer_row, { index: e.index })}</span>
          <span className="transfer__text">{issue(e.code)}</span>
        </li>)}
      </ul>
    </div>
  );


  return createPortal(
    <div className="overlay overlay--transfer" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="transfer" role="dialog" aria-modal="true" aria-labelledby="transfer-title">
        <div className="transfer__head">
          <div className="transfer__title" id="transfer-title">{T.transfer_title}</div>
          <button type="button" className="transfer__close" aria-label={T.transfer_close} disabled={busy} onClick={onClose}>
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
          </button>
        </div>
        <div className="transfer__tabs" role="tablist">
          {(['import', 'export'] as const).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} disabled={busy}
              className={`transfer__tab ${tab === t ? 'transfer__tab--active' : ''}`} onClick={() => switchTab(t)}>
              {t === 'import' ? T.transfer_tab_import : T.transfer_tab_export}
            </button>
          ))}
        </div>

        {tab === 'import' && <>
          <input ref={fileRef} type="file" hidden
            accept=".ics,.ical,.icalendar,.json,.txt,text/calendar,application/json,text/plain"
            onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ''; }} />

          {!pasting && !source && <>
            <button type="button" className={`transfer__drop ${dragging ? 'transfer__drop--active' : ''}`}
              onClick={() => fileRef.current?.click()} disabled={busy}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)} onDrop={drop}>
              <Upload size={22} strokeWidth={1.5} aria-hidden="true" />
              <span className="transfer__drop-title">{dragging ? T.transfer_drop_active : touch ? T.transfer_drop_touch : T.transfer_drop_title}</span>
              {!touch && <span className="transfer__drop-sub">{T.transfer_drop_sub}</span>}
            </button>
            <div className="transfer__hint">{T.transfer_drop_hint}</div>
            <details className="transfer__where">
              <summary>{T.transfer_where}</summary>
              <ul>
                <li>{T.transfer_where_google}</li>
                <li>{T.transfer_where_yandex}</li>
                <li>{T.transfer_where_apple}</li>
                <li>{T.transfer_where_outlook}</li>
              </ul>
            </details>
            <div className="transfer__or"><span>{T.transfer_or}</span></div>
            <button type="button" className="transfer__link" onClick={() => { setPasting(true); setNote(null); }}>
              {T.transfer_paste_link}
            </button>
          </>}

          {pasting && <>
            <div className="transfer__hint">{T.transfer_paste_hint}</div>
            <div className="transfer__row">
              <Pill variant="secondary" onClick={() => void copyPrompt()}
                icon={promptCopied ? <Check size={14} strokeWidth={1.75} aria-hidden="true" />
                  : <Copy size={14} strokeWidth={1.5} aria-hidden="true" />}>
                {promptCopied ? T.transfer_prompt_done : T.transfer_prompt_copy}
              </Pill>
            </div>
            <textarea className="transfer__field" value={text} placeholder={T.transfer_placeholder} spellCheck={false}
              autoFocus onChange={(e) => setText(e.target.value)} />
          </>}

          {!pasting && source && <div className="transfer__file">
            <span className="transfer__file-name">{source.name}</span>
            <button type="button" className="transfer__link" disabled={busy} onClick={reset}>{T.transfer_other_file}</button>
          </div>}

          {busy && <div className="transfer__note">{T.transfer_reading}</div>}
          {note && <div className="transfer__note transfer__note--alarm">{note}</div>}
          {!busy && summary}
          {!busy && failed}

          {(pasting || source) && <div className="transfer__foot">
            {pasting ? <button type="button" className="transfer__link" disabled={busy}
              onClick={() => { checkRef.current++; setPasting(false); setText(''); setSource(null); setPreview(null); setNote(null); setBusy(false); }}>
              ← {T.transfer_back_file}
            </button> : <span />}
            {preview && errors.length === 0 && total > 0 && !busy && (
              <button type="button" className="pill pill--selected pill--action"
                onClick={() => preview.delete > 10 ? setConfirm(true) : void apply()}>
                {replacing ? T.transfer_apply_btn : `${T.transfer_add_btn} ${preview.add}`}
              </button>
            )}
          </div>}
        </>}

        {tab === 'export' && <>
          <div className="transfer__hint">{T.transfer_export_text}</div>
          <div className="transfer__sum">{exported === null ? T.transfer_loading : fill(T.transfer_export_count, { count: exportCount })}</div>
          {note && <div className="transfer__note transfer__note--alarm">{note}</div>}
          {exported !== null && <div className="transfer__foot transfer__foot--end">
            <Pill variant="secondary" onClick={() => void copyExport()}
              icon={exportCopied ? <Check size={14} strokeWidth={1.75} aria-hidden="true" />
                : <Copy size={14} strokeWidth={1.5} aria-hidden="true" />}>
              {exportCopied ? T.transfer_export_copied : T.transfer_export_copy}
            </Pill>
            <button type="button" className="pill pill--selected pill--action" onClick={download}>
              <Download size={14} strokeWidth={1.75} aria-hidden="true" />
              {T.transfer_export_download}
            </button>
          </div>}
        </>}

        {confirm && <Modal title={fill(T.transfer_delete_confirm, { count: preview?.delete ?? 0 })}
          text={T.transfer_replace_note} confirm={T.transfer_confirm} cancel={T.new_dialog_cancel}
          onCancel={() => setConfirm(false)} onConfirm={() => { setConfirm(false); void apply(); }} />}
      </div>
    </div>, document.body,
  );
}
