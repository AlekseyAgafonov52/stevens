/**
 * Запись для гибридного распознавания (Ф4): живой текст и «стоп» даёт браузер, итоговый текст — SpeechKit.
 *
 * Звук держим только в памяти страницы. Кольцо последних секунд — запас: браузер узнаёт имя «Стивенс»
 * с задержкой, и без запаса начало просьбы, сказанной на одном дыхании, не попало бы в запись.
 * Никуда ничего не уходит, пока фраза не закончилась; отменённая фраза («стоп») выбрасывается.
 */

/** Столько отдаём серверу: 16 кГц, моно, 16 бит — 32 КБ в секунду (раздел 4.3: до 30 с и до 1 МБ) */
export const WAV_RATE = 16000;
/** Кольцо: имя браузер узнаёт с задержкой до полутора секунд, плюс начало просьбы */
const RING_SECONDS = 4;
/** Не длиннее, чем примет сервер: 25 с — это 800 КБ, с запасом до 1 МБ */
const MAX_TAKE_SECONDS = 25;

let stream: MediaStream | null = null;
let context: AudioContext | null = null;
let processor: ScriptProcessorNode | null = null;
let opening: Promise<boolean> | null = null;
/** Закрыли, пока микрофон открывался, — открытое сразу отпускаем */
let generation = 0;
let ring: Float32Array[] = [];
let ringSamples = 0;
let take: Float32Array[] | null = null;
let takeSamples = 0;
let takeRate = WAV_RATE;

export function captureAvailable(): boolean {
  return typeof AudioContext !== 'undefined' && typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

function keep(samples: Float32Array, rate: number): void {
  // Буфер браузер переиспользует — копируем
  const piece = new Float32Array(samples);
  ring.push(piece);
  ringSamples += piece.length;
  while (ring.length > 1 && ringSamples - ring[0].length >= RING_SECONDS * rate) {
    const old = ring.shift();
    if (old) ringSamples -= old.length;
  }
  if (take && takeSamples < MAX_TAKE_SECONDS * rate) {
    take.push(piece);
    takeSamples += piece.length;
  }
}

/** Открыть микрофон для записи. Уже открыт — сразу true; не дали — false, тогда распознавание идёт как раньше */
export function openCapture(): Promise<boolean> {
  if (context) return Promise.resolve(true);
  if (opening) return opening;
  const mine = generation;
  opening = (async () => {
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (mine !== generation) {
        media.getTracks().forEach((t) => t.stop());
        return false;
      }
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(media);
      // ScriptProcessor устарел, но работает везде, где включается гибрид, и не требует отдельного файла
      const node = ctx.createScriptProcessor(4096, 1, 1);
      const mute = ctx.createGain();
      mute.gain.value = 0;
      node.onaudioprocess = (event) => keep(event.inputBuffer.getChannelData(0), ctx.sampleRate);
      source.connect(node);
      // Без подключения к выходу Chrome не вызывает onaudioprocess; звука нет — громкость 0
      node.connect(mute);
      mute.connect(ctx.destination);
      void ctx.resume().catch(() => undefined);
      stream = media;
      context = ctx;
      processor = node;
      return true;
    } catch {
      return false;
    } finally {
      opening = null;
    }
  })();
  return opening;
}

/** Начать запись фразы, захватив из кольца последние prerollSeconds — сказанное чуть раньше */
export function beginTake(prerollSeconds: number): void {
  if (!context) {
    dropTake();
    return;
  }
  takeRate = context.sampleRate;
  const want = Math.round(prerollSeconds * takeRate);
  const pieces: Float32Array[] = [];
  let got = 0;
  for (let i = ring.length - 1; i >= 0 && got < want; i -= 1) {
    const piece = ring[i];
    const need = want - got;
    pieces.unshift(piece.length > need ? piece.subarray(piece.length - need) : piece);
    got += Math.min(piece.length, need);
  }
  take = pieces;
  takeSamples = got;
}

/** Закончить запись фразы: WAV 16 кГц для /api/stt. Запись не шла или пуста — null */
export function endTake(): Blob | null {
  const pieces = take;
  const length = takeSamples;
  dropTake();
  if (!pieces || !length) return null;
  return encodeWav(downsample(concat(pieces, length), takeRate, WAV_RATE), WAV_RATE);
}

export function dropTake(): void {
  take = null;
  takeSamples = 0;
}

/** Отпустить микрофон: красная точка записи во вкладке гаснет */
export function closeCapture(): void {
  generation += 1;
  dropTake();
  ring = [];
  ringSamples = 0;
  if (processor) processor.onaudioprocess = null;
  processor?.disconnect();
  processor = null;
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  void context?.close().catch(() => undefined);
  context = null;
}

export function concat(pieces: Float32Array[], length: number): Float32Array {
  const out = new Float32Array(length);
  let offset = 0;
  for (const piece of pieces) {
    out.set(piece.subarray(0, Math.min(piece.length, length - offset)), offset);
    offset += piece.length;
    if (offset >= length) break;
  }
  return out;
}

/** Понизить частоту усреднением соседних отсчётов — для речи этого достаточно */
export function downsample(samples: Float32Array, from: number, to: number): Float32Array {
  if (from <= to) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

/** WAV: моно, 16 бит, заголовок 44 байта */
export function encodeWav(samples: Float32Array, rate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
