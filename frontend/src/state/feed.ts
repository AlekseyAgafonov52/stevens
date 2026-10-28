/** Сохранение и восстановление ленты */
import { storage } from '../storage';
import { store, type AnswerMessage, type FeedMessage, type UserMessage } from './store';

const MAX_SAVED = 50;
const MAX_AGE = 60 * 60 * 1000;

type Saved = UserMessage | AnswerMessage;

let previous: FeedMessage[] = store.get().messages;

export function feedKey(): string | null {
  const { mode, userId } = store.get();
  if (mode === 'sandbox') return 'sandbox';
  if (mode === 'account' && userId !== null) return `user:${userId}`;
  return null;
}

export function saveFeed(messages: FeedMessage[]): void {
  const key = feedKey();
  if (!key) return;
  const kept = messages.filter((m): m is Saved => m.kind === 'user' || m.kind === 'answer').slice(-MAX_SAVED);
  storage.setFeed(key, kept.length ? kept : null);
}

export function clearFeed(): void {
  const key = feedKey();
  if (key) storage.setFeed(key, null);
}

export function restoreFeed(): void {
  const key = feedKey();
  const saved = key ? storage.feed<Saved>(key) : null;
  if (!saved || Date.now() - saved.savedAt > MAX_AGE) {
    if (key && saved) storage.setFeed(key, null);
    store.set({ messages: [] });
    return;
  }
  const messages: FeedMessage[] = saved.messages.map((m) =>
    m.kind === 'answer' ? { ...m, restored: true, flash: null } : m,
  );
  let input = store.get().input;
  const last = messages[messages.length - 1];
  if (last && last.kind === 'user') {
    // Обновили страницу во время ожидания — текст обратно в поле
    messages.pop();
    if (last.source !== 'button') input = last.text;
  }
  previous = messages; // восстановленную ленту не пересохраняем: её возраст считается от последнего сообщения
  store.set({ messages, input });
}

/** Лента пишется после каждого сообщения */
store.subscribe(() => {
  const { messages, screen } = store.get();
  if (messages === previous) return;
  previous = messages;
  if (screen === 'app') saveFeed(messages);
});
