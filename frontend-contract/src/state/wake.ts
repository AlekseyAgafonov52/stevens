/**
 * Вызов по имени «Стивенс» без кнопки микрофона. По умолчанию выключен, выбор хранится в браузере.
 * Слушаем фоном, только когда Stevens свободен: не пишем голос, не ждём ответ, не говорим вслух,
 * вкладка открыта. Иначе он услышал бы сам себя или перебил запрос.
 */
import { storage } from '../storage';
import { voice } from '../voice';
import { setHint } from './chat';
import { isSpeaking, onSpeech } from './events';
import { createStore, store } from './store';

export const wakeStore = createStore({ enabled: false, armed: false });

function update(): void {
  const s = store.get();
  const free = s.screen === 'app' && !s.waiting && !s.recording && !isSpeaking()
    && (typeof document === 'undefined' || document.visibilityState === 'visible');
  voice.setArmed(wakeStore.get().enabled && free);
}

export function setWakeWord(on: boolean): void {
  if (on && !voice.isSupported()) {
    setHint('voice_unsupported');
    return;
  }
  storage.setWakeWord(on);
  wakeStore.set({ enabled: on });
  update();
}

export function initWakeWord(): void {
  if (!voice.isSupported()) return;
  wakeStore.set({ enabled: storage.wakeWord() });
  store.subscribe(update);
  onSpeech(update);
  voice.on('armed', (armed) => wakeStore.set({ armed }));
  voice.on('wakeDenied', () => {
    storage.setWakeWord(false);
    wakeStore.set({ enabled: false, armed: false });
    setHint('voice_denied');
  });
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', update);
  update();
}
