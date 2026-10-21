// Web Speech API types are not part of TypeScript's standard DOM definitions.
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
const constructor = () =>
  (window as SpeechWindow).SpeechRecognition ??
  (window as SpeechWindow).webkitSpeechRecognition;
export const isSupported = () => !!constructor() && window.isSecureContext;

export interface VoiceCallbacks {
  state: (recording: boolean) => void;
  interim: (text: string) => void;
  final: (text: string) => void;
  error: (
    kind: "denied" | "no_mic" | "no_speech" | "unsupported" | "error",
  ) => void;
}
export function createVoice(callbacks: VoiceCallbacks) {
  interface Session {
    recognition: Recognition;
    finalText: string;
    latestText: string;
    stopping: boolean;
    timer?: ReturnType<typeof setTimeout>;
  }
  let active: Session | null = null;
  function abort(session: Session) {
    try {
      session.recognition.abort();
    } catch {
      // Some engines have already released capture before notifying the caller.
    }
  }
  function cleanup(session: Session): boolean {
    if (active !== session) return false;
    active = null;
    clearTimeout(session.timer);
    session.recognition.onresult = null;
    session.recognition.onerror = null;
    session.recognition.onend = null;
    callbacks.state(false);
    return true;
  }
  function stop(session: Session) {
    if (active !== session || session.stopping) return;
    session.stopping = true;
    clearTimeout(session.timer);
    try {
      session.recognition.stop();
    } catch {
      if (cleanup(session)) {
        abort(session);
        callbacks.error("error");
      }
    }
  }
  return {
    start() {
      const Constructor = constructor();
      if (!Constructor || !window.isSecureContext) {
        callbacks.error("unsupported");
        return;
      }
      if (active) return;
      const current = new Constructor();
      const session: Session = {
        recognition: current,
        finalText: "",
        latestText: "",
        stopping: false,
      };
      active = session;
      current.lang = "ru-RU";
      current.continuous = false;
      current.interimResults = true;
      current.onresult = (event) => {
        if (active !== session) return;
        const parts = Array.from(event.results);
        session.finalText = parts
          .filter((result) => result.isFinal)
          .map((result) => result[0].transcript)
          .join(" ");
        session.latestText = parts
          .map((result) => result[0].transcript)
          .join(" ");
        callbacks.interim(session.latestText);
      };
      current.onerror = (event) => {
        if (!cleanup(session)) return;
        abort(session);
        callbacks.error(
          event.error === "not-allowed"
            ? "denied"
            : event.error === "audio-capture"
              ? "no_mic"
              : event.error === "no-speech"
                ? "no_speech"
                : "error",
        );
      };
      current.onend = () => {
        if (!cleanup(session)) return;
        const text = (session.finalText || session.latestText).trim();
        if (text) callbacks.final(text);
        else callbacks.error("no_speech");
      };
      try {
        current.start();
        if (active === session) {
          callbacks.state(true);
          session.timer = setTimeout(() => stop(session), 20_000);
        }
      } catch {
        if (cleanup(session)) {
          abort(session);
          callbacks.error("error");
        }
      }
    },
    stop() {
      if (active) stop(active);
    },
    cancel() {
      const session = active;
      if (session && cleanup(session)) abort(session);
    },
  };
}
