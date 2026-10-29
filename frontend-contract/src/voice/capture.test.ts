import { describe, expect, it } from 'vitest';
import { concat, downsample, encodeWav, WAV_RATE } from './capture';

describe('запись для SpeechKit', () => {
  it('склеивает куски по порядку', () => {
    const joined = concat([new Float32Array([1, 2]), new Float32Array([3])], 3);
    expect([...joined]).toEqual([1, 2, 3]);
  });

  it('48 кГц → 16 кГц: втрое меньше семплов, громкость та же', () => {
    const out = downsample(new Float32Array(4800).fill(0.5), 48000, WAV_RATE);
    expect(out.length).toBe(1600);
    expect(out.every((v) => Math.abs(v - 0.5) < 1e-6)).toBe(true);
  });

  it('WAV: заголовок 44 байта, 16 бит, моно, 16 кГц', async () => {
    const blob = encodeWav(new Float32Array([0, 1, -1, 2]), WAV_RATE);
    expect(blob.type).toBe('audio/wav');
    expect(blob.size).toBe(44 + 4 * 2);
    const view = new DataView(await blob.arrayBuffer());
    const tag = (at: number) => String.fromCharCode(...new Uint8Array(view.buffer, at, 4));
    expect(tag(0)).toBe('RIFF');
    expect(tag(8)).toBe('WAVE');
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(WAV_RATE);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getInt16(46, true)).toBe(32767);
    expect(view.getInt16(48, true)).toBe(-32768);
    expect(view.getInt16(50, true)).toBe(32767); // громче предела — обрезаем, а не переворачиваем
  });
});
