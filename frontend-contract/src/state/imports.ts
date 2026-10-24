/** Результат импорта и его отмена в ленте (§9 Ф26). */
import { api, ApiFailure, errorKey } from '../api';
import type { TransferResult } from '../api/types';
import { T, fill } from '../content/texts';
import { uuid } from '../lib/uuid';
import { setHint } from './chat';
import { emitActivity, emitRecordsChanged } from './events';
import { sessionExpired } from './session';
import { store, type AnswerMessage } from './store';

function message(text: string, kind: 'updated' | 'deleted', undoId?: string): AnswerMessage {
  return { kind: 'answer', id: uuid(), restored: false, pressed: null, voice: false, edited: {}, flash: null,
    ...(undoId ? { importUndo: undoId } : {}),
    response: { message_id: uuid(), kind, text, speech: null, records: [], nearest: null, total: null,
      awaiting_reply: false, buttons: [] } };
}

export function showImport(result: TransferResult): void {
  store.set((s) => ({ messages: [...s.messages, message(fill(T.transfer_done, {
    add: result.add, update: result.update, delete: result.delete,
  }), 'updated', result.undo_id)] }));
  emitRecordsChanged();
}

export async function undoImport(id: string): Promise<void> {
  if (store.get().waiting || store.get().recording) return;
  store.set({ waiting: true });
  emitActivity('request-start');
  try {
    await api.undoImport(id);
    store.set((s) => ({ messages: [...s.messages, message(T.transfer_undone, 'deleted')] }));
    emitRecordsChanged();
  } catch (error) {
    if (error instanceof ApiFailure && error.error.type === 'unauthorized') sessionExpired();
    else setHint(errorKey(error));
  } finally {
    store.set({ waiting: false });
    emitActivity('request-end');
  }
}
