/** Одно хранилище состояния приложения. */
import { useSyncExternalStore } from 'react';
import type { ChatRequest, ChatResponse, RecordItem } from '../api/types';

export type UserMessage = { kind: 'user'; id: string; text: string; source: ChatRequest['source'] };
export type AnswerMessage = {
  /** Локальная кнопка отмены импорта v1.6: отдельный REST-стык import/undo. */
  importUndo?: string;
  kind: 'answer';
  id: string;
  response: ChatResponse;
  /** Восстановлено из хранилища: только для чтения, без подсветки и анимаций */
  restored: boolean;
  /** Индекс нажатой кнопки ответа */
  pressed: number | null;
  /** Ответ на голосовое — для Д12, Д13 */
  voice: boolean;
  /** Правки записей через форму (Д10): id → запись */
  edited: Record<number, RecordItem>;
  /** Запись, подсвечиваемая после сохранения формы */
  flash: { id: number; at: number } | null;
};
export type PendingMessage = { kind: 'pending'; id: string; request: ChatRequest; startedAt: number };
export type ErrorMessage = { kind: 'error'; id: string; text: string; request: ChatRequest };
export type FeedMessage = UserMessage | AnswerMessage | PendingMessage | ErrorMessage;

export type Screen = 'boot' | 'auth' | 'app';
export type Mode = 'sandbox' | 'account';
export type Server = 'ok' | 'waking' | 'down';

export type AppState = {
  screen: Screen;
  mode: Mode | null;
  login: string | null;
  userId: number | null;
  /** Почему открыт экран входа */
  authNotice: 'expired' | null;
  server: Server;
  conversationId: string;
  messages: FeedMessage[];
  input: string;
  waiting: boolean;
  recording: boolean;
  /** Подсказка в строке статуса: ключ texts.ts */
  hint: { key: string; until: number } | null;
  /** Ошибка сброса песочницы, 6 с */
  resetError: { key: string; until: number } | null;
  calendarOpen: boolean;
  /** Открытая форма правки в ленте: id сообщения и записи */
  editing: { messageId: string; recordId: number } | null;
  /** Счётчик «пришло новое, пока человек выше» */
  unseen: number;
};

type Listener = () => void;

export function createStore<S>(initial: S) {
  let state = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => state,
    set(patch: Partial<S> | ((s: S) => Partial<S>)) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      state = { ...state, ...next };
      listeners.forEach((l) => l());
    },
    subscribe(listener: Listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export const store = createStore<AppState>({
  screen: 'boot',
  mode: null,
  login: null,
  userId: null,
  authNotice: null,
  server: 'ok',
  conversationId: '',
  messages: [],
  input: '',
  waiting: false,
  recording: false,
  hint: null,
  resetError: null,
  calendarOpen: false,
  editing: null,
  unseen: 0,
});

export function useApp<T>(select: (s: AppState) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(store.get()));
}

export function lastAnswerId(messages: FeedMessage[]): string | null {
  const last = messages[messages.length - 1];
  return last && last.kind === 'answer' ? last.id : null;
}
