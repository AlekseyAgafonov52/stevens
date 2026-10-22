/** Д12: озвучка ответов на голосовые сообщения голосом браузера — 07-extras.md, раздел 7. */
import { setHint } from '../../state/chat';
import { emitSpeech, isSpeaking, onAssistantResponse, onUiActivity } from '../../state/events';

let voice: SpeechSynthesisVoice | null = null;
/** Голоса, которые отказали (synthesis-failed бывает у Microsoft Irina в Chrome) — больше их не берём */
const broken = new Set<string>();
/** Держим ссылку: Chrome иначе может собрать фразу сборщиком мусора, и onend не придёт */
let current: SpeechSynthesisUtterance | null = null;
let endTimer: ReturnType<typeof setTimeout> | undefined;
let startTimer: ReturnType<typeof setTimeout> | undefined;
let warnedNoVoice = false;

/** Строки в консоли браузера (F12) — по ним видно, где озвучка останавливается */
const log = (...args: unknown[]) => console.info('[Stevens · озвучка]', ...args);

function pickVoice(): void {
  const voices = window.speechSynthesis.getVoices()
    .filter((v) => v.lang.toLowerCase().startsWith('ru') && !broken.has(v.name));
  voice = voices.find((v) => v.localService) ?? voices[0] ?? null;
}

function finish(): void {
  clearTimeout(endTimer);
  current = null;
  if (isSpeaking()) emitSpeech('end');
}

function stop(reason: string): void {
  clearTimeout(startTimer);
  if (!isSpeaking()) return;
  log('оборвал:', reason);
  clearTimeout(endTimer);
  current = null;
  window.speechSynthesis.cancel();
  emitSpeech('cancelled');
}

function sayBrowser(text: string): void {
  // Голоса в Chrome подгружаются не сразу — переспрашиваем перед каждой фразой
  if (!voice) pickVoice();
  if (!voice) {
    log('нет русского голоса');
    if (!warnedNoVoice) setHint('speech_no_voice');
    warnedNoVoice = true;
    finish();
    return;
  }
  clearTimeout(endTimer);
  say(text, voice);
}

function say(text: string, chosen: SpeechSynthesisVoice): void {
  const synth = window.speechSynthesis;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = chosen;
  utterance.lang = chosen.lang;
  utterance.onstart = () => log('говорю', chosen.name);
  utterance.onend = () => {
    log('договорил');
    if (current === utterance) finish();
  };
  utterance.onerror = (event) => {
    log('ошибка', event.error);
    if (current !== utterance) return;
    // Без единого нажатия на странице (например, вызвали по имени сразу после загрузки) Chrome молчит
    if (event.error === 'not-allowed') setHint('speech_blocked');
    // Голос сломан — та же фраза следующим русским голосом
    if (event.error === 'synthesis-failed' || event.error === 'voice-unavailable' || event.error === 'synthesis-unavailable') {
      broken.add(chosen.name);
      pickVoice();
      if (voice) {
        clearTimeout(endTimer);
        say(text, voice);
        return;
      }
      setHint('speech_no_voice');
    }
    finish();
  };
  current = utterance;
  if (!isSpeaking()) emitSpeech('start', text);
  // Если onend так и не придёт (бывает в Chrome), не держим «говорит» вечно: иначе не включатся автослушание и «Стивенс»
  endTimer = setTimeout(finish, 3000 + text.length * 120);
  // Chrome: speak сразу после cancel иногда теряет фразу — даём очереди очиститься
  const busy = synth.speaking || synth.pending;
  synth.cancel();
  log('фраза', JSON.stringify(text), 'голос', chosen.name);
  startTimer = setTimeout(() => {
    synth.resume();
    synth.speak(utterance);
  }, busy ? 120 : 30);
}

export function init(): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  pickVoice();
  window.speechSynthesis.addEventListener('voiceschanged', pickVoice);

  // Safari (и иногда Chrome) разрешает говорить вслух, только если первая фраза прозвучала прямо в нажатии.
  // Поэтому при первом нажатии на странице произносим беззвучный пробел — дальше ответы можно озвучивать когда угодно
  // Брифинг приходит при открытии, до первого нажатия: звук пока запрещён — скажем его по первому касанию
  let unlocked = false;
  let queued: string | null = null;
  const unlock = () => {
    unlocked = true;
    if (queued) {
      const text = queued;
      queued = null;
      setTimeout(() => speak(text), 300);
    }
    document.removeEventListener('pointerdown', unlock, true);
    document.removeEventListener('keydown', unlock, true);
    const silent = new SpeechSynthesisUtterance(' ');
    silent.volume = 0;
    window.speechSynthesis.speak(silent);
  };
  document.addEventListener('pointerdown', unlock, true);
  document.addEventListener('keydown', unlock, true);

  const speak = (text: string) => {
    stop('новая фраза');
    clearTimeout(startTimer);
    clearTimeout(endTimer);
    sayBrowser(text);
  };

  onAssistantResponse((response, request) => {
    const briefing = request.action?.id === 'briefing';
    if (request.source !== 'voice' && !briefing) return;
    const text = response.speech ?? response.text;
    if (!text) return;
    if (briefing && !unlocked) {
      queued = text;
      return;
    }
    speak(text);
  });

  // Обрывает любое действие: кнопка, ввод, микрофон, «Новый диалог», сворачивание вкладки
  onUiActivity((kind) => {
    if (['typing', 'button-press', 'recording-start', 'new-dialog', 'tab-hidden'].includes(kind)) stop(kind);
  });
}
