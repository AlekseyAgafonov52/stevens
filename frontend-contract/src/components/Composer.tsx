/** Строка ввода — 02-screens.md, 2.5–2.6. */
import { ArrowUp, Ear, Mic, Trash2 } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { T, fill } from '../content/texts';
import { InputBarOverlay } from '../extensions/points';
import { send } from '../state/chat';
import { emitActivity } from '../state/events';
import { cancelRecording, recordingStore, startRecording, stopRecording } from '../state/recording';
import { store, useApp } from '../state/store';
import { setWakeWord, wakeStore } from '../state/wake';
import { voice } from '../voice';

const LIMIT = 300;
const COUNTER_FROM = 250;
const MAX_LINES = 4;
const BARS = 7;
const PHONE = '(max-width: 760px)';

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener('change', cb);
      return () => m.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
  );
}

function StopIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
    </svg>
  );
}

function RecordingRow() {
  const { transcript, level, startedAt } = useSyncExternalStore(recordingStore.subscribe, recordingStore.get);
  const [seconds, setSeconds] = useState(0);
  const textRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 250);
    return () => clearInterval(timer);
  }, [startedAt]);
  useLayoutEffect(() => {
    const el = textRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [transcript]);
  // Столбики: 7 штук, 6–24 px по уровню звука; середина выше краёв
  const shape = [0.45, 0.7, 0.9, 1, 0.9, 0.7, 0.45];
  return (
    <>
      <button type="button" className="icon-btn icon-btn--ghost" aria-label={T.btn_cancel_record} onClick={() => { emitActivity('button-press'); cancelRecording(); }}>
        <Trash2 size={18} strokeWidth={1.5} aria-hidden="true" />
      </button>
      <div className="bars" aria-hidden="true">
        {Array.from({ length: BARS }, (_, i) => (
          <span key={i} className="bars__bar" style={{ height: `${6 + 18 * level * shape[i]}px` }} />
        ))}
      </div>
      <div className="rec-text" ref={textRef}><span>{transcript}</span></div>
      <span className="rec-timer">{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`}</span>
      <button type="button" className="icon-btn icon-btn--dark" aria-label={T.btn_stop_send} onClick={() => { emitActivity('button-press'); stopRecording(); }}>
        <StopIcon />
      </button>
    </>
  );
}

/** Вызов по имени: включить или выключить. Пока слушает фоном — у кнопки тихая точка */
function WakeToggle() {
  const { enabled, armed } = useSyncExternalStore(wakeStore.subscribe, wakeStore.get);
  if (!voice.isSupported()) return null;
  return (
    <button type="button" className={`icon-btn icon-btn--ghost wake-btn ${enabled ? 'wake-btn--on' : ''}`}
      aria-pressed={enabled} aria-label={enabled ? T.btn_wake_off : T.btn_wake_on} title={enabled ? T.btn_wake_off : T.btn_wake_on}
      onClick={() => { emitActivity('button-press'); setWakeWord(!enabled); }}>
      <Ear size={18} strokeWidth={1.5} aria-hidden="true" />
      {enabled && armed && <span className="wake-btn__dot" aria-hidden="true" />}
    </button>
  );
}

export function Composer() {
  const input = useApp((s) => s.input);
  const waiting = useApp((s) => s.waiting);
  const recording = useApp((s) => s.recording);
  const phone = useMedia(PHONE);
  const ref = useRef<HTMLTextAreaElement>(null);

  // Высота поля: 1–4 строки, дальше прокрутка
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    const line = parseFloat(getComputedStyle(el).lineHeight) || 22;
    const padding = parseFloat(getComputedStyle(el).paddingTop) * 2;
    el.style.height = `${Math.min(el.scrollHeight, line * MAX_LINES + padding)}px`;
  }, [input, recording]);

  const canSend = input.trim().length > 0 && !waiting;

  const submit = () => {
    if (!canSend) return;
    const text = input;
    if (send(text, 'text')) {
      store.set({ input: '' });
      if (phone) ref.current?.blur();
    }
  };

  const length = input.length;
  return (
    <div className="composer">
      <div className={`composer__box ${recording ? 'composer__box--rec anim-rec' : ''}`}>
        <InputBarOverlay />
        {recording ? (
          <RecordingRow />
        ) : (
          <>
            <WakeToggle />
            <button type="button" className="icon-btn icon-btn--dark" aria-label={T.btn_mic} disabled={waiting}
              onClick={() => { emitActivity('button-press'); startRecording(); }}>
              <Mic size={18} strokeWidth={1.5} aria-hidden="true" />
            </button>
            <div className="composer__field">
              <textarea
                ref={ref}
                rows={1}
                value={input}
                maxLength={LIMIT}
                placeholder={phone ? T.input_placeholder_short : T.input_placeholder}
                autoFocus={!phone}
                onChange={(e) => {
                  store.set({ input: e.target.value.slice(0, LIMIT) });
                  emitActivity('typing');
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              {length >= COUNTER_FROM && (
                <span className={`counter ${length >= LIMIT ? 'counter--limit' : ''}`}>{fill(T.char_counter, { count: length })}</span>
              )}
            </div>
            <button type="button" className={`icon-btn ${canSend ? 'icon-btn--dark' : 'icon-btn--off'}`} aria-label={T.btn_send}
              disabled={!canSend} onClick={submit}>
              <ArrowUp size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
