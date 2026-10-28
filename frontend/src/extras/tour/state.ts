/** Ф23 Обучение в демо-режиме: шаги идут по ответам Stevens. */
import type { ChatResponse, RecordItem } from '../../api/types';
import { api, errorKey } from '../../api';
import { TOUR_STEPS } from '../../content/texts';
import { briefingStore, declineBriefing } from '../../state/briefing';
import { pressButton, resetSandbox, send } from '../../state/chat';
import { emitActivity, emitRecordsChanged, onAssistantResponse, onUiActivity } from '../../state/events';
import { clearFeed } from '../../state/feed';
import { notifyStore, showNotifyCard, viewNotifyCard } from '../../state/notify';
import { enterTourSandbox, returnToAccount } from '../../state/session';
import { createStore, store } from '../../state/store';
import { T } from '../../content/texts';
import { uuid } from '../../lib/uuid';
import { storage } from '../../storage';

type Kind = ChatResponse['kind'];
export type TourStatus = 'off' | 'offer' | 'running' | 'done';

/**
 * Какими ответами закрываются подсказки шагов обучения: последний ответ закрывает шаг.
 * Шаг 16 («Уведомление») и 17 («Календарь») закрывает сам фронт:
 * «Посмотреть» на карточке уведомления и перенос перетаскиванием в календаре.
 */
type Expect = (Kind | 'notify-viewed' | 'calendar-moved')[];
const EXPECT: Expect[] = [
  ['created'],
  ['created'],
  ['created'],
  ['list'],
  ['found'],
  ['clarify', 'created'],
  ['conflict', 'clarify', 'created'],
  ['completed'],
  ['found', 'updated', 'deleted', 'created'],
  ['confirm', 'created'],
  ['found'],
  ['created'],
  ['clarify'],
  ['person'],
  ['created', 'found'],
  ['notify-show', 'notify-viewed'],
  ['calendar-open', 'calendar-moved'],
] as Expect[];

export type TourStep = (typeof TOUR_STEPS)[number] & { expect: Expect };

export function tourSteps(): TourStep[] {
  return TOUR_STEPS.map((step, i) => ({ ...step, expect: EXPECT[i] }));
}

const STEP_DONE_MS = 1400;

/** account — предложение после регистрации; back — обучение запущено из аккаунта, по окончании вернём */
export const tourStore = createStore({
  status: 'off' as TourStatus, step: 0, sub: 0, stepDone: false, again: false, account: false, back: false, cleaning: false,
});

/** Аккаунт, из которого ушли в обучение на демо-данных */
let back: { login: string | null; userId: number | null } | null = null;

let doneTimer: ReturnType<typeof setTimeout> | undefined;
/** Напоминание из шага «Напоминание» — его же показываем в примере уведомления */
let exampleRecord: RecordItem | null = null;
let cleanup: Promise<boolean> | null = null;
let cleanupErrorTimer: ReturnType<typeof setTimeout> | undefined;

function cleanTourSandbox(): Promise<boolean> {
  if (cleanup) return cleanup;
  const clientId = storage.clientId();
  tourStore.set({ cleaning: true });
  store.set({ waiting: true });
  cleanup = (async () => {
    try {
      if (!clientId) throw new Error('Missing tour sandbox');
      await api.clearSandbox(clientId);
      clearTimeout(cleanupErrorTimer);
      store.set({ resetError: null });
      exampleRecord = null;
      notifyStore.set({ card: null, offer: null });
      if (store.get().mode === 'sandbox') {
        clearFeed();
        emitActivity('new-dialog');
        store.set({ messages: [], conversationId: uuid(), editing: null, unseen: 0 });
        emitRecordsChanged();
      }
      return true;
    } catch (error) {
      store.set({ resetError: { key: errorKey(error), until: Date.now() + 6000 } });
      clearTimeout(cleanupErrorTimer);
      cleanupErrorTimer = setTimeout(() => store.set({ resetError: null }), 6000);
      return false;
    } finally {
      tourStore.set({ cleaning: false });
      store.set({ waiting: false });
    }
  })().then((ok) => {
    if (!ok) cleanup = null;
    return ok;
  });
  return cleanup;
}

function next(): void {
  const { step } = tourStore.get();
  if (step + 1 >= tourSteps().length) {
    if (store.get().waiting || store.get().recording) {
      doneTimer = setTimeout(next, 100);
      return;
    }
    tourStore.set({ status: 'done', stepDone: false });
    void cleanTourSandbox();
  }
  else tourStore.set({ step: step + 1, sub: 0, stepDone: false });
}

function onResponse(kind: string): void {
  const t = tourStore.get();
  if (t.status !== 'running' || t.stepDone) return;
  const step = tourSteps()[t.step];
  if (!step) return;
  const expect = step.expect as string[];
  // Ответ, которым заканчивается шаг, засчитываем, даже если человек сказал всё одной фразой
  if (kind === expect[expect.length - 1]) {
    tourStore.set({ stepDone: true, sub: expect.length - 1 });
    clearTimeout(doneTimer);
    doneTimer = setTimeout(next, STEP_DONE_MS);
    return;
  }
  const at = expect.indexOf(kind, t.sub);
  if (at >= 0) tourStore.set({ sub: Math.min(at + 1, expect.length - 1) });
}

/** Пример уведомления в шаге «Уведомление»: запись из шага «Напоминание», без ожидания */
function showExample(): void {
  const record: RecordItem = exampleRecord ?? {
    id: null, type: 'reminder', text: 'Позвонить Ивану', date: null, time: null, date_kind: 'none', status: 'open',
    created_at: null, repeat: null, demo: false, marks: [], highlight: null,
  };
  showNotifyCard(record);
  onResponse('notify-show');
}

export async function startTour(): Promise<void> {
  if (tourStore.get().cleaning || store.get().waiting || store.get().recording) return;
  cleanup = null;
  storage.setTourSeen();
  storage.setTourOffer(null);
  clearTimeout(doneTimer);
  declineBriefing();
  const s = store.get();
  // Из аккаунта — на демо-данные песочницы, свои записи человека обучение не трогает
  if (s.mode === 'account' && !back) {
    back = { login: s.login, userId: s.userId };
    tourStore.set({ status: 'running', step: 0, sub: 0, stepDone: false, back: true });
    enterTourSandbox();
  }
  // С чистых демо-данных: иначе встречи из прошлого прохода сбили бы шаги про совпадение и правку
  await resetSandbox();
  exampleRecord = null;
  tourStore.set({ status: 'running', step: 0, sub: 0, stepDone: false, back: !!back });
}

export function declineTour(): void {
  storage.setTourSeen();
  const account = tourStore.get().account;
  storage.setTourOffer(null);
  dismissedFor = store.get().conversationId;
  entry = null;
  tourStore.set({ status: 'off', account: false });
  // После регистрации предлагаем один раз — подсказываем, где обучение искать потом
  if (account) sayLater();
}

function sayLater(): void {
  const id = uuid();
  store.set((s) => ({
    messages: [...s.messages, {
      kind: 'answer', id, restored: false, pressed: null, voice: false, edited: {}, flash: null,
      response: {
        message_id: id, kind: 'tour-later', text: T.tour_later, speech: null, records: [], nearest: null,
        total: null, awaiting_reply: false, buttons: [],
      },
    }],
  }));
}

export async function closeTour(): Promise<void> {
  if ((store.get().waiting && !tourStore.get().cleaning) || store.get().recording) return;
  clearTimeout(doneTimer);
  const { status } = tourStore.get();
  if ((status === 'running' || status === 'done') && !(await cleanTourSandbox())) return;
  dismissedFor = store.get().conversationId;
  tourStore.set({ status: 'off', stepDone: false, back: false });
  if (back) {
    const { login, userId } = back;
    back = null;
    returnToAccount(login, userId);
    emitRecordsChanged();
  }
}

export function skipStep(): void {
  clearTimeout(doneTimer);
  next();
}

/** Подсказка нажата: фраза уходит как текст, кнопка — нажимается под последним ответом */
export function sendHint(): void {
  const { step, sub } = tourStore.get();
  const subs = tourSteps()[step]?.subs;
  const hint = subs?.[Math.min(sub, subs.length - 1)];
  if (!hint) return;
  if ('say' in hint) {
    emitActivity('button-press');
    send(hint.say, 'text');
    return;
  }
  emitActivity('button-press');
  if (special(hint.press)) return;
  const found = lastButton(hint.press);
  if (found) pressButton(found.answerId, found.button, found.index);
}

/** Подсказки шагов, которые нажимают не кнопку под ответом: пример уведомления, «Посмотреть», календарь */
const SPECIAL = ['Показать пример', 'Посмотреть', 'Открыть календарь'];

function special(label: string): boolean {
  if (label === 'Показать пример') showExample();
  else if (label === 'Посмотреть') viewNotifyCard();
  else if (label === 'Открыть календарь') {
    store.set({ calendarOpen: true });
    onResponse('calendar-open');
  } else return false;
  return true;
}

/** Можно ли нажать подсказку-кнопку прямо сейчас */
export function hintReady(label: string): boolean {
  if (label === 'Посмотреть') return notifyStore.get().card !== null;
  if (SPECIAL.includes(label)) return true;
  return lastButton(label) !== null;
}

export function lastButton(label: string) {
  const messages = store.get().messages;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.kind !== 'answer') continue;
    const index = m.response.buttons.findIndex((b) => b.label === label);
    return index >= 0 && m.pressed === null ? { answerId: m.id, button: m.response.buttons[index], index } : null;
  }
  return null;
}

/** «Не сейчас» прячет предложение до следующего входа или нового диалога */
let dismissedFor: string | null = null;
/** Сколько сообщений человека было в диалоге при входе: плашка уходит с первым новым */
let entry: { conversationId: string; users: number } | null = null;

/**
 * Предложение над строкой ввода: в песочнице после входа или нового диалога, пока человек ничего не отправил.
 * Первый раз — «Показать, что я умею?», потом (новый диалог, сброс, повторный вход) — «Пройти обучение?»
 */
function maybeOffer(): void {
  const s = store.get();
  const status = tourStore.get().status;
  if (s.mode === 'account' && s.screen === 'app') {
    // В аккаунте обучение не предлагаем: оно в меню «Пройти обучение», на старте — примеры фраз
    if (storage.tourOffer() !== null) storage.setTourOffer(null);
    if (status === 'offer') tourStore.set({ status: 'off', account: false });
    return;
  }
  if (s.mode !== 'sandbox') {
    // Вышли из песочницы — обучение прячем
    if (status !== 'off') closeTour();
    return;
  }
  // Обучение из аккаунта: предложение песочницы не показываем
  if (back) return;
  const users = s.messages.filter((m) => m.kind === 'user').length;
  // Вход в приложение (и перезагрузка) или новый диалог — отсчёт сообщений заново
  if (s.screen !== 'app') entry = null;
  else if (!entry || entry.conversationId !== s.conversationId) entry = { conversationId: s.conversationId, users };
  const fresh = !!entry && users <= entry.users && s.conversationId !== dismissedFor;
  if (status === 'off' && fresh) tourStore.set({ status: 'offer', again: storage.tourSeen() });
  else if (status === 'offer' && !fresh) tourStore.set({ status: 'off' });
}

export function init(): void {
  onAssistantResponse((response, request) => {
    if (request.action?.id === 'briefing') return;
    const t = tourStore.get();
    if (t.status === 'running' && response.kind === 'created') {
      exampleRecord = response.records.find((r) => r.type === 'reminder' && r.id !== null) ?? exampleRecord;
    }
    onResponse(response.kind);
  });
  onUiActivity((kind) => {
    if (kind === 'notify-viewed' || kind === 'calendar-moved') onResponse(kind);
  });
  // Во время обучения плашку брифинга не показываем: после перехода в песочницу она бы посчиталась заново
  briefingStore.subscribe(() => {
    if (tourStore.get().status === 'running' && briefingStore.get().offer) declineBriefing();
  });
  store.subscribe(maybeOffer);
  maybeOffer();
}
