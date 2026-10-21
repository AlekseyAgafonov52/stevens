/**
 * Голос — 03-behavior.md, раздел 6. Интерфейс: isSupported(), start(), stop(), cancel()
 * и события state / interim / final / error / level. Движок — Web Speech API;
 * если его заменят на серверный (POST /api/stt), остальной код не меняется.
 *
 * Вызов по имени: arm() слушает фоном, пока не услышит «Стивенс». Тогда эта же запись
 * становится обычной (событие wake, затем state recording), и всё сказанное после имени
 * уходит в final. Так нет паузы между именем и фразой: «Стивенс, завтра в 10 созвон».
 */
export type VoiceError = 'denied' | 'no-mic' | 'no-speech' | 'failed' | 'service';
export type VoiceState = 'idle' | 'asking' | 'recording';

type Events = {
  state: (state: VoiceState) => void;
  interim: (text: string) => void;
  final: (text: string) => void;
  error: (error: VoiceError) => void;
  level: (level: number) => void;
  /** Услышали имя: дальше идёт обычная запись */
  wake: () => void;
  /** Фоновое прослушивание имени: включилось или выключилось */
  armed: (armed: boolean) => void;
  /** Фоновому прослушиванию закрыли микрофон */
  wakeDenied: () => void;
};

interface RecognitionResult { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

const MAX_MS = 20000;
/** Пауза, после которой считаем, что человек договорил: хватает, чтобы подумать посреди фразы */
const SILENCE_MS = 1800;
const STOP_WORD = /(?:^|\s)стоп[.!]?$/i;
/** Как браузер пишет имя: «Стивенс», «Стивенсон», «Стивен», «Stevens» */
const WAKE_WORD = /(?:^|[\s,.!?])(стив[еи]н\S*|stevens?\S*|steven\S*)[\s,.!?—-]*/i;
/** Сказали только имя и молчат — ждём фразу столько, потом снова слушаем фоном */
const WAKE_WAIT_MS = 6000;

const ERRORS: Record<string, VoiceError> = {
  'not-allowed': 'denied',
  'audio-capture': 'no-mic',
  // Safari: распознавание недоступно (выключена Диктовка или Siri, нет разрешения на распознавание речи)
  'service-not-allowed': 'service',
};

const isSafari = () => typeof navigator !== 'undefined' && /^((?!chrome|chromium|android|crios|fxios|edg).)*safari/i.test(navigator.userAgent);

function ctor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const listeners: { [K in keyof Events]: Set<Events[K]> } = {
  state: new Set(), interim: new Set(), final: new Set(), error: new Set(), level: new Set(),
  wake: new Set(), armed: new Set(), wakeDenied: new Set(),
};

function emit<K extends keyof Events>(name: K, ...args: Parameters<Events[K]>): void {
  listeners[name].forEach((l) => (l as (...a: Parameters<Events[K]>) => void)(...args));
}

let recognition: Recognition | null = null;
let stream: MediaStream | null = null;
let audio: AudioContext | null = null;
let levelTimer: ReturnType<typeof setInterval> | undefined;
let maxTimer: ReturnType<typeof setTimeout> | undefined;
let silenceTimer: ReturnType<typeof setTimeout> | undefined;
let finalText = '';
let interimText = '';
let cancelled = false;
let permissionGranted = false;
/** Фоновая запись, которая ещё ждёт имя */
let armedRec: Recognition | null = null;
let armedEnded: Promise<void> | null = null;
let wantArmed = false;
let rearmTimer: ReturnType<typeof setTimeout> | undefined;

function cleanupAudio(): void {
  clearInterval(levelTimer);
  clearTimeout(maxTimer);
  clearTimeout(silenceTimer);
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  void audio?.close().catch(() => undefined);
  audio = null;
}

function startLevel(media: MediaStream): void {
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (reduced) return;
  try {
    audio = new AudioContext();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 256;
    audio.createMediaStreamSource(media).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    levelTimer = setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const v of data) sum += ((v - 128) / 128) ** 2;
      emit('level', Math.min(1, Math.sqrt(sum / data.length) * 4));
    }, 80);
  } catch {
    /* без столбиков */
  }
}

function transcriptOf(event: RecognitionEvent): string {
  let text = '';
  for (let i = 0; i < event.results.length; i += 1) text += event.results[i][0].transcript;
  return text;
}

/** Фоновая запись до имени. Браузер сам обрывает её раз в минуту или на тишине — запускаем заново */
function arm(): void {
  const Ctor = ctor();
  if (!Ctor || !wantArmed || recognition || armedRec) return;
  const rec = new Ctor();
  rec.lang = 'ru-RU';
  rec.interimResults = true;
  rec.continuous = true;
  let woke = false;
  let resolveEnded: () => void = () => undefined;
  armedEnded = new Promise((resolve) => { resolveEnded = resolve; });

  const finish = () => {
    clearTimeout(silenceTimer);
    clearTimeout(maxTimer);
    rec.stop();
  };

  rec.onresult = (event) => {
    const whole = transcriptOf(event);
    if (!woke) {
      const hit = WAKE_WORD.exec(whole);
      if (!hit) return;
      // Имя услышано: эта запись становится обычной
      woke = true;
      armedRec = null;
      emit('armed', false);
      recognition = rec;
      cancelled = false;
      finalText = '';
      interimText = '';
      emit('wake');
      emit('state', 'recording');
      maxTimer = setTimeout(finish, MAX_MS);
      silenceTimer = setTimeout(finish, WAKE_WAIT_MS);
      void navigator.mediaDevices?.getUserMedia({ audio: true }).then((media) => {
        if (recognition !== rec) { media.getTracks().forEach((t) => t.stop()); return; }
        stream = media;
        startLevel(media);
      }).catch(() => undefined);
    }
    const hit = WAKE_WORD.exec(whole);
    const shown = (hit ? whole.slice(hit.index + hit[0].length) : whole).trim();
    if (STOP_WORD.test(shown)) {
      finalText = shown.replace(STOP_WORD, '');
      interimText = '';
      finish();
      return;
    }
    finalText = shown;
    interimText = '';
    emit('interim', shown);
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(finish, shown ? SILENCE_MS : WAKE_WAIT_MS);
  };
  rec.onerror = (event) => {
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      wantArmed = false;
      emit('wakeDenied');
    }
    if (woke && event.error !== 'no-speech' && event.error !== 'aborted') cancelled = true;
  };
  rec.onend = () => {
    resolveEnded();
    if (!woke) {
      armedRec = null;
      armedEnded = null;
      emit('armed', false);
    } else {
      recognition = null;
      cleanupAudio();
      emit('state', 'idle');
      // Тишина после имени — без «Не расслышал»: просто снова слушаем фоном
      if (!cancelled && finalText.trim()) emit('final', finalText.trim());
    }
    clearTimeout(rearmTimer);
    if (wantArmed) rearmTimer = setTimeout(arm, 400);
  };
  try {
    rec.start();
    armedRec = rec;
    emit('armed', true);
  } catch {
    armedEnded = null;
  }
}

/** Остановить фоновую запись и дождаться, пока браузер отпустит микрофон */
async function disarmAndWait(): Promise<void> {
  clearTimeout(rearmTimer);
  const ended = armedEnded;
  if (!armedRec) return;
  armedRec.abort();
  armedRec = null;
  if (ended) await Promise.race([ended, new Promise((resolve) => setTimeout(resolve, 600))]);
}

export const voice = {
  isSupported(): boolean {
    return typeof window !== 'undefined' && ctor() !== null && !!navigator.mediaDevices?.getUserMedia;
  },

  /** Разрешение на микрофон уже дано (для Д13) */
  hasPermission(): boolean {
    return permissionGranted;
  },

  async start(): Promise<void> {
    const Ctor = ctor();
    if (!Ctor || recognition) return;
    // Только если фоном слушали имя: иначе ждать нечего, а Safari запускает распознавание лишь прямо в нажатии
    if (armedRec) await disarmAndWait();
    if (recognition) return;
    cancelled = false;
    finalText = '';
    interimText = '';
    const rec = new Ctor();
    recognition = rec;
    rec.lang = 'ru-RU';
    rec.interimResults = true;
    // Слушаем сами до паузы SILENCE_MS: браузер в обычном режиме обрывает запись уже через ~1 с тишины
    rec.continuous = true;
    rec.onstart = () => {
      permissionGranted = true;
      // Столбики громкости — вторым захватом микрофона. Safari от этого сбивает распознавание, там без столбиков
      if (isSafari()) return;
      void navigator.mediaDevices.getUserMedia({ audio: true }).then((media) => {
        if (recognition !== rec) { media.getTracks().forEach((t) => t.stop()); return; }
        stream = media;
        startLevel(media);
      }).catch(() => undefined);
    };
    rec.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText = `${finalText} ${result[0].transcript}`.trim();
        else interim += result[0].transcript;
      }
      interimText = interim;
      const shown = (finalText + interim).trim();
      if (STOP_WORD.test(shown)) {
        finalText = shown.replace(STOP_WORD, '');
        interimText = '';
        rec.stop();
        return;
      }
      emit('interim', shown);
      clearTimeout(silenceTimer);
      if (shown) silenceTimer = setTimeout(() => rec.stop(), SILENCE_MS);
    };
    rec.onerror = (event) => {
      if (cancelled) return;
      if (event.error === 'no-speech') return; // сообщим в onend
      if (event.error === 'aborted') return;
      cancelled = true;
      emit('error', ERRORS[event.error] ?? 'failed');
    };
    rec.onend = () => {
      recognition = null;
      cleanupAudio();
      emit('state', 'idle');
      clearTimeout(rearmTimer);
      if (wantArmed) rearmTimer = setTimeout(arm, 400);
      if (cancelled) return;
      const text = (finalText + ' ' + interimText).trim();
      if (text) emit('final', text);
      else emit('error', 'no-speech');
    };
    maxTimer = setTimeout(() => rec.stop(), MAX_MS);
    try {
      // Синхронно, в том же нажатии: разрешение на микрофон браузер спросит сам
      rec.start();
      emit('state', 'recording');
    } catch {
      recognition = null;
      cleanupAudio();
      emit('state', 'idle');
      emit('error', 'failed');
    }
  },

  /** Остановить и отдать распознанное */
  stop(): void {
    recognition?.stop();
  },

  /** Отменить: ничего не отдавать */
  cancel(): void {
    cancelled = true;
    if (recognition) recognition.abort();
    else cleanupAudio();
  },

  /** Слушать имя фоном (true) или нет. Пока идёт обычная запись, фоновая не мешает: включится после */
  setArmed(on: boolean): void {
    wantArmed = on;
    clearTimeout(rearmTimer);
    // С задержкой: сразу после записи уходит запрос, и включать фоновую запись на миг незачем
    if (on) rearmTimer = setTimeout(arm, 400);
    else void disarmAndWait();
  },

  on<K extends keyof Events>(name: K, listener: Events[K]): () => void {
    listeners[name].add(listener);
    return () => listeners[name].delete(listener);
  },
};
