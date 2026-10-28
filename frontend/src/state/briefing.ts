/**
 * План на сегодня (брифинг) — по предложению, не сам. Предлагаем, если на сегодня есть дела,
 * а человек не заходил несколько часов: в пустом чате вместо примеров, в непустом — в конце ленты.
 * «Да» — действие briefing без сообщения пользователя, «Нет» — плашка уходит до следующего долгого перерыва.
 */
import { useSyncExternalStore } from 'react';
import { api } from '../api';
import { storage } from '../storage';
import { sendQuiet } from './chat';
import { createStore, store } from './store';

/** Сколько не заходил, чтобы предложить план */
const AWAY_MS = 3 * 60 * 60 * 1000;
/** Как часто отмечаем «был здесь», пока вкладка открыта */
const SEEN_EVERY_MS = 60 * 1000;

export const briefingStore = createStore<{ offer: { count: number } | null }>({ offer: null });

export function useBriefingOffer() {
  const offer = useSyncExternalStore(briefingStore.subscribe, briefingStore.get).offer;
  return offer;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function markSeen(): void {
  storage.setLastSeen(Date.now());
}

let checking = false;

/** Чьи дела считаем: песочница или аккаунт. Сменился — старое число чужое */
function ownerKey(): string | null {
  const s = store.get();
  if (s.screen !== 'app' || s.server !== 'ok') return null;
  return s.mode === 'account' ? `a:${s.userId ?? ''}` : 'sandbox';
}

/** Был долгий перерыв — смотрим, есть ли дела на сегодня */
async function checkOffer(awaySince: number | null): Promise<void> {
  if (checking || (awaySince !== null && Date.now() - awaySince < AWAY_MS)) return;
  checking = true;
  const owner = ownerKey();
  try {
    const day = today();
    const records = await api.records(day, day);
    // Считаем как сервер в брифинге: без выполненных, занятости и заметок
    const count = records.filter((r) => r.status !== 'done' && !r.marks.includes('deleted')
      && r.type !== 'busy' && r.type !== 'note').length;
    // Пока ждали ответ, вошли в другой аккаунт — это число уже не его
    if (count > 0 && ownerKey() === owner) briefingStore.set({ offer: { count } });
  } catch {
    /* без предложения */
  } finally {
    checking = false;
  }
}

export function acceptBriefing(): void {
  if (sendQuiet({ id: 'briefing' })) briefingStore.set({ offer: null });
}

export function declineBriefing(): void {
  briefingStore.set({ offer: null });
}

export function initBriefing(): void {
  // Время прошлого визита берём до того, как отметим нынешний
  const previous = storage.lastSeen();
  let started = false;
  let owner: string | null = null;
  store.subscribe(() => {
    const key = ownerKey();
    if (key === owner || (key === null && store.get().screen === 'app')) return;
    // Вышли или зашли под другим: плашка с прошлыми делами уходит, считаем заново
    const first = owner === null && !started;
    owner = key;
    briefingStore.set({ offer: null });
    if (key === null) return;
    void checkOffer(first ? previous : null);
    if (started) return;
    started = true;
    markSeen();
    setInterval(() => document.visibilityState === 'visible' && markSeen(), SEEN_EVERY_MS);
  });
  if (typeof document === 'undefined') return;
  let hiddenAt: number | null = null;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      hiddenAt = Date.now();
      markSeen();
    } else if (started) {
      void checkOffer(hiddenAt);
      markSeen();
    }
  });
}
