/**
 * Голос — 03-behavior.md, раздел 6. Интерфейс: isSupported(), start(), stop(), cancel()
 * и события state / interim / final / error / level. Движок — Web Speech API;
 * если его заменят на серверный (POST /api/stt), остальной код не меняется.
 */
export type VoiceError = 'denied' | 'no-mic' | 'no-speech' | 'failed';
export type VoiceState = 'idle' | 'asking' | 'recording';

type Events = {
  state: (state: VoiceState) => void;
  interim: (text: string) => void;
  final: (text: string) => void;
  error: (error: VoiceError) => void;
  level: (level: number) => void;
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

function ctor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const listeners: { [K in keyof Events]: Set<Events[K]> } = {
  state: new Set(), interim: new Set(), final: new Set(), error: new Set(), level: new Set(),
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
    cancelled = false;
    finalText = '';
    interimText = '';
    let asking = true;
    const askTimer = setTimeout(() => asking && emit('state', 'asking'), 300);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      asking = false;
      clearTimeout(askTimer);
      const name = (error as { name?: string }).name;
      emit('state', 'idle');
      emit('error', name === 'NotFoundError' || name === 'OverconstrainedError' ? 'no-mic' : 'denied');
      return;
    }
    asking = false;
    clearTimeout(askTimer);
    permissionGranted = true;
    startLevel(stream);
    const rec = new Ctor();
    recognition = rec;
    rec.lang = 'ru-RU';
    rec.interimResults = true;
    // Слушаем сами до паузы SILENCE_MS: браузер в обычном режиме обрывает запись уже через ~1 с тишины
    rec.continuous = true;
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
      emit('error', event.error === 'not-allowed' ? 'denied' : event.error === 'audio-capture' ? 'no-mic' : 'failed');
    };
    rec.onend = () => {
      recognition = null;
      cleanupAudio();
      emit('state', 'idle');
      if (cancelled) return;
      const text = (finalText + ' ' + interimText).trim();
      if (text) emit('final', text);
      else emit('error', 'no-speech');
    };
    maxTimer = setTimeout(() => rec.stop(), MAX_MS);
    try {
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

  on<K extends keyof Events>(name: K, listener: Events[K]): () => void {
    listeners[name].add(listener);
    return () => listeners[name].delete(listener);
  },
};
