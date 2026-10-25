/**
 * Вызов по имени «Стивенс» без кнопки микрофона. По умолчанию выключен, выбор хранится в браузере.
 * Слушаем фоном, только когда Stevens свободен: не пишем голос, не ждём ответ, вкладка открыта.
 * Пока он говорит вслух, тоже слушаем: «Стивс» обрывает озвучку и включает запись (кроме Safari),
 * даже при выключенном вызове по имени, если микрофон уже разрешён.
 * Сам себя он не позовёт: имя из его же фразы не ловим (voice.setEcho).
 */
import { storage } from '../storage';
import { voice } from '../voice';
import { isSpeaking, onSpeech, spokenText } from './events';
import { showMicProblem } from './micHelp';
import { createStore, store } from './store';

/** tip: после первой голосовой просьбы сами один раз открываем плашку у точки — чтобы узнали о функции */
export const wakeStore = createStore({ enabled: false, armed: false, tip: false });

/** Первая голосовая просьба ушла: Стивенс думает — самое время показать вызов по имени */
export function offerWakeTip(): void {
  if (wakeStore.get().enabled || storage.wakeTipSeen()) return;
  wakeStore.set({ tip: true });
}

function update(inGesture = false): void {
  const s = store.get();
  const free = s.screen === 'app' && !s.waiting && !s.recording && (!isSpeaking() || voice.canBargeIn())
    && (typeof document === 'undefined' || document.visibilityState === 'visible');
  // Перебить по имени можно и с выключенным вызовом: пока он говорит, а микрофон уже разрешён
  const bargeIn = isSpeaking() && voice.hasPermission();
  voice.setArmed((wakeStore.get().enabled || bargeIn) && free, inGesture);
}

export function setWakeWord(on: boolean): void {
  if (on && !voice.isSupported()) {
    showMicProblem('unsupported');
    return;
  }
  storage.setWakeWord(on);
  wakeStore.set({ enabled: on });
  update(true); // вызывается из нажатия на переключатель: Safari запускает распознавание только в нём
}

export function initWakeWord(): void {
  if (!voice.isSupported()) return;
  wakeStore.set({ enabled: storage.wakeWord() });
  store.subscribe(() => update());
  onSpeech(() => {
    voice.setEcho(isSpeaking() ? spokenText() : null);
    update();
  });
  voice.on('armed', (armed) => wakeStore.set({ armed }));
  voice.on('wakeDenied', () => {
    storage.setWakeWord(false);
    wakeStore.set({ enabled: false, armed: false });
    showMicProblem('denied');
  });
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => update());
  update();
}
