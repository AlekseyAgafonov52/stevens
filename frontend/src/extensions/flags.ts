/** Точки расширения без разметки: что зависит от фич сервера (GET /api/health). */
import type { RecordItem } from '../api/types';
import { serverHas } from '../config/server';

/** Состояние «Удалено»: вид приглушённой карточки */
export function recordCardDeleted(record: RecordItem): boolean {
  return record.marks.includes('deleted');
}

/** Д14: вместо точек ждёт персонаж — только текст через 8 с */
export function waitingWithDots(): boolean {
  return !serverHas('f22');
}

/** Д14: запас ленты снизу */
export function feedBottomInsetClass(): string {
  return serverHas('f22') ? 'feed--with-mascot' : '';
}

/** Допы без своего места на экране: Д12 озвучка, Д13 автослушание, CSS персонажа; Д15 — подписка на ответы */
export function initExtras(): void {
  void import('../extras/speech').then((m) => m.init());
  void import('../extras/autolisten').then((m) => m.init());
  void import('../styles/mascot.css');
  void import('../extras/tour/state').then((m) => m.init());
}
