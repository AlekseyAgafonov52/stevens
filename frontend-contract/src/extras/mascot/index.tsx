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
import nightcap from '../../assets/mascot/stevens-nightcap.svg?raw';
import writeRead from '../../assets/mascot/stevens-write-read.svg?raw';
import write1 from '../../assets/mascot/stevens-write-1.svg?raw';
import write2 from '../../assets/mascot/stevens-write-2.svg?raw';
import write3 from '../../assets/mascot/stevens-write-3.svg?raw';
import { capDrop, gestureAt, gestureSvg, type Gesture } from './bow';
import { onAssistantResponse, onUiActivity } from '../../state/events';
import { recordingStore } from '../../state/recording';
import { store, useApp } from '../../state/store';
import {
  BOW, CLICK_COOLDOWN_MS, GREET, CLICK_RESET_MS, FLASH_MS, FRAME_MS, NIGHT_FROM, NIGHT_TO, READ_MS, TILT,
  READ_WRITE_FADE_MS, STATE_FADE_MS, THINK_FRAMES, THINK_LONG_MS, THINK_STEP_MS, TYPING_PAUSE_MS, WRITE_FRAMES, WRITE_MS,
} from './timing';

const SVG = {
  rest, 'rest-night': restNight, think, 'think-tap': thinkTap, 'think-read': thinkRead, listen, puzzled, done, concern,
  'write-read': writeRead, 'write-1': write1, 'write-2': write2, 'write-3': write3,
} as const;
type Frame = keyof typeof SVG;
type Mood = 'listen' | 'think' | 'write' | 'concern' | Gesture | 'puzzled' | 'done' | 'rest';
type Step = { frame: Frame; fade: number };
type GestureRun = { kind: Gesture; id: number; plan: typeof BOW };

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
function useMood(): { mood: Mood; gesture: GestureRun | null; onClick: () => void } {
  const recording = useApp((s) => s.recording);
  const waiting = useApp((s) => s.waiting);
  const hasText = useApp((s) => s.input.trim().length > 0);
  const [flash, setFlash] = useState<'puzzled' | 'done' | null>(null);
  const [typing, setTyping] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [gesture, setGesture] = useState<GestureRun | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastClick = useRef(0);

  const play = (kind: Gesture, greet = false) => {
    if (reducedMotion()) return;
    clearTimeout(flashTimer.current);
    setFlash(null);
    setGesture((g) => ({ kind, id: (g?.id ?? 0) + 1, plan: greet ? GREET : kind === 'bow' ? BOW : TILT }));
  };
  const playRef = useRef(play);
  playRef.current = play;

  useEffect(() => {
    // Приветствие: при каждом открытии чата (вход, перезагрузка) и при «Новом диалоге»
    playRef.current('bow', true);
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
      if (kind === 'new-dialog') playRef.current('bow', true);
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
    const { plan } = gesture;
    const timer = setTimeout(() => setGesture(null), plan.down + plan.hold + plan.up);
    return () => clearTimeout(timer);
  }, [gesture]);

  // Клик: первый — поклон, дальше — наклон головы; после 10 с без кликов снова поклон
  const onClick = () => {
    const now = Date.now();
    const since = now - lastClick.current;
    if (since < CLICK_COOLDOWN_MS) return;
    const s = store.get();
    if (s.recording || s.waiting) return;
    lastClick.current = now;
    play(since > CLICK_RESET_MS ? 'bow' : 'tilt');
  };

  let mood: Mood = 'rest';
  if (recording) mood = 'listen';
  else if (waiting) mood = 'think';
  else if (typing && hasText && !store.get().recording) mood = 'write';
  else if (conflict) mood = 'concern';
  else if (gesture) mood = gesture.kind;
  else if (flash) mood = flash;
  return { mood, gesture: gesture && mood === gesture.kind ? gesture : null, onClick };
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

function useFrame(mood: Mood, night: boolean): Step {
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

  if (mood === 'write') return write ?? { frame: 'write-read', fade: STATE_FADE_MS };
  if (mood === 'think') return thinking ?? { frame: 'think', fade: STATE_FADE_MS };
  if ((mood === 'rest' || mood === 'bow' || mood === 'tilt') && night) return { frame: 'rest-night', fade: STATE_FADE_MS };
  if (mood === 'bow' || mood === 'tilt') return { frame: 'rest', fade: STATE_FADE_MS };
  return { frame: mood, fade: STATE_FADE_MS };
}

/** Доля поклона или наклона на каждом кадре экрана; null — движения нет */
function useGesture(gesture: GestureRun | null): number | null {
  const [k, setK] = useState<number | null>(null);
  useEffect(() => {
    if (!gesture) {
      setK(null);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const value = gestureAt(now - start, gesture.plan);
      setK(value);
      if (value !== null) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [gesture]);
  return gesture ? k : null;
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
  const { mood, gesture, onClick } = useMood();
  const { frame, fade } = useFrame(mood, night);
  const bow = useGesture(gesture);
  const amp = useHornAmplitude(mood === 'listen');
  const style = { '--stv-amp': amp, '--stv-cap-drop': bow === null ? 0 : capDrop(mood === 'bow' ? 'bow' : 'tilt', bow) } as CSSProperties;
  return (
    <div className="stevens-perch" aria-hidden="true" onClick={onClick} style={style}>
      {/* Поклон рисуется поверх; при k = 0 он совпадает с покоем, поэтому подмена незаметна */}
      <div className="stevens-frames" data-hidden={bow !== null}>
        <Layers frame={frame} fade={fade} />
      </div>
      {bow !== null && <div className="stevens-layer" dangerouslySetInnerHTML={{ __html: gestureSvg(mood === 'bow' ? 'bow' : 'tilt', bow, night) }} />}
      {night && <div className="stevens-cap" dangerouslySetInnerHTML={{ __html: nightcap }} />}
    </div>
  );
}

const TITLE_SVG = rest.replace('viewBox="0 0 120 140"', 'viewBox="34 12 52 117.4"');

/** На экране входа справа от «Stevens», не анимируется */
export function MascotTitle() {
  return <span className="stevens-title" aria-hidden="true" dangerouslySetInnerHTML={{ __html: TITLE_SVG }} />;
}
