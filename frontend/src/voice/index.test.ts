import { afterEach, describe, expect, it, vi } from "vitest";
import { createVoice } from "./index";

class FakeRecognition {
  static current: FakeRecognition;
  lang = "";
  continuous = false;
  interimResults = false;
  onresult:
    | ((event: {
        results: { isFinal: boolean; 0: { transcript: string } }[];
      }) => void)
    | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.current = this;
  }
  start() {
    /* Controlled by the test. */
  }
  stop() {
    this.onend?.();
  }
  abort() {
    this.onend?.();
  }
}
function setup() {
  vi.stubGlobal("window", {
    SpeechRecognition: FakeRecognition,
    isSecureContext: true,
  });
  const callbacks = {
    state: vi.fn(),
    interim: vi.fn(),
    final: vi.fn(),
    error: vi.fn(),
  };
  return { voice: createVoice(callbacks), callbacks };
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe("voice capture lifecycle", () => {
  it("sends final speech exactly once when stopped", () => {
    const { voice, callbacks } = setup();
    voice.start();
    FakeRecognition.current.onresult?.({
      results: [{ isFinal: true, 0: { transcript: "Планы на завтра" } }],
    });
    voice.stop();
    expect(callbacks.final).toHaveBeenCalledExactlyOnceWith("Планы на завтра");
    expect(callbacks.state).toHaveBeenLastCalledWith(false);
  });
  it("does not send interim text after cancel", () => {
    const { voice, callbacks } = setup();
    voice.start();
    FakeRecognition.current.onresult?.({
      results: [{ isFinal: false, 0: { transcript: "Не отправлять" } }],
    });
    voice.cancel();
    expect(callbacks.final).not.toHaveBeenCalled();
  });
  it("stops after 20 seconds and reports empty speech", () => {
    vi.useFakeTimers();
    const { voice, callbacks } = setup();
    voice.start();
    vi.advanceTimersByTime(20_000);
    expect(callbacks.error).toHaveBeenCalledWith("no_speech");
    expect(callbacks.final).not.toHaveBeenCalled();
  });
  it("ignores queued callbacks from a cancelled session after restarting", () => {
    const { voice, callbacks } = setup();
    voice.start();
    const old = FakeRecognition.current;
    const oldEnd = old.onend;
    const oldResult = old.onresult;
    voice.cancel();
    voice.start();
    oldResult?.({
      results: [{ isFinal: true, 0: { transcript: "Старая команда" } }],
    });
    oldEnd?.();
    expect(callbacks.state).toHaveBeenLastCalledWith(true);
    expect(callbacks.final).not.toHaveBeenCalled();
    FakeRecognition.current.onresult?.({
      results: [{ isFinal: true, 0: { transcript: "Новая команда" } }],
    });
    voice.stop();
    expect(callbacks.final).toHaveBeenCalledExactlyOnceWith("Новая команда");
  });
  it("does not emit twice when an end event is delivered again", () => {
    const { voice, callbacks } = setup();
    voice.start();
    const end = FakeRecognition.current.onend;
    FakeRecognition.current.onresult?.({
      results: [{ isFinal: true, 0: { transcript: "Одна команда" } }],
    });
    voice.stop();
    end?.();
    expect(callbacks.final).toHaveBeenCalledExactlyOnceWith("Одна команда");
  });
  it("can restart after an error without sending or reporting an extra end error", () => {
    const { voice, callbacks } = setup();
    voice.start();
    const end = FakeRecognition.current.onend;
    FakeRecognition.current.onerror?.({ error: "not-allowed" });
    end?.();
    expect(callbacks.error).toHaveBeenCalledExactlyOnceWith("denied");
    expect(callbacks.final).not.toHaveBeenCalled();
    voice.start();
    expect(callbacks.state).toHaveBeenLastCalledWith(true);
    voice.cancel();
  });
});
