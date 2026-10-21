/**
 * Утренний брифинг: при первом открытии за день Stevens сам пишет план дня
 * и предупреждает о плотных местах (действие briefing, без сообщения пользователя).
 */
import { storage } from '../storage';
import { sendQuiet } from './chat';
import { store } from './store';

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

let sent: string | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;

const ready = () => {
  const s = store.get();
  return s.screen === 'app' && s.server === 'ok' && !!s.conversationId && !s.waiting && !s.recording;
};

/** Ждём секунду после входа: лента и диалог должны успеть восстановиться, иначе брифинг затрётся */
function tryBriefing(): void {
  if (timer || !ready()) return;
  timer = setTimeout(() => {
    timer = undefined;
    if (ready()) sendBriefing();
  }, 1000);
}

function sendBriefing(): void {
  const day = today();
  if (sent === day || storage.briefingDay() === day) return;
  // Отмечаем до отправки: sendQuiet меняет store, и подписка вызовет нас снова
  sent = day;
  storage.setBriefingDay(day);
  if (!sendQuiet({ id: 'briefing' })) {
    sent = null;
    storage.setBriefingDay('');
  }
}

export function initBriefing(): void {
  store.subscribe(tryBriefing);
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && tryBriefing());
  }
}
