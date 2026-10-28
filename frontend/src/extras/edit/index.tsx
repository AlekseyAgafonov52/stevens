/** Д10: «Исправить» у созданной записи */
import type { RecordItem } from '../../api/types';
import { Pill } from '../../components/Pill';
import { T } from '../../content/texts';
import { applyEdit } from '../../state/chat';
import { emitActivity, emitRecordsChanged } from '../../state/events';
import { store, useApp, type AnswerMessage } from '../../state/store';
import { EditForm } from './EditForm';

export { EditForm };

export function EditButton({ message, isLast }: { message: AnswerMessage; isLast: boolean }) {
  const waiting = useApp((s) => s.waiting);
  const editing = useApp((s) => s.editing?.messageId === message.id);
  const record = message.response.records[0];
  const dimmed = !isLast || message.restored || waiting || message.pressed !== null;
  return (
    <Pill
      variant={dimmed ? 'dimmed' : 'primary'}
      disabled={editing}
      onClick={() => {
        emitActivity('button-press');
        if (record.id !== null) store.set({ editing: { messageId: message.id, recordId: record.id } });
      }}
    >
      {T.btn_edit}
    </Pill>
  );
}

export function FeedEditForm({ message, record }: { message: AnswerMessage; record: RecordItem }) {
  const close = () => store.set({ editing: null });
  return (
    <EditForm
      record={record}
      onCancel={close}
      onSaved={(saved) => {
        close();
        applyEdit(message.id, saved);
        emitActivity('edit-saved');
        emitRecordsChanged();
      }}
    />
  );
}
