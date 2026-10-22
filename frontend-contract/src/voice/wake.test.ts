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

test('«Стивенс, …, отмена» — ничего не уходит, снова слушаем имя', () => {
  vi.useFakeTimers();
  const events: string[] = [];
  const offFinal = voice.on('final', (t) => events.push(`final:${t}`));
  const offState = voice.on('state', (s) => events.push(s));
  voice.setArmed(true);
  vi.advanceTimersByTime(500);
  const rec = FakeRec.last!;
  rec.say('Стивенс, завтра в 10 созвон');
  rec.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'Стивенс, завтра в 10 созвон отмена' } }] });
  vi.advanceTimersByTime(3000);
  expect(events).toEqual(['recording', 'idle']);
  offFinal();
  offState();
  voice.setArmed(false);
  vi.useRealTimers();
});

test('своё имя из динамиков не зовёт Стивенса, после фразы фоновая запись начинается заново', async () => {
  vi.useFakeTimers();
  const events: string[] = [];
  const off = voice.on('wake', () => events.push('wake'));
  voice.setArmed(true);
  vi.advanceTimersByTime(500);
  const first = FakeRec.last!;
  voice.setEcho('Меня зовут Стивенс, я записал встречу');
  first.say('меня зовут Стивенс я записал');
  expect(events).toEqual([]);
  voice.setEcho(null);
  await vi.advanceTimersByTimeAsync(700);
  const second = FakeRec.last!;
  expect(second).not.toBe(first);
  second.say('Стив, отмени');
  expect(events).toEqual(['wake']);
  off();
  second.stop();
  voice.setArmed(false);
  await vi.advanceTimersByTimeAsync(700);
  vi.useRealTimers();
});

test('пока Стивенс говорит фразу без имени, «Стив» зовёт его', () => {
  vi.useFakeTimers();
  const events: string[] = [];
  const off = voice.on('wake', () => events.push('wake'));
  voice.setArmed(true);
  vi.advanceTimersByTime(500);
  voice.setEcho('Записал на завтра в 10');
  FakeRec.last!.say('записал на завтра Стив подожди');
  expect(events).toEqual(['wake']);
  voice.setEcho(null);
  off();
  FakeRec.last!.stop();
  voice.setArmed(false);
  vi.useRealTimers();
});
