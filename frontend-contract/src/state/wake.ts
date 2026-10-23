/**
 * Вызов по имени «Стивенс» без кнопки микрофона. По умолчанию выключен, выбор хранится в браузере.
 * Слушаем фоном, только когда Stevens свободен: не пишем голос, не ждём ответ, вкладка открыта.
 * Пока он говорит вслух, тоже слушаем: «Стивс» обрывает озвучку и включает запись (кроме Safari).
 * Сам себя он не позовёт: имя из его же фразы не ловим (voice.setEcho).
 */
import { storage } from '../storage';
import { voice } from '../voice';
import { setHint } from './chat';
import { isSpeaking, onSpeech, spokenText } from './events';
import { createStore, store } from './store';

export const wakeStore = createStore({ enabled: false, armed: false });

function update(inGesture = false): void {
  const s = store.get();
  const free = s.screen === 'app' && !s.waiting && !s.recording && (!isSpeaking() || voice.canBargeIn())
    && (typeof document === 'undefined' || document.visibilityState === 'visible');
  voice.setArmed(wakeStore.get().enabled && free, inGesture);
}

export function setWakeWord(on: boolean): void {
  if (on && !voice.isSupported()) {
    setHint('voice_unsupported');
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
    setHint('voice_denied');
  });
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => update());
  update();
}
