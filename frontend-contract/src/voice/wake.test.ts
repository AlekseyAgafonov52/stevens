import { beforeAll, expect, test, vi } from 'vitest';
import { voice } from './index';

type Handler = ((e: unknown) => void) | null;
class FakeRec {
  static last: FakeRec | null = null;
  lang = ''; interimResults = false; continuous = false;
  onresult: Handler = null; onerror: Handler = null; onend: (() => void) | null = null; onstart: (() => void) | null = null;
  constructor() { FakeRec.last = this; }
  start() {}
  stop() { this.onend?.(); }
  abort() { this.onend?.(); }
  say(text: string) {
    this.onresult?.({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript: text } }] });
  }
}

beforeAll(() => {
  // Тесты идут без браузера: подставляем распознавание и микрофон
  const g = globalThis as unknown as Record<string, unknown>;
  g.window = { SpeechRecognition: FakeRec };
  Object.defineProperty(globalThis, 'navigator', {
    value: { mediaDevices: { getUserMedia: () => Promise.reject(new Error('no')) } },
    configurable: true,
  });
});

test('после имени запись становится обычной, имя в текст не попадает', () => {
  vi.useFakeTimers();
  const events: string[] = [];
  voice.on('wake', () => events.push('wake'));
  voice.on('final', (t) => events.push(`final:${t}`));
  voice.setArmed(true);
  vi.advanceTimersByTime(500);
  const rec = FakeRec.last!;
  rec.say('ну вот');
  expect(events).toEqual([]);
  rec.say('ну вот Стивенсон, завтра в 10 созвон с Иваном');
  expect(events).toEqual(['wake']);
  vi.advanceTimersByTime(2000);
  expect(events).toEqual(['wake', 'final:завтра в 10 созвон с Иваном']);
  voice.setArmed(false);
  vi.useRealTimers();
});
