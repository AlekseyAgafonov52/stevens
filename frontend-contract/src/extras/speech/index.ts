/** Д12: озвучка ответов на голосовые сообщения — 07-extras.md, раздел 7.
 *  Голос Яндекса (POST /api/tts) основной, браузерный speechSynthesis — запасной:
 *  при сбое сети, отказе службы или исчерпанной квоте Стивенс не замолкает. */
import { api } from '../../api';
import { setHint } from '../../state/chat';
import { emitSpeech, isSpeaking, onAssistantResponse, onUiActivity } from '../../state/events';
import { serverHas } from '../../config/server';
import { isSafari } from '../../voice';

let voice: SpeechSynthesisVoice | null = null;
/** Голоса, которые отказали (synthesis-failed бывает у Microsoft Irina в Chrome) — больше их не берём */
const broken = new Set<string>();
/** Держим ссылку: Chrome иначе может собрать фразу сборщиком мусора, и onend не придёт */
let current: SpeechSynthesisUtterance | null = null;
let endTimer: ReturnType<typeof setTimeout> | undefined;
let startTimer: ReturnType<typeof setTimeout> | undefined;
let warnedNoVoice = false;
/** Звук от сервера: держим ссылку и адрес, чтобы оборвать по действию человека и освободить память */
let sound: HTMLAudioElement | null = null;
let soundUrl: string | null = null;
/** Браузер разрешил звук из кода (после первого нажатия на странице) */
let unlocked = false;
/** Номер текущей фразы: каждая новая фраза и каждое прерывание делают прежнее ожидание сервера недействительным */
let token = 0;

/** Строки в консоли браузера (F12) — по ним видно, где озвучка останавливается */
const log = (...args: unknown[]) => console.info('[Stevens · озвучка]', ...args);

function pickVoice(): void {
  const voices = window.speechSynthesis.getVoices()
    .filter((v) => v.lang.toLowerCase().startsWith('ru') && !broken.has(v.name));
  voice = voices.find((v) => v.localService) ?? voices[0] ?? null;
}

function dropSound(): void {
  if (soundUrl) URL.revokeObjectURL(soundUrl);
  sound = null;
  soundUrl = null;
}

function finish(): void {
  clearTimeout(endTimer);
  current = null;
  dropSound();
  if (isSpeaking()) emitSpeech('end');
}

function stop(reason: string): void {
  clearTimeout(startTimer);
  token += 1;
  if (!isSpeaking()) return;
  log('оборвал:', reason);
  clearTimeout(endTimer);
  current = null;
  if (sound) sound.pause();
  dropSound();
  window.speechSynthesis.cancel();
  emitSpeech('cancelled');
}

/** Голос Яндекса. Любая неудача — та же фраза браузерным голосом, без подсказки пользователю */
async function sayServer(text: string): Promise<void> {
  const mine = token;
  // «Говорю» — сразу, до ответа сервера: иначе автослушание решит, что Стивенс молчит,
  // через 0,6 с включит микрофон и этим оборвёт фразу на полуслове
  if (!isSpeaking()) emitSpeech('start', text);
  let audio: Blob;
  try {
    audio = await api.tts(text);
  } catch {
    if (mine !== token) return;
    log('сервер не озвучил — говорит браузер');
    sayBrowser(text);
    return;
  }
  // Пока ждали сервер, человек нажал кнопку или начал новую фразу — этот звук уже не нужен
  if (mine !== token) return;
  const url = URL.createObjectURL(audio);
  const element = new Audio(url);
  sound = element;
  soundUrl = url;
  const fallback = (why: string) => {
    if (sound !== element) return;
    clearTimeout(endTimer);
    dropSound();
    log(why, '— говорит браузер');
    sayBrowser(text);
  };
  element.onended = () => {
    if (sound !== element) return;
    log('договорил');
    finish();
  };
  element.onerror = () => fallback('звук не проигрался');
  log('фраза', JSON.stringify(text), 'голос сервера');
  try {
    await element.play();
  } catch {
    fallback('браузер не дал проиграть');
    return;
  }
  if (sound !== element) return;
  // Если конец звука так и не придёт, не держим «говорит» вечно — то же правило, что для голоса браузера
  clearTimeout(endTimer);
  endTimer = setTimeout(finish, 3000 + text.length * 120);
}

function sayBrowser(text: string): void {
  // Голоса в Chrome подгружаются не сразу — переспрашиваем перед каждой фразой
  if (!voice) pickVoice();
  if (!voice && isSafari()) {
    // Safari прячет системные голоса (Milena) из getVoices(), но говорит ими, если указать только язык
    log('русского голоса нет в списке — говорю системным голосом Safari');
    clearTimeout(endTimer);
    say(text, null);
    return;
  }
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


const MONTH = '(?!(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек))';
const ONE = (ending: string) => new RegExp(`(^|[^\\d.,:])1 ${MONTH}(?=[а-яё]*[${ending}](?![а-яё]))`, 'gi');

/** Голос браузера читает «1 встречу» как «один встречу»: род числа по окончанию слова (у голоса сервера это делает бэкенд) */
function agreeNumbers(text: string): string {
  return text
    .replace(ONE('ую'), '$1одну ')
    .replace(ONE('ая'), '$1одна ')
    .replace(ONE('ое'), '$1одно ')
    .replace(/(^|[^\d.,:])2 (?=(?:встреч|задач|заметк|запис|недел|минут)[иы](?![а-яё]))/gi, '$1две ');
}


/** chosen = null — голос не задан, только язык: так Safari берёт системный голос, которого нет в списке */
function say(text: string, chosen: SpeechSynthesisVoice | null): void {
  const synth = window.speechSynthesis;
  // Кавычки системный голос Safari читает вслух — убираем; числа согласуем со словом
  const utterance = new SpeechSynthesisUtterance(agreeNumbers(text.replace(/[«»„“"]/g, '')));
  const name = chosen?.name ?? 'системный';
  if (chosen) {
    utterance.voice = chosen;
    utterance.lang = chosen.lang;
  } else {
    utterance.lang = 'ru-RU';
  }
  utterance.onstart = () => log('говорю', name);
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
      if (chosen) broken.add(chosen.name);
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
  log('фраза', JSON.stringify(text), 'голос', name);
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
    // Тому же правилу подчиняется Audio: проигрываем пустой звук прямо в нажатии,
    // иначе Safari откажет уже готовому ответу от сервера
    const primer = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=');
    primer.volume = 0;
    void primer.play().catch(() => undefined);
  };
  document.addEventListener('pointerdown', unlock, true);
  document.addEventListener('keydown', unlock, true);

  const speak = (text: string) => {
    stop('новая фраза');
    clearTimeout(startTimer);
    clearTimeout(endTimer);
    // Без нажатия браузер может не дать проиграть звук (Safari — пока не разрешено автовоспроизведение
    // в настройках сайта). Пробуем всегда: откажет — та же фраза голосом браузера
    if (serverHas('tts')) void sayServer(text);
    else sayBrowser(text);
  };

  onAssistantResponse((response, request) => {
    if (!serverHas('f9')) return;
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
