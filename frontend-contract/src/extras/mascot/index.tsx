/** Д14: персонаж Stevens — 08-mascot.md. */
import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react';
import rest from '../../assets/mascot/stevens-rest.svg?raw';
import restNight from '../../assets/mascot/stevens-rest-night.svg?raw';
import think from '../../assets/mascot/stevens-think.svg?raw';
import thinkTap from '../../assets/mascot/stevens-think-tap.svg?raw';
import thinkRead from '../../assets/mascot/stevens-think-read.svg?raw';
import listen from '../../assets/mascot/stevens-listen.svg?raw';
import puzzled from '../../assets/mascot/stevens-puzzled.svg?raw';
import done from '../../assets/mascot/stevens-done.svg?raw';
import concern from '../../assets/mascot/stevens-concern.svg?raw';
import bow1 from '../../assets/mascot/stevens-bow-1.svg?raw';
import bow2 from '../../assets/mascot/stevens-bow-2.svg?raw';
import nightcap from '../../assets/mascot/stevens-nightcap.svg?raw';
import writeRead from '../../assets/mascot/stevens-write-read.svg?raw';
import write1 from '../../assets/mascot/stevens-write-1.svg?raw';
import write2 from '../../assets/mascot/stevens-write-2.svg?raw';
import write3 from '../../assets/mascot/stevens-write-3.svg?raw';
import { onAssistantResponse, onUiActivity, takeGreeting } from '../../state/events';
import { recordingStore } from '../../state/recording';
import { store, useApp } from '../../state/store';
import {
  BOW_STEPS, CLICK_COOLDOWN_MS, FLASH_MS, FRAME_MS, GESTURE_MS, NIGHT_FROM, NIGHT_TO, NOD_STEPS, READ_MS,
  READ_WRITE_FADE_MS, STATE_FADE_MS, THINK_FRAMES, THINK_LONG_MS, THINK_STEP_MS, TYPING_PAUSE_MS, WRITE_FRAMES, WRITE_MS,
} from './timing';

const SVG = {
  rest, 'rest-night': restNight, think, 'think-tap': thinkTap, 'think-read': thinkRead, listen, puzzled, done, concern,
  'bow-1': bow1, 'bow-2': bow2, 'write-read': writeRead, 'write-1': write1, 'write-2': write2, 'write-3': write3,
} as const;
type Frame = keyof typeof SVG;
type Gesture = 'bow' | 'nod';
type Mood = 'listen' | 'think' | 'write' | 'concern' | Gesture | 'puzzled' | 'done' | 'rest';
type Step = { frame: Frame; fade: number };

/** Насколько опускается верх головы в кадре (единицы viewBox) — колпак едет вместе с ним */
const CAP_DROP: Partial<Record<Frame, number>> = { 'bow-1': 4.5, 'bow-2': 9 };

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

const isNight = () => {
  const hour = new Date().getHours();
  return hour >= NIGHT_FROM || hour < NIGHT_TO;
};

function useNight(): boolean {
  const [night, setNight] = useState(isNight);
  useEffect(() => {
    const timer = setInterval(() => setNight(isNight()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return night;
}

/**
 * Приоритет: слушает → думает → пишет → конфликт → поклон/кивок → не понял/готово → покой.
 * «Конфликт» держится, пока не ушёл следующий запрос; поклон — после входа, «Нового диалога» и по клику.
 */
function useMood(): { mood: Mood; gestureId: number; onClick: () => void } {
  const recording = useApp((s) => s.recording);
  const waiting = useApp((s) => s.waiting);
  const hasText = useApp((s) => s.input.trim().length > 0);
  const [flash, setFlash] = useState<'puzzled' | 'done' | null>(null);
  const [typing, setTyping] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [gesture, setGesture] = useState<{ kind: Gesture; id: number } | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastClick = useRef({ at: 0, next: 'bow' as Gesture });

  const play = (kind: Gesture) => {
    if (reducedMotion()) return;
    clearTimeout(flashTimer.current);
    setFlash(null);
    setGesture((g) => ({ kind, id: (g?.id ?? 0) + 1 }));
  };
  const playRef = useRef(play);
  playRef.current = play;

  useEffect(() => {
    if (takeGreeting()) playRef.current('bow');
    const showFlash = (mood: 'puzzled' | 'done') => {
      clearTimeout(flashTimer.current);
      setFlash(mood);
      flashTimer.current = setTimeout(() => setFlash(null), FLASH_MS);
    };
    const offResponse = onAssistantResponse((response) => {
      setConflict(response.kind === 'conflict');
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
      if (kind === 'request-start' || kind === 'new-dialog') setConflict(false);
      // Состояние выше по приоритету гасит «готово», «не понял» и поклон
      if (kind === 'typing' || kind === 'recording-start' || kind === 'request-start' || kind === 'new-dialog') {
        clearTimeout(flashTimer.current);
        setFlash(null);
        setGesture(null);
      }
      if (kind === 'new-dialog') playRef.current('bow');
    });
    return () => {
      offResponse();
      offActivity();
      clearTimeout(flashTimer.current);
      clearTimeout(typingTimer.current);
    };
  }, []);

  // Поклон гаснет сам; таймер в эффекте, а не в play — переживает повторный запуск эффектов
  useEffect(() => {
    if (!gesture) return;
    const timer = setTimeout(() => setGesture(null), GESTURE_MS);
    return () => clearTimeout(timer);
  }, [gesture]);

  // Клик: поклон, следующий — кивок; не чаще раза в 2 с и только в покое
  const onClick = () => {
    const now = Date.now();
    if (now - lastClick.current.at < CLICK_COOLDOWN_MS) return;
    const s = store.get();
    if (s.recording || s.waiting) return;
    const kind = lastClick.current.next;
    lastClick.current = { at: now, next: kind === 'bow' ? 'nod' : 'bow' };
    play(kind);
  };

  let mood: Mood = 'rest';
  if (recording) mood = 'listen';
  else if (waiting) mood = 'think';
  else if (typing && hasText && !store.get().recording) mood = 'write';
  else if (conflict) mood = 'concern';
  else if (gesture) mood = gesture.kind;
  else if (flash) mood = flash;
  return { mood, gestureId: gesture?.id ?? 0, onClick };
}

/** Последовательность кадров по таймерам; сбрасывается при смене состояния */
function useSequence(active: boolean, run: (set: (step: Step) => void, after: (ms: number, fn: () => void) => void) => void, deps: unknown[]): Step | null {
  const [step, setStep] = useState<Step | null>(null);
  useEffect(() => {
    if (!active) {
      setStep(null);
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    run(setStep, (ms, fn) => timers.push(setTimeout(fn, ms)));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);
  return active ? step : null;
}

function useFrame(mood: Mood, gestureId: number, night: boolean): Step {
  const still = reducedMotion();

  // «Пишет»: читает 1,2 с → письмо 1,6 с (кадры по 200 мс) → снова читает
  const write = useSequence(mood === 'write', (set, after) => {
    if (still) return set({ frame: 'write-1', fade: 0 });
    const cycle = (first: boolean) => {
      set({ frame: 'write-read', fade: first ? STATE_FADE_MS : READ_WRITE_FADE_MS });
      const frames = WRITE_MS / FRAME_MS;
      for (let i = 0; i < frames; i += 1) {
        after(READ_MS + i * FRAME_MS, () => set({ frame: WRITE_FRAMES[i % WRITE_FRAMES.length], fade: i === 0 ? READ_WRITE_FADE_MS : 0 }));
      }
      after(READ_MS + WRITE_MS, () => cycle(false));
    };
    cycle(true);
  }, []);

  // «Думает» дольше 1,5 с: точки → карандаш → сверяется, по кругу
  const thinking = useSequence(mood === 'think', (set, after) => {
    set({ frame: 'think', fade: STATE_FADE_MS });
    if (still) return;
    const next = (i: number) => {
      set({ frame: THINK_FRAMES[i % THINK_FRAMES.length], fade: STATE_FADE_MS });
      after(THINK_STEP_MS, () => next(i + 1));
    };
    after(THINK_LONG_MS, () => next(1));
  }, []);

  // Поклон и кивок
  const gesture = useSequence(mood === 'bow' || mood === 'nod', (set, after) => {
    const steps = mood === 'bow' ? BOW_STEPS : NOD_STEPS;
    steps.forEach((s) => after(s.at, () => set({ frame: s.frame === 'rest' && night ? 'rest-night' : s.frame, fade: s.fade })));
  }, [mood, gestureId]);

  if (mood === 'write') return write ?? { frame: 'write-read', fade: STATE_FADE_MS };
  if (mood === 'think') return thinking ?? { frame: 'think', fade: STATE_FADE_MS };
  if (mood === 'bow' || mood === 'nod') return gesture ?? { frame: 'rest', fade: STATE_FADE_MS };
  if (mood === 'rest' && night) return { frame: 'rest-night', fade: STATE_FADE_MS };
  return { frame: mood, fade: STATE_FADE_MS };
}

/** Два слоя, мягкая смена прозрачности */
function Layers({ frame, fade }: Step) {
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

/** Трубка качается тем сильнее, чем громче голос: 1° в тишине, до 7° */
function useHornAmplitude(listening: boolean): number {
  const level = useSyncExternalStore(recordingStore.subscribe, () => recordingStore.get().level);
  const smooth = useRef(0);
  smooth.current = listening ? smooth.current * 0.6 + level * 0.4 : 0;
  return Math.round((1 + 6 * smooth.current) * 10) / 10;
}

export function MascotPerch() {
  const night = useNight();
  const { mood, gestureId, onClick } = useMood();
  const { frame, fade } = useFrame(mood, gestureId, night);
  const amp = useHornAmplitude(mood === 'listen');
  const style = { '--stv-amp': amp, '--stv-cap-drop': CAP_DROP[frame] ?? 0 } as CSSProperties;
  return (
    <div className="stevens-perch" aria-hidden="true" onClick={onClick} style={style}>
      <Layers frame={frame} fade={fade} />
      {night && <div className="stevens-cap" dangerouslySetInnerHTML={{ __html: nightcap }} />}
    </div>
  );
}

const TITLE_SVG = rest.replace('viewBox="0 0 120 140"', 'viewBox="34 12 52 117.4"');

/** На экране входа справа от «Stevens», не анимируется */
export function MascotTitle() {
  return <span className="stevens-title" aria-hidden="true" dangerouslySetInnerHTML={{ __html: TITLE_SVG }} />;
}
