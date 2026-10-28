/** Напоминание в чате (после «Посмотреть» в пуше): «Готово» и «Напомнить позже».
 *  «Напомнить позже» сразу ставит напоминание через 15 минут — сайт можно закрыть, пуш придёт;
 *  ниже строка «Напомню в 22:45» и пилюли с другим временем: выбор заменяет прежнее. */
import { useState } from 'react';
import { api } from '../api';
import type { RecordItem } from '../api/types';
import { T, fill } from '../content/texts';
import { now } from '../lib/clock';
import { applyEdit, setHint } from '../state/chat';
import { emitActivity, emitRecordsChanged } from '../state/events';
import { snoozeRecord } from '../state/notify';
import type { AnswerMessage } from '../state/store';
import { Pill } from './Pill';

const FIRST_MIN = 15;
const OTHER = [
  { label: T.reminder_in_hour, minutes: 60 },
  { label: T.reminder_in_3_hours, minutes: 180 },
  { label: T.reminder_tomorrow, minutes: 24 * 60 },
];

type Props = { message: AnswerMessage; record: RecordItem };
type State = { step: 'idle' } | { step: 'closed' } | { step: 'snoozed'; at: Date; chosen: boolean };

function atText(at: Date): string {
  const time = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
  const today = now();
  return fill(at.toDateString() === today.toDateString() ? T.reminder_at : T.reminder_at_tomorrow, { time });
}

export function ReminderActions({ message, record }: Props) {
  const [state, setState] = useState<State>({ step: 'idle' });
  const [busy, setBusy] = useState(false);
  const id = record.id;
  if (id === null || message.restored || state.step === 'closed' || record.marks.includes('deleted')) return null;
  if (record.status === 'done' && state.step === 'idle') return null;

  const later = async (minutes: number, chosen: boolean) => {
    emitActivity('button-press');
    setBusy(true);
    try {
      await snoozeRecord(id, minutes);
      setState({ step: 'snoozed', at: new Date(now().getTime() + minutes * 60 * 1000), chosen });
    } catch {
      setHint('err_network');
    } finally {
      setBusy(false);
    }
  };
  const done = async () => {
    emitActivity('button-press');
    if (record.type === 'meeting') {
      setState({ step: 'closed' });
      return;
    }
    setBusy(true);
    try {
      applyEdit(message.id, await api.patchRecord(id, { status: 'done' }));
      emitRecordsChanged();
    } catch {
      setHint('err_network');
    } finally {
      setBusy(false);
    }
  };

  if (state.step === 'snoozed') {
    return (
      <>
        <div className="answer__caption">
          {atText(state.at)}{!state.chosen && ` ${T.reminder_other_time}`}
        </div>
        {!state.chosen && (
          <div className="answer__buttons">
            {OTHER.map((o) => (
              <Pill key={o.minutes} variant="secondary" disabled={busy} onClick={() => void later(o.minutes, true)}>{o.label}</Pill>
            ))}
          </div>
        )}
      </>
    );
  }
  return (
    <div className="answer__buttons">
      <Pill disabled={busy} onClick={() => void done()}>{record.type === 'meeting' ? T.reminder_ok : T.reminder_done}</Pill>
      <Pill variant="secondary" disabled={busy} onClick={() => void later(FIRST_MIN, false)}>{T.reminder_later}</Pill>
    </div>
  );
}
