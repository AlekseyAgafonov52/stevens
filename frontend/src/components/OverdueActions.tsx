/** Вечерняя сводка о просроченном: под каждым делом «Перенести», «Выполнено», «Удалить».
 *  «Перенести» — «На завтра» (то же время) или «Другое время» (форма правки на месте карточки). */
import { useState } from 'react';
import { api } from '../api';
import type { RecordItem } from '../api/types';
import { T } from '../content/texts';
import { now } from '../lib/clock';
import { isoDate, isPast } from '../lib/dates';
import { applyEdit, setHint } from '../state/chat';
import { emitActivity, emitRecordsChanged } from '../state/events';
import { store, useApp, type AnswerMessage } from '../state/store';
import { Pill } from './Pill';

type Props = { message: AnswerMessage; record: RecordItem };

export function OverdueActions({ message, record }: Props) {
  const [moving, setMoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const editing = useApp((s) => !!s.editing);
  const id = record.id;
  if (id === null || record.status === 'done' || record.marks.includes('deleted') || !isPast(record)) return null;

  const run = async (action: () => Promise<RecordItem>) => {
    emitActivity('button-press');
    setBusy(true);
    try {
      applyEdit(message.id, await action());
      emitRecordsChanged();
    } catch {
      setHint('err_network');
    } finally {
      setBusy(false);
      setMoving(false);
    }
  };
  const tomorrow = () => {
    const day = now();
    day.setDate(day.getDate() + 1);
    return api.patchRecord(id, { date: isoDate(day) });
  };
  const remove = async () => {
    await api.deleteRecord(id);
    return { ...record, marks: [...record.marks, 'deleted' as const] };
  };
  const off = busy || editing;

  return (
    <div className="answer__buttons overdue-actions">
      {moving ? (
        <>
          <Pill disabled={off} onClick={() => void run(tomorrow)}>{T.overdue_tomorrow}</Pill>
          <Pill variant="secondary" disabled={off} onClick={() => {
            emitActivity('button-press');
            setMoving(false);
            store.set({ editing: { messageId: message.id, recordId: id } });
          }}>{T.overdue_other_time}</Pill>
        </>
      ) : (
        <>
          <Pill variant="secondary" disabled={off} onClick={() => setMoving(true)}>{T.overdue_move}</Pill>
          <Pill disabled={off} onClick={() => void run(() => api.patchRecord(id, { status: 'done' }))}>{T.overdue_done}</Pill>
          <Pill variant="secondary" disabled={off} onClick={() => void run(remove)}>{T.overdue_delete}</Pill>
        </>
      )}
    </div>
  );
}
