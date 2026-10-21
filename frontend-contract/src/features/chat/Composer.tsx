import { useEffect, useRef, useState } from "react";
import { ArrowUp, Mic, Square, Trash2 } from "lucide-react";
import type { MessageSource } from "../../api/types";
import { T, fill } from "../../content/texts";
import { createVoice } from "../../voice";
import { stopSpeaking } from "../../voice/speech";

export function Composer({
  busy,
  value,
  onChange,
  onSend,
  onRecording,
  status,
  listenSignal = 0,
}: {
  busy: boolean;
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string, source: MessageSource) => void;
  onRecording: (recording: boolean) => void;
  status: string;
  /** Д13 Автослушание: при каждом увеличении фронт сам включает микрофон */
  listenSignal?: number;
}) {
  const [recording, setRecording] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("");
  const [seconds, setSeconds] = useState(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const draft = useRef("");
  const handlers = useRef({ onSend, onRecording });
  handlers.current = { onSend, onRecording };
  const controller = useRef<ReturnType<typeof createVoice> | null>(null);
  useEffect(() => {
    controller.current = createVoice({
      state: (active) => {
        setRecording(active);
        if (active) setVoiceStatus("");
        handlers.current.onRecording(active);
      },
      interim: setTranscript,
      final: (text) => {
        const combined = `${draft.current} ${text}`.trim();
        if (combined.length > 300) {
          onChange(combined);
          setVoiceStatus(T.char_limit);
        } else handlers.current.onSend(combined, "voice");
      },
      error: (kind) =>
        setVoiceStatus(
          {
            denied: T.voice_denied,
            no_mic: T.voice_no_mic,
            no_speech: T.voice_no_speech,
            unsupported: T.voice_unsupported,
            error: T.voice_error,
          }[kind],
        ),
    });
    const hidden = () => {
      if (document.hidden) controller.current?.cancel();
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      controller.current?.cancel();
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [onChange]);
  useEffect(() => {
    if (listenSignal > 0) startListening();
    // Запускаем только по сигналу, а не при каждом изменении черновика.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listenSignal]);
  useEffect(() => {
    if (!recording) return;
    const interval = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(interval);
  }, [recording]);
  useEffect(() => {
    if (!voiceStatus) return;
    const timer = setTimeout(() => setVoiceStatus(""), 6000);
    return () => clearTimeout(timer);
  }, [voiceStatus]);
  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = `${input.current.scrollHeight}px`;
  }, [value]);

  function startListening() {
    stopSpeaking();
    draft.current = value;
    setTranscript("");
    setSeconds(0);
    setVoiceStatus(T.voice_permission);
    controller.current?.start();
  }
  function send() {
    if (busy || !value.trim() || value.trim().length > 300) return;
    onSend(value, "text");
    if (matchMedia("(max-width: 760px)").matches) input.current?.blur();
  }
  return (
    <div className="composer-wrap">
      <p className="composer-status" role="status">
        {status || voiceStatus || (value.length >= 300 ? T.char_limit : "")}
      </p>
      <form
        className={`composer ${recording ? "anim-rec" : ""}`}
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        {recording ? (
          <>
            <button
              type="button"
              className="icon-button ghost-button"
              aria-label={T.btn_cancel_record}
              onClick={() => controller.current?.cancel()}
            >
              <Trash2 strokeWidth={1.5} />
            </button>
            <p className="recording-transcript">
              {draft.current} {transcript}
            </p>
            <span className="recording-timer">
              0:{String(seconds).padStart(2, "0")}
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label={T.btn_stop_send}
              onClick={() => controller.current?.stop()}
            >
              <Square fill="currentColor" />
            </button>
          </>
        ) : (
          <>
            <textarea
              ref={input}
              aria-label={T.input_label}
              value={value}
              maxLength={300}
              rows={1}
              placeholder={T.input_placeholder}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  send();
                }
              }}
            />
            {value.length >= 250 && (
              <span
                className={`char-counter ${value.length >= 300 ? "at-limit" : ""}`}
              >
                {fill(T.char_counter, { count: value.length })}
              </span>
            )}
            <button
              type="button"
              className="icon-button mic-button"
              disabled={busy}
              aria-label={T.btn_mic}
              onClick={startListening}
            >
              <Mic strokeWidth={1.5} />
            </button>
            <button
              className="icon-button"
              aria-label={T.btn_send}
              disabled={busy || !value.trim() || value.trim().length > 300}
            >
              <ArrowUp strokeWidth={1.75} />
            </button>
          </>
        )}
      </form>
    </div>
  );
}
