/** Ответ ассистента: текст, карточки, «Ближайшее», кнопки. */
import { useState } from 'react';
import type { RecordItem } from '../api/types';
import { T, fill } from '../content/texts';
import { dayTitle, groupByDay, groupByTense, splitPast } from '../lib/dates';
import { pressButton } from '../state/chat';
import { useApp, type AnswerMessage } from '../state/store';
import { AnswerExtraButtons, RecordCardOverride, cardEditHandler } from '../extensions/points';
import { NotifyOffer } from './NotifyOffer';
import { OverdueActions } from './OverdueActions';
import { ReminderActions } from './ReminderActions';
import { undoImport } from '../state/imports';
import { Pill, type PillVariant } from './Pill';
import { RecordCard } from './RecordCard';

const PAGE = { list: { first: 20, step: 20 }, found: { first: 5, step: 10 } } as const;

type Props = { message: AnswerMessage; isLast: boolean };

export function Answer({ message, isLast }: Props) {
  const { response } = message;
  const waiting = useApp((s) => s.waiting);
  const editing = useApp((s) => s.editing);
  const paging =
    response.kind === 'list' ? PAGE.list : response.kind === 'found' || response.kind === 'person' ? PAGE.found : null;
  const [shown, setShown] = useState<number>(paging ? paging.first : Infinity);
  const fresh = !message.restored;

  const given = response.records.map((r) => (r.id !== null && message.edited[r.id]) || r);
  // В списке на период уже прошедшее — отдельно, после того, что впереди
  const split = response.kind === 'list' ? splitPast(given) : null;
  const records = split ? [...split.ahead, ...split.past] : given;
  const pastIds = new Set(split?.past.map((r) => r));
  const visible = records.slice(0, shown);
  const rest = records.length - visible.length;

  const card = (record: RecordItem, withDate: boolean, index: number) => {
    const isEditing = !!editing && editing.messageId === message.id && editing.recordId === record.id;
    const flash = message.flash && message.flash.id === record.id;
    if (isEditing) {
      return <RecordCardOverride key={`${record.id}-${index}`} message={message} record={record} editing />;
    }
    const view = (
      <RecordCard
        key={`${record.id ?? 'd'}-${index}-${flash ? message.flash?.at : ''}`}
        record={flash ? { ...record, marks: [...record.marks, 'new'] } : record}
        withDate={withDate}
        isNew={(fresh && record.marks.includes('new')) || !!flash}
        onClick={cardEditHandler(message, record, isLast && !message.restored && !waiting && !editing)}
      />
    );
    if (response.kind !== 'overdue' && response.kind !== 'reminder') return view;
    return (
      <div className="overdue-item" key={`${record.id ?? 'd'}-${index}`}>
        {view}
        {response.kind === 'overdue'
          ? <OverdueActions message={message} record={record} />
          : <ReminderActions message={message} record={record} />}
      </div>
    );
  };

  /** «Что ты умеешь?» и «Не понял»: кнопки — примеры фраз, тихие, как на стартовом экране */
  const examples = response.kind === 'help' || response.kind === 'not_understood';

  const buttonVariant = (index: number, style: string | undefined): PillVariant => {
    if (message.pressed === index) return 'selected';
    if (!isLast || message.restored || message.pressed !== null || waiting) return 'dimmed';
    return style === 'secondary' ? 'secondary' : 'primary';
  };

  return (
    <div className={`answer ${fresh ? 'anim-appear' : ''}`}>
      {response.text && <div className="answer__text">{response.text}</div>}

      {visible.length > 0 && (
        <div className="answer__cards">
          {response.kind === 'list'
            ? [visible.filter((r) => !pastIds.has(r)), visible.filter((r) => pastIds.has(r))].map((part, pi) =>
                part.length > 0 && (
                  <div className={pi ? 'list-past' : 'list-ahead'} key={pi}>
                    {pi > 0 && <div className="list-past__title">{T.group_past_list}</div>}
                    {groupByDay(part).map((group, gi) => (
                      <div className="day-group" key={gi}>
                        <div className="day-title">{group.date ? dayTitle(group.date) : T.group_no_date}</div>
                        {group.records.map((r, i) => card(r, false, pi * 100000 + gi * 1000 + i))}
                      </div>
                    ))}
                  </div>
                ))
            : response.kind === 'person'
              ? groupByTense(visible).map((group, gi) => (
                  <div className="day-group" key={gi}>
                    <div className="day-title">{group.ahead ? T.group_ahead : T.group_past}</div>
                    {group.records.map((r, i) => card(r, true, gi * 1000 + i))}
                  </div>
                ))
              : visible.map((r, i) => card(r, true, i))}
        </div>
      )}

      {paging && rest > 0 && (
        <div>
          <Pill variant="secondary" onClick={() => setShown((n) => n + paging.step)}>
            {fill(T.show_more, { count: Math.min(rest, paging.step) })}
          </Pill>
        </div>
      )}
      {response.kind === 'found' && response.total !== null && response.total > response.records.length && (
        <div className="answer__caption">{fill(T.limit_caption, { shown: response.records.length, total: response.total })}</div>
      )}

      {response.nearest && (
        <div className="answer__cards">
          <div className="day-title">{T.label_nearest}</div>
          <RecordCard record={response.nearest} withDate />
        </div>
      )}

      {(response.buttons.length > 0 || (isLast && response.kind === 'created')) && (
        <div className="answer__buttons">
          <AnswerExtraButtons message={message} isLast={isLast} />
          {response.buttons.map((button, index) => (
            <Pill
              key={index}
              variant={buttonVariant(index, button.style)}
              className={examples ? 'pill--example' : ''}
              onClick={() => pressButton(message.id, button, index)}
            >
              {button.label}
            </Pill>
          ))}
        </div>
      )}
      {isLast && response.kind === 'created' && <NotifyOffer messageId={message.id} />}
      {isLast && !message.restored && message.importUndo && (
        <div className="answer__buttons"><Pill variant="secondary" disabled={waiting}
          onClick={() => void undoImport(message.importUndo!)}>{T.btn_restore}</Pill></div>
      )}
    </div>
  );
}
