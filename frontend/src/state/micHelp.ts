/**
 * Микрофон не работает — Стивенс говорит об этом в ленте и объясняет почему,
 * а не мелькает строкой статуса. Сообщение одно: только в ленте, над полем ввода его не дублируем.
 */
import { T } from '../content/texts';
import { uuid } from '../lib/uuid';
import { setHint } from './chat';
import { store } from './store';

export type MicProblem = 'denied' | 'no_mic' | 'unsupported' | 'service' | 'network' | 'failed' | 'silent' | 'no_words' | 'quiet';

export function showMicProblem(problem: MicProblem): void {
  const key = `mic_why_${problem}` as keyof typeof T;
  setHint(null);
  store.set((s) => ({ messages: [...s.messages, {
    kind: 'answer', id: uuid(), restored: false, pressed: null, voice: false, edited: {}, flash: null,
    response: { message_id: uuid(), kind: 'not_understood', text: String(T[key]), speech: null, records: [],
      nearest: null, total: null, awaiting_reply: false, buttons: [] },
  }] }));
}
