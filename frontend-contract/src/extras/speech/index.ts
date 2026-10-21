/**
 * Д12: озвучка ответов на голосовые сообщения — 07-extras.md, раздел 7.
 * Сначала голос Stevens с сервера (Silero «aidar», контейнер tts, POST /api/tts → WAV),
 * если сервер не ответил — голос браузера (speechSynthesis).
 */
import { apiUrl } from '../../config/features';
import { setHint } from '../../state/chat';
import { emitSpeech, isSpeaking, onAssistantResponse, onUiActivity } from '../../state/events';

const TTS_URL = `${apiUrl.replace(/\/$/, '')}/api/tts`;
/** Сервер не ответил — минуту не спрашиваем его, чтобы не ждать перед каждой фразой */
const SERVER_RETRY_MS = 60_000;
/** Сколько ждём звук с сервера, прежде чем говорить голосом браузера */
const SERVER_TIMEOUT_MS = 8000;
/** Короткая тишина: проигрываем её при первом нажатии, после этого Safari и Chrome дают играть звук без нажатия */
const SILENT_WAV =
  'data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==';

let audio: HTMLAudioElement | null = null;
let audioUrl: string | null = null;
let request: AbortController | null = null;
let serverDownUntil = 0;

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

function releaseAudio(): void {
  request?.abort();
  request = null;
  if (audio) {
    audio.onended = audio.onerror = null;
    audio.pause();
  }
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = null;
}

function finish(): void {
  clearTimeout(endTimer);
  current = null;
  releaseAudio();
  if (isSpeaking()) emitSpeech('end');
}

function stop(reason: string): void {
  clearTimeout(startTimer);
  releaseAudio();
  if (!isSpeaking()) return;
  log('оборвал:', reason);
  clearTimeout(endTimer);
  current = null;
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  emitSpeech('cancelled');
}

/** Режем ответ на предложения: первое звучит, пока сервер готовит остальные.
 *  Граница — знак конца, пробел и заглавная буква, чтобы «1. созвон» и «15.10» не рвались */
export function splitSentences(text: string): string[] {
  const parts = text.split(/(?<=[.!?…])\s+(?=[А-ЯЁA-Z«"])/).map((t) => t.trim()).filter(Boolean);
  return parts.length ? parts : [text];
}

/** Ставит кусок звука в плеер: started — начал играть, ended — доиграл (ошибка — звук битый) */
function playBlob(player: HTMLAudioElement, blob: Blob): { started: Promise<void>; ended: Promise<void> } {
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(blob);
  const ended = new Promise<void>((resolve, reject) => {
    player.onended = () => resolve();
    player.onerror = () => reject(new Error('битый звук'));
  });
  ended.catch(() => undefined);
  player.src = audioUrl;
  return { started: player.play(), ended };
}

/** Не доиграли с сервера — остаток договариваем голосом браузера */
function fallbackToBrowser(rest: string): void {
  log('ошибка проигрывания, договариваю голосом браузера');
  releaseAudio();
  if (isSpeaking() && rest) sayBrowser(rest);
}

/** Остальные предложения по очереди; запросы за ними ушли заранее */
async function playRest(controller: AbortController, parts: string[], blobs: Promise<Blob>[], first: Promise<void>): Promise<void> {
  let ended = first;
  for (let i = 0; ; i++) {
    try {
      await ended;
    } catch {
      if (request === controller) fallbackToBrowser(parts.slice(i).join(' '));
      return;
    }
    if (request !== controller) return;
    if (i + 1 >= parts.length) {
      log('договорил (сервер)');
      finish();
      return;
    }
    try {
      const blob = await blobs[i + 1];
      if (request !== controller || !audio) return;
      const next = playBlob(audio, blob);
      await next.started;
      ended = next.ended;
    } catch {
      if (request === controller) fallbackToBrowser(parts.slice(i + 1).join(' '));
      return;
    }
  }
}

/** Голос Stevens с сервера. false — сервер недоступен или звук не проигрался, тогда говорит браузер */
async function sayServer(text: string): Promise<boolean | 'aborted'> {
  if (!audio || Date.now() < serverDownUntil) return false;
  const controller = new AbortController();
  request = controller;
  const timer = setTimeout(() => controller.abort(), SERVER_TIMEOUT_MS);
  const parts = splitSentences(text);
  // Все запросы уходят сразу и по порядку: сервер готовит их один за другим, пока играет предыдущее
  const blobs = parts.map(async (part) => {
    const res = await fetch(TTS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: part }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`tts ${res.status}`);
    return res.blob();
  });
  blobs.forEach((b) => b.catch(() => undefined));
  try {
    const blob = await blobs[0];
    if (request !== controller) return 'aborted';
    clearTimeout(timer);
    const first = playBlob(audio, blob);
    await first.started;
    log('говорю голосом сервера', JSON.stringify(text), `(${parts.length} предл.)`);
    void playRest(controller, parts, blobs, first.ended);
    return true;
  } catch (err) {
    clearTimeout(timer);
    // Оборвали сами (кнопка, ввод, микрофон) — молчим, голос браузера не нужен
    if (request !== controller) return 'aborted';
    request?.abort();
    request = null;
    if ((err as Error).name === 'NotAllowedError') {
      log('браузер не дал проиграть звук без нажатия');
      return false;
    }
    log('сервер озвучки недоступен, говорю голосом браузера:', (err as Error).message);
    serverDownUntil = Date.now() + SERVER_RETRY_MS;
    return false;
  }
}

function sayBrowser(text: string): void {
  if (!('speechSynthesis' in window)) {
    finish();
    return;
  }
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
  if (!isSpeaking()) emitSpeech('start');
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
  if (typeof window === 'undefined') return;
  const hasSynth = 'speechSynthesis' in window;
  if (typeof Audio !== 'undefined') audio = new Audio();
  if (!hasSynth && !audio) return;
  if (hasSynth) {
    pickVoice();
    window.speechSynthesis.addEventListener('voiceschanged', pickVoice);
  }

  // Safari (и иногда Chrome) разрешает звук, только если первый раз он прозвучал прямо в нажатии.
  // Поэтому при первом нажатии на странице проигрываем тишину и беззвучный пробел — дальше ответы звучат когда угодно
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
    if (audio && !audioUrl) {
      audio.src = SILENT_WAV;
      audio.play().catch(() => undefined);
    }
    if (hasSynth) {
      const silent = new SpeechSynthesisUtterance(' ');
      silent.volume = 0;
      window.speechSynthesis.speak(silent);
    }
  };
  document.addEventListener('pointerdown', unlock, true);
  document.addEventListener('keydown', unlock, true);

  const speak = (text: string) => {
    stop('новая фраза');
    clearTimeout(startTimer);
    clearTimeout(endTimer);
    emitSpeech('start');
    // Пока ждём звук с сервера, Стивенс уже «говорит»: автослушание и «Стивенс» не включаются
    endTimer = setTimeout(finish, SERVER_TIMEOUT_MS + 3000 + text.length * 120);
    void sayServer(text).then((ok) => {
      if (ok === false && isSpeaking()) sayBrowser(text);
    });
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
