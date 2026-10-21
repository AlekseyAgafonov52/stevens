/**
 * Уведомления о напоминаниях и встречах, пока вкладка открыта.
 * После первого созданного напоминания под ответом — плашка «Прислать уведомление в 10:00?».
 * Напоминание приходит в своё время, встреча — за 10 минут. Тихий звук — двумя нотами.
 */
import { api } from '../api';
import type { RecordItem } from '../api/types';
import { storage } from '../storage';
import { onAssistantResponse, onRecordsChanged } from './events';
import { createStore, lastAnswerId, store } from './store';

export const notifyStore = createStore<{ offer: { messageId: string; time: string } | null }>({ offer: null });

const MEETING_EARLY_MIN = 10;
const RESCAN_MS = 30 * 60 * 1000;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

const supported = () => typeof window !== 'undefined' && 'Notification' in window;
export const notifyGranted = () => supported() && Notification.permission === 'granted';

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fireAt(record: RecordItem): number | null {
  if (!record.date || !record.time || record.status === 'done' || record.type === 'task') return null;
  const [h, m] = record.time.split(':').map(Number);
  const [y, mo, d] = record.date.split('-').map(Number);
  const at = new Date(y, mo - 1, d, h, m).getTime();
  return record.type === 'meeting' ? at - MEETING_EARLY_MIN * 60 * 1000 : at;
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

function fire(record: RecordItem, key: string): void {
  const fired = storage.notifyFired();
  if (fired.includes(key)) return;
  storage.setNotifyFired([...fired, key]);
  const body = record.type === 'meeting' ? `Через ${MEETING_EARLY_MIN} минут: ${record.text}` : record.text;
  try {
    const n = new Notification('Stevens', { body, tag: key });
    n.onclick = () => { window.focus(); n.close(); };
  } catch {
    /* браузер не дал показать */
  }
  chime();
}

/** Перестроить таймеры на сегодня и завтра */
export async function reschedule(): Promise<void> {
  if (!notifyGranted() || store.get().screen !== 'app') return;
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
  const fired = storage.notifyFired();
  for (const record of records) {
    const at = fireAt(record);
    if (at === null || record.id === null) continue;
    const key = `${record.id}@${record.date}T${record.time}`;
    const wait = at - Date.now();
    if (wait < -60 * 1000 || wait > 25 * 60 * 60 * 1000 || fired.includes(key)) continue;
    timers.set(key, setTimeout(() => fire(record, key), Math.max(0, wait)));
  }
}

export async function acceptOffer(): Promise<void> {
  notifyStore.set({ offer: null });
  if (!supported()) return;
  const permission = await Notification.requestPermission();
  if (permission === 'granted') void reschedule();
  else storage.setNotifyDeclined();
}

export function declineOffer(): void {
  notifyStore.set({ offer: null });
  storage.setNotifyDeclined();
}

export function initNotify(): void {
  if (!supported()) return;
  onAssistantResponse((response) => {
    if (response.kind !== 'created') return;
    if (notifyGranted()) {
      void reschedule();
      return;
    }
    if (Notification.permission !== 'default' || storage.notifyDeclined()) return;
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
    document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && void reschedule());
  }
  setInterval(() => void reschedule(), RESCAN_MS);
  let booted = false;
  store.subscribe(() => {
    if (!booted && store.get().screen === 'app') {
      booted = true;
      void reschedule();
    }
  });
}
