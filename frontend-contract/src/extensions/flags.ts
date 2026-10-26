/** Точки расширения без разметки — 09-extensions.md, раздел 2. Флаги проверяются только здесь и в points.tsx. */
import type { RecordItem } from '../api/types';
import { features } from '../config/features';
import { serverHas } from '../config/server';

/** Состояние «Удалено» (Д2 или Д10): вид приглушённой карточки */
export function recordCardDeleted(record: RecordItem): boolean {
  return (features.d2_delete || features.d10_undo) && record.marks.includes('deleted');
}

/** Д14: вместо точек ждёт персонаж — только текст через 8 с */
export function waitingWithDots(): boolean {
  return !features.d14_mascot || !serverHas('f22');
}

/** Д14: запас ленты снизу */
export function feedBottomInsetClass(): string {
  return features.d14_mascot && serverHas('f22') ? 'feed--with-mascot' : '';
}

/** Допы без своего места на экране: Д12 озвучка, Д13 автослушание, CSS персонажа; Д15 — подписка на ответы */
export function initExtras(): void {
  if (features.d12_speech) void import('../extras/speech').then((m) => m.init());
  if (features.d13_autolisten) void import('../extras/autolisten').then((m) => m.init());
  if (features.d14_mascot) void import('../styles/mascot.css');
  if (features.d15_tour) void import('../extras/tour/state').then((m) => m.init());
}
