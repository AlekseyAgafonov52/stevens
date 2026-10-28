/**
 * Уведомления о напоминаниях и встречах (контракт v1.5, Ф10).
 * После первого созданного напоминания под ответом — плашка «Прислать уведомление в 10:00?».
 * Напоминание приходит в своё время, встреча — за remind_before минут (по умолчанию 15).
 * Человек не на вкладке — пуш (с сервера через public/sw.js, а если вкладка открыта в фоне — ещё и
 * отсюда, с тем же tag, браузер склеит). На вкладке — пуша нет: сверху карточка уведомления
 * с «Посмотреть» и «Через 10 минут» и тихий звук двумя нотами; чат она не трогает.
 * «Посмотреть», клик по пушу или возврат на вкладку — в ленте сообщение Стивенса с записью.
 * Меню: «Уведомления» с галочкой.
 * Звонят только записи, заведённые человеком: демо-записи песочницы помечены demo.
 * У пуша кнопки «Посмотреть» (Стивенс присылает запись в чат) и «Через 10 минут» — см. public/sw.js.
 * Просроченное — вечерней сводкой с сервера; «Разобрать» — сообщение Стивенса (kind overdue),
 * у каждого дела кнопки «Перенести», «Выполнено», «Удалить» (components/OverdueActions.tsx).
 */
import { api } from '../api';
import { serverHas } from '../config/server';
import type { RecordItem } from '../api/types';
import { T } from '../content/texts';
import { timezone } from '../lib/clock';
import { pluralKey } from '../lib/dates';
import { uuid } from '../lib/uuid';
import { storage } from '../storage';
import { emitActivity, onAssistantResponse, onRecordsChanged } from './events';
import { setHint } from './chat';
import { createStore, lastAnswerId, store } from './store';

type PushMessage = { type?: string; recordId?: number; snoozed?: boolean; recordIds?: number[] };

export type NotifyCard = { record: RecordItem; title: string; tag: string };

export const notifyStore = createStore<{
  offer: { messageId: string; time: string } | null;
  card: NotifyCard | null;
  /** Пункт меню: включены ли уведомления (разрешение есть и человек их не выключал) */
  on: boolean;
}>({ offer: null, card: null, on: false });

const MEETING_EARLY_MIN = 15;
const CARD_MS = 10 * 1000;
const SNOOZE_MS = 10 * 60 * 1000;
const RESCAN_MS = 30 * 60 * 1000;
/** Насколько назад смотреть пропущенное при открытии */
const MISSED_MAX_MS = 12 * 60 * 60 * 1000;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

const supported = () => typeof window !== 'undefined' && 'Notification' in window;
export const notifyGranted = () => supported() && Notification.permission === 'granted';
/** Уведомления включены: разрешение дано и в меню их не выключали */
const notifyOn = () => notifyGranted() && !storage.notifyDeclined();
const refreshOn = () => notifyStore.set({ on: notifyOn() });
const earlyMin = (record: RecordItem) => record.remind_before ?? MEETING_EARLY_MIN;

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fireAt(record: RecordItem): number | null {
  if (!record.date || !record.time || record.demo || record.status === 'done' || record.type === 'task'
    || record.type === 'busy') return null;
  if (record.marks.includes('deleted')) return null;
  const [h, m] = record.time.split(':').map(Number);
  const [y, mo, d] = record.date.split('-').map(Number);
  const at = new Date(y, mo - 1, d, h, m).getTime();
  return record.type === 'meeting' ? at - earlyMin(record) * 60 * 1000 : at;
}

function chime(): void {
  try {
    const audio = new AudioContext();
    [660, 880].forEach((freq, i) => {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      const start = audio.currentTime + i * 0.18;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.5);
      osc.connect(gain).connect(audio.destination);
      osc.start(start);
      osc.stop(start + 0.55);
    });
    setTimeout(() => void audio.close().catch(() => undefined), 1200);
  } catch {
    /* без звука */
  }
}

const keyOf = (record: RecordItem) => `${record.id}@${record.date}T${record.time}`;

/** Системное уведомление через service worker: так оно не пропадает и склеивается с пушем.
 *  Заголовок — сам текст записи, без «Позвольте напомнить»; у встречи ниже — через сколько */
async function systemNotify(title: string, body: string, tag: string, recordId: number): Promise<void> {
  const options = {
    body, tag, icon: '/icon-192.png', badge: '/badge-96.png', requireInteraction: true, renotify: true,
    data: { recordId },
    // Кнопки обрабатывает public/sw.js; TypeScript о них пока не знает
    actions: [{ action: 'view', title: 'Посмотреть' }, { action: 'snooze', title: 'Через 10 минут' }],
  } as NotificationOptions;
  try {
    const registration = await navigator.serviceWorker?.getRegistration();
    if (registration) {
      await registration.showNotification(title, options);
      return;
    }
  } catch {
    /* попробуем напрямую */
  }
  try {
    // Без service worker кнопок не бывает — только клик
    const n = new Notification(title, { ...options, actions: undefined } as NotificationOptions);
    n.onclick = () => { window.focus(); n.close(); };
  } catch {
    /* браузер не дал показать */
  }
}

/** Сообщение Стивенса в ленте с карточками записей */
function remindInFeed(records: RecordItem[], text: string, kind = 'reminder'): void {
  if (store.get().screen !== 'app') return;
  store.set((s) => ({
    messages: [...s.messages, {
      kind: 'answer', id: uuid(), restored: false, pressed: null, voice: false, edited: {}, flash: null,
      response: {
        message_id: '', kind, text, speech: null, records, nearest: null,
        total: null, awaiting_reply: false, buttons: [],
      },
    }],
  }));
}

/** «Через 15 минут у вас встреча.» с числом минут этой встречи */
function meetingTitle(record: RecordItem): string {
  const minutes = earlyMin(record);
  const word = minutes === 30 ? 'полчаса' : minutes === 60 ? 'час' : `${minutes} ${{ one: 'минуту', few: 'минуты', many: 'минут' }[pluralKey(minutes)]}`;
  return T.remind_meeting.replace('15 минут', word);
}

function titleOf(record: RecordItem, again: boolean): string {
  if (again) return T.remind_again;
  return record.type === 'meeting' ? meetingTitle(record) : T.remind_one;
}

let cardTimer: ReturnType<typeof setTimeout> | undefined;

/** Карточка сверху на открытой вкладке: уходит сама через 10 с, чат, поле и микрофон не трогает */
export function showNotifyCard(record: RecordItem, again = false): void {
  clearTimeout(cardTimer);
  notifyStore.set({ card: { record, title: titleOf(record, again), tag: keyOf(record) } });
  chime();
  cardTimer = setTimeout(() => notifyStore.set({ card: null }), CARD_MS);
}

export function closeNotifyCard(): void {
  clearTimeout(cardTimer);
  notifyStore.set({ card: null });
}

/** «Посмотреть» на карточке: сообщение Стивенса с записью в ленте */
export function viewNotifyCard(): void {
  const card = notifyStore.get().card;
  closeNotifyCard();
  if (card) remindInFeed([card.record], card.title);
  emitActivity('notify-viewed');
}

/** «Через 10 минут» на карточке: откладывает сервер, если есть подписка, иначе сама вкладка */
export async function snoozeNotifyCard(): Promise<void> {
  const card = notifyStore.get().card;
  closeNotifyCard();
  const id = card?.record.id;
  if (id === undefined || id === null) return;
  await snoozeRecord(id, SNOOZE_MS / 60000);
}

/** Напомнить о записи ещё раз через minutes минут; новое время заменяет прежнее.
 *  Есть подписка — пуш придёт и при закрытом сайте, нет — откладывает сама вкладка */
export async function snoozeRecord(id: number, minutes: number): Promise<void> {
  try {
    const subscription = await (await navigator.serviceWorker?.getRegistration())?.pushManager.getSubscription();
    if (subscription) {
      await api.pushSnooze(subscription.endpoint, id, minutes);
      clearTimeout(snoozeTimers.get(id));
      snoozeTimers.delete(id);
      return;
    }
  } catch {
    /* сервер не принял — отложим здесь */
  }
  snoozeHere(id, minutes * 60 * 1000);
}

function fire(record: RecordItem, key: string): void {
  const fired = storage.notifyFired();
  if (fired.includes(key) || storage.notifyDeclined()) return;
  storage.setNotifyFired([...fired, key]);
  const title = titleOf(record, false);
  if (document.visibilityState === 'visible') showNotifyCard(record);
  else {
    remindInFeed([record], title); // вернётся на вкладку — увидит в ленте
    if (notifyGranted() && record.id !== null) {
      void systemNotify(record.text, record.type === 'meeting' ? title : '', key, record.id);
    }
  }
}

async function findRecord(id: number): Promise<RecordItem | null> {
  try {
    return await api.record(id);
  } catch {
    return null;
  }
}

/** «Посмотреть» в пуше: Стивенс присылает запись в чат (если только что не прислал её сам) */
async function showRecord(id: number, ring = false): Promise<void> {
  const record = await findRecord(id);
  if (!record) return;
  const last = store.get().messages.at(-1);
  if (!ring && last?.kind === 'answer' && last.response.kind === 'reminder' && last.response.records.some((r) => r.id === id)) return;
  const key = keyOf(record);
  const fired = storage.notifyFired();
  if (!fired.includes(key)) storage.setNotifyFired([...fired, key]);
  if (ring && record.status === 'done') return;
  if (ring) showNotifyCard(record, true);
  else remindInFeed([record], titleOf(record, false));
}

/** «Разобрать» в вечерней сводке: Стивенс присылает в чат дела, которые ещё не разобраны */
async function showDigest(ids: number[]): Promise<void> {
  const last = store.get().messages.at(-1);
  if (last?.kind === 'answer' && last.response.kind === 'overdue'
    && ids.every((id) => last.response.records.some((r) => r.id === id))) return;
  const found = await Promise.all(ids.map(findRecord));
  const records = found.filter((r): r is RecordItem => !!r && r.status !== 'done' && !r.marks.includes('deleted'));
  if (!records.length) return;
  remindInFeed(records, records.length === 1 ? T.remind_digest_one : T.remind_digest, 'overdue');
}

const snoozeTimers = new Map<number, ReturnType<typeof setTimeout>>();

/** Отложенное, когда пуша с сервера нет: откладывает сама вкладка */
function snoozeHere(id: number, wait = SNOOZE_MS): void {
  clearTimeout(snoozeTimers.get(id));
  snoozeTimers.set(id, setTimeout(() => {
    snoozeTimers.delete(id);
    void findRecord(id).then((record) => {
      if (!record || record.status === 'done' || record.marks.includes('deleted')) return;
      if (document.visibilityState === 'visible') showNotifyCard(record, true);
      else {
        remindInFeed([record], T.remind_again);
        if (notifyGranted()) void systemNotify(record.text, '', keyOf(record), id);
      }
    });
  }, wait));
}

/** Подписка на пуш с сервера: нужен service worker и разрешение на уведомления */
async function subscribePush(): Promise<boolean> {
  if (!notifyOn() || !('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  try {
    const registration = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const key = await api.pushKey();
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToBytes(key),
      });
    }
    await api.pushSubscribe(subscription.toJSON(), timezone());
    return true;
  } catch (error) {
    console.warn('Push subscription failed', error);
    /* без пушей: остаются уведомления, пока вкладка открыта */
    return false;
  }
}

function urlBase64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const base64 = (value + '='.repeat((4 - (value.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Что подошло, пока человека не было: одно сообщение Стивенса при открытии */
async function remindMissed(since: number | null, away = true): Promise<void> {
  if (since === null) return;
  const from = Math.max(since, Date.now() - MISSED_MAX_MS);
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);
  let records: RecordItem[];
  try {
    records = await api.records(isoDay(yesterday), isoDay(new Date()));
  } catch {
    return;
  }
  const fired = storage.notifyFired();
  const missed = records.filter((r) => {
    const at = fireAt(r);
    return at !== null && r.id !== null && at > from && at <= Date.now() && !fired.includes(keyOf(r));
  });
  if (!missed.length) return;
  storage.setNotifyFired([...fired, ...missed.map(keyOf)]);
  if (away) {
    remindInFeed(missed, missed.length === 1 ? titleOf(missed[0], false) : T.remind_one);
    return;
  }
  // Пуш пришёл, пока человек на вкладке: карточка сверху, а не сообщение в ленте
  missed.forEach((record) => showNotifyCard(record));
}

/** Перестроить таймеры на сегодня и завтра */
export async function reschedule(): Promise<void> {
  if (store.get().screen !== 'app') return;
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  let records: RecordItem[];
  try {
    records = await api.records(isoDay(now), isoDay(tomorrow));
  } catch {
    return;
  }
  timers.forEach((t) => clearTimeout(t));
  timers.clear();
  if (storage.notifyDeclined()) return;
  const fired = storage.notifyFired();
  for (const record of records) {
    const at = fireAt(record);
    if (at === null || record.id === null) continue;
    const key = keyOf(record);
    const wait = at - Date.now();
    if (wait < -60 * 1000 || wait > 25 * 60 * 60 * 1000 || fired.includes(key)) continue;
    timers.set(key, setTimeout(() => fire(record, key), Math.max(0, wait)));
  }
}

export async function acceptOffer(): Promise<void> {
  notifyStore.set({ offer: null });
  await enableNotify();
}

export function declineOffer(): void {
  notifyStore.set({ offer: null });
  storage.setNotifyDeclined();
  refreshOn();
}

/** Галочка «Уведомления» в меню ставится: разрешение браузера → подписка на пуш */
export async function enableNotify(): Promise<void> {
  // iOS разрешает запрос только из установленного приложения, не из вкладки Safari.
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  if (ios && !standalone) {
    setHint('install_safari');
    return;
  }
  if (!supported()) {
    console.warn('Notifications are unavailable', { secureContext: window.isSecureContext });
    return;
  }
  storage.clearNotifyDeclined();
  try {
    // До запроса разрешения нельзя ожидать сеть: Safari потеряет жест пользователя.
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    if (permission === 'granted') {
      void reschedule();
      const subscribed = await subscribePush();
      if (!subscribed) setHint('err_server');
      notifyStore.set({ on: subscribed });
    } else {
      storage.setNotifyDeclined();
      refreshOn();
    }
  } catch (error) {
    console.warn('Notification permission failed', error);
    notifyStore.set({ on: false });
    setHint('err_server');
  }
}

/** Галочка «Уведомления» в меню снимается: POST /api/push/unsubscribe и отписка в браузере */
export async function disableNotify(): Promise<void> {
  storage.setNotifyDeclined();
  timers.forEach((t) => clearTimeout(t));
  timers.clear();
  refreshOn();
  try {
    const subscription = await (await navigator.serviceWorker?.getRegistration())?.pushManager.getSubscription();
    if (subscription) {
      await api.pushUnsubscribe(subscription.endpoint).catch(() => undefined);
      await subscription.unsubscribe();
    }
  } catch {
    /* отписка в браузере не удалась — сервер уже не шлёт */
  }
}

export async function handlePushMessage(data: PushMessage): Promise<void> {
  const id = typeof data.recordId === 'number' ? data.recordId : null;
  if (data.type === 'stevens-digest') await showDigest((data.recordIds ?? []).filter(Number.isInteger));
  else if (data.type === 'stevens-reminder' && data.snoozed && id !== null) await showRecord(id, true);
  else if (data.type === 'stevens-reminder') await remindMissed(Date.now() - 15 * 60 * 1000, false);
  else if (data.type === 'stevens-open' && id !== null) await showRecord(id);
  else if (data.type === 'stevens-snooze' && id !== null) snoozeHere(id);
}

export function initNotify(): void {
  refreshOn();
  // Время прошлого визита — до того, как его отметит брифинг
  const previous = storage.lastSeen();
  onAssistantResponse((response) => {
    // Перенос, удаление и отметка фразой тоже меняют, когда звонить
    if (response.kind === 'updated' || response.kind === 'deleted' || response.kind === 'completed') {
      void reschedule();
      return;
    }
    if (response.kind !== 'created') return;
    void reschedule();
    if (notifyGranted()) return;
    if (!serverHas('f10') || !supported() || Notification.permission !== 'default' || storage.notifyDeclined()) return;
    const record = response.records.find((r) => fireAt(r) !== null && (fireAt(r) ?? 0) > Date.now());
    const messageId = lastAnswerId(store.get().messages);
    if (record?.time && messageId) notifyStore.set({ offer: { messageId, time: record.time } });
  });
  onRecordsChanged(() => void reschedule());
  store.subscribe(() => {
    const offer = notifyStore.get().offer;
    if (offer && lastAnswerId(store.get().messages) !== offer.messageId) notifyStore.set({ offer: null });
  });
  if (typeof document !== 'undefined') {
    let hiddenAt: number | null = null;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        hiddenAt = Date.now();
        return;
      }
      // Пока вкладка была в фоне, таймеры могли проспать (сон компьютера) — досказываем
      void remindMissed(hiddenAt).then(() => reschedule());
    });
  }
  setInterval(() => void reschedule(), RESCAN_MS);
  // Пуш пришёл, когда человек на вкладке: пуша не было, показываем сообщение (если таймер его ещё не показал)
  navigator.serviceWorker?.addEventListener('message', (event: MessageEvent<PushMessage>) => {
    void handlePushMessage(event.data ?? {});
  });
  // Приложение открыли кнопкой «Посмотреть» из пуша: /?remind=<номер записи>; «Разобрать» из сводки: /?overdue=1,2,3
  const params = new URLSearchParams(typeof location !== 'undefined' ? location.search : '');
  const remindParam = params.get('remind');
  const overdueParam = params.get('overdue');
  let remindId = remindParam && /^\d+$/.test(remindParam) ? Number(remindParam) : null;
  let digestIds = (overdueParam ?? '').split(',').filter((v) => /^\d+$/.test(v)).map(Number);
  if (remindParam !== null || overdueParam !== null) {
    const url = new URL(location.href);
    url.searchParams.delete('remind');
    url.searchParams.delete('overdue');
    history.replaceState(history.state, '', url);
  }
  let booted = false;
  let owner: string | null = null;
  store.subscribe(() => {
    const { screen, mode, userId } = store.get();
    if (screen !== 'app') return;
    if (!booted) {
      booted = true;
      const id = remindId;
      const digest = digestIds;
      remindId = null;
      digestIds = [];
      void remindMissed(previous)
        .then(() => (id === null ? undefined : showRecord(id)))
        .then(() => (digest.length ? showDigest(digest) : undefined));
    }
    // Вошли в аккаунт или вернулись в песочницу — пуши и таймеры переезжают к новому владельцу
    if (owner !== `${mode}:${userId}`) {
      owner = `${mode}:${userId}`;
      void reschedule();
      void subscribePush();
    }
  });
}
