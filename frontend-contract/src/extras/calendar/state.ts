/** Состояние панели календаря: месяц, выбранный день, записи сетки. */
import { api, ApiFailure } from '../../api';
import type { RecordItem } from '../../api/types';
import { now } from '../../lib/clock';
import { isoDate } from '../../lib/dates';
import { sessionExpired } from '../../state/session';
import { createStore } from '../../state/store';
import { gridRange } from './month';

const today = () => now();
export const calendar = createStore({
  year: today().getFullYear(),
  month: today().getMonth(),
  selected: isoDate(today()),
  records: [] as RecordItem[],
  loading: true,
  failed: false,
  version: 0,
});

let loadToken = 0;
export async function load(): Promise<void> {
  const { year, month } = calendar.get();
  const token = ++loadToken;
  calendar.set({ loading: true, failed: false });
  try {
    const { from, to } = gridRange(year, month);
    const records = await api.records(from, to);
    if (token === loadToken) calendar.set({ records, loading: false });
  } catch (error) {
    if (error instanceof ApiFailure && error.error.type === 'unauthorized') {
      sessionExpired();
      return;
    }
    if (token === loadToken) calendar.set({ loading: false, failed: true });
  }
}


export function shiftMonth(delta: number, selectDay?: string) {
  const { year, month } = calendar.get();
  const date = new Date(year, month + delta, 1);
  calendar.set({ year: date.getFullYear(), month: date.getMonth(), ...(selectDay ? { selected: selectDay } : {}) });
  void load();
}
