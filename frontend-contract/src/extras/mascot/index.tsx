/** Д14: персонаж Stevens — 08-mascot.md. */
import { useEffect, useRef, useState } from 'react';
import rest from '../../assets/mascot/stevens-rest.svg?raw';
import think from '../../assets/mascot/stevens-think.svg?raw';
import listen from '../../assets/mascot/stevens-listen.svg?raw';
import puzzled from '../../assets/mascot/stevens-puzzled.svg?raw';
import done from '../../assets/mascot/stevens-done.svg?raw';
import writeRead from '../../assets/mascot/stevens-write-read.svg?raw';
import write1 from '../../assets/mascot/stevens-write-1.svg?raw';
import write2 from '../../assets/mascot/stevens-write-2.svg?raw';
import write3 from '../../assets/mascot/stevens-write-3.svg?raw';
import { onAssistantResponse, onUiActivity } from '../../state/events';
import { store, useApp } from '../../state/store';
import {
  FLASH_MS, FRAME_MS, READ_MS, READ_WRITE_FADE_MS, STATE_FADE_MS, TYPING_PAUSE_MS, WRITE_FRAMES, WRITE_MS,
} from './timing';

const SVG = {
  rest, think, listen, puzzled, done, 'write-read': writeRead, 'write-1': write1, 'write-2': write2, 'write-3': write3,
} as const;
type Frame = keyof typeof SVG;
type Mood = 'listen' | 'think' | 'write' | 'puzzled' | 'done' | 'rest';

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

/** «Готово» / «Не понял» — 3 с; «пишет» — по времени последнего нажатия */
function useMood(): Mood {
  const recording = useApp((s) => s.recording);
  const waiting = useApp((s) => s.waiting);
  const hasText = useApp((s) => s.input.trim().length > 0);
  const [flash, setFlash] = useState<'puzzled' | 'done' | null>(null);
  const [typing, setTyping] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const showFlash = (mood: 'puzzled' | 'done') => {
      clearTimeout(flashTimer.current);
      setFlash(mood);
      flashTimer.current = setTimeout(() => setFlash(null), FLASH_MS);
    };
    const offResponse = onAssistantResponse((response) => {
      if (response.kind === 'not_understood' || response.kind === 'off_topic') showFlash('puzzled');
      else if (response.kind === 'created' || response.kind === 'completed' || response.kind === 'deleted') showFlash('done');
    });
    const offActivity = onUiActivity((kind) => {
      if (kind === 'typing') {
        setTyping(true);
        clearTimeout(typingTimer.current);
        typingTimer.current = setTimeout(() => setTyping(false), TYPING_PAUSE_MS);
      }
      if (kind === 'edit-saved') showFlash('done');
      // Состояние выше по приоритету гасит «готово» и «не понял»
      if (kind === 'typing' || kind === 'recording-start' || kind === 'request-start' || kind === 'new-dialog') {
        clearTimeout(flashTimer.current);
        setFlash(null);
      }
    });
    return () => {
      offResponse();
      offActivity();
      clearTimeout(flashTimer.current);
      clearTimeout(typingTimer.current);
    };
  }, []);

  if (recording) return 'listen';
  if (waiting) return 'think';
  if (typing && hasText && !store.get().recording) return 'write';
  if (flash) return flash;
  return 'rest';
}

/** Цикл «пишет»: читает 1,2 с → письмо 1,6 с (кадры по 200 мс) → снова читает */
function useFrame(mood: Mood): { frame: Frame; fade: number } {
  const [writeStep, setWriteStep] = useState<{ frame: Frame; fade: number }>({ frame: 'write-read', fade: STATE_FADE_MS });
  useEffect(() => {
    if (mood !== 'write') return;
    if (reducedMotion()) {
      setWriteStep({ frame: 'write-1', fade: 0 });
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    let cancelled = false;
    const cycle = (first: boolean) => {
      if (cancelled) return;
      setWriteStep({ frame: 'write-read', fade: first ? STATE_FADE_MS : READ_WRITE_FADE_MS });
      const frames = WRITE_MS / FRAME_MS;
      for (let i = 0; i < frames; i += 1) {
        timers.push(setTimeout(() => {
          setWriteStep({ frame: WRITE_FRAMES[i % WRITE_FRAMES.length], fade: i === 0 ? READ_WRITE_FADE_MS : 0 });
        }, READ_MS + i * FRAME_MS));
      }
      timers.push(setTimeout(() => cycle(false), READ_MS + WRITE_MS));
    };
    cycle(true);
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [mood]);
  if (mood === 'write') return writeStep;
  return { frame: mood, fade: STATE_FADE_MS };
}

/** Два слоя, мягкая смена прозрачности */
function Layers({ frame, fade }: { frame: Frame; fade: number }) {
  const [slots, setSlots] = useState<{ a: Frame; b: Frame; active: 'a' | 'b'; fade: number }>({ a: frame, b: frame, active: 'a', fade });
  useEffect(() => {
    setSlots((s) => {
      if (s[s.active] === frame) return s;
      const next = s.active === 'a' ? 'b' : 'a';
      return { ...s, [next]: frame, active: next, fade: reducedMotion() ? 0 : fade };
    });
  }, [frame, fade]);
  return (
    <>
      {(['a', 'b'] as const).map((slot) => (
        <div
          key={slot}
          className="stevens-layer"
          data-hidden={slots.active !== slot}
          style={{ transitionDuration: `${slots.fade}ms` }}
          dangerouslySetInnerHTML={{ __html: SVG[slots[slot]] }}
        />
      ))}
    </>
  );
}

export function MascotPerch() {
  const mood = useMood();
  const { frame, fade } = useFrame(mood);
  return (
    <div className="stevens-perch" aria-hidden="true">
      <Layers frame={frame} fade={fade} />
    </div>
  );
}

const TITLE_SVG = rest.replace('viewBox="0 0 120 140"', 'viewBox="34 12 52 117.4"');

/** На экране входа справа от «Stevens», не анимируется */
export function MascotTitle() {
  return <span className="stevens-title" aria-hidden="true" dangerouslySetInnerHTML={{ __html: TITLE_SVG }} />;
}
