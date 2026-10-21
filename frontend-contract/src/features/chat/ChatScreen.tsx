import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  CalendarDays,
  Check,
  Mic,
  Plus,
  Volume2,
  VolumeX,
} from "lucide-react";
import { chat, ApiError } from "../../api";
import type {
  Button,
  ChatRequest,
  MessageSource,
  RecordItem,
} from "../../api/types";
import {
  apiUrl,
  featureList,
  features,
  setFeature,
} from "../../config/features";
import { T } from "../../content/texts";
import { Pill } from "../../components/Pill";
import { Modal } from "../../components/Modal";
import { Mascot, type MascotState } from "../../components/Mascot";
import { clientTime, userTimezone } from "../../lib/clock";
import {
  loadFeed,
  read,
  remove,
  saveFeed,
  write,
  type Session,
} from "../../storage";
import { speak, stopSpeaking } from "../../voice/speech";
import { CalendarPanel } from "../calendar/CalendarPanel";
import { Answer } from "./Answer";
import { Composer } from "./Composer";
import type { Message } from "./types";

const id = () => crypto.randomUUID();
export function ChatScreen({
  session,
  onExit,
  serverStatus,
}: {
  session: Session;
  onExit: (expired?: boolean) => void;
  serverStatus: string;
}) {
  const feedKey = `${apiUrl}:user:${session.user.id}`;
  const [initial] = useState<Message[]>(() =>
    loadFeed<Message>(feedKey)
      .filter(
        (item) =>
          item &&
          typeof item.id === "string" &&
          typeof item.text === "string" &&
          ["user", "assistant"].includes(item.role),
      )
      .map((item) => ({ ...item, restored: true })),
  );
  const [messages, setMessages] = useState<Message[]>(
    initial.at(-1)?.role === "user" ? initial.slice(0, -1) : initial,
  );
  const [draft, setDraft] = useState(
    initial.at(-1)?.role === "user" ? (initial.at(-1)?.text ?? "") : "",
  );
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [slow, setSlow] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [menu, setMenu] = useState(false);
  const [modal, setModal] = useState(false);
  const [unread, setUnread] = useState(false);
  // Д6: на широком экране календарь открыт справа, на телефоне — по кнопке (Р-87)
  const [calendar, setCalendar] = useState(
    () => features.d6 && matchMedia("(min-width: 1100px)").matches,
  );
  const [calendarKey, setCalendarKey] = useState(0);
  // Д12: озвучку можно приглушить кнопкой в шапке
  const [sound, setSound] = useState(() => read<boolean>("sound") !== false);
  const [speaking, setSpeaking] = useState(false);
  // Д13: увеличение сигнала включает микрофон
  const [listenSignal, setListenSignal] = useState(0);
  const conversation = useRef(id());
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const feed = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    saveFeed(feedKey, messages);
  }, [feedKey, messages]);
  useEffect(() => {
    if (!busy) {
      setSlow(false);
      setThinking(false);
      return;
    }
    const dots = setTimeout(() => setThinking(true), 300);
    const label = setTimeout(() => setSlow(true), 8000);
    return () => {
      clearTimeout(dots);
      clearTimeout(label);
    };
  }, [busy]);
  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenu(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(false);
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);

  const scrollDown = useCallback(() => {
    feed.current?.scrollTo({
      top: feed.current.scrollHeight,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
    setUnread(false);
  }, []);

  async function execute(payload: ChatRequest, retryId?: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    if (retryId)
      setMessages((current) =>
        current.filter((message) => message.id !== retryId),
      );
    try {
      const response = await chat(
        { ...payload, client_time: clientTime() },
        session.token,
      );
      if (!mounted.current) return;
      setCalendarKey((value) => value + 1);
      // Д13: после вопроса ассистента сами включаем микрофон, если человек говорил голосом
      const listen =
        features.d13 && response.awaiting_reply && payload.source === "voice";
      const after = () => {
        if (!mounted.current) return;
        setSpeaking(false);
        if (listen) setListenSignal((value) => value + 1);
      };
      if (features.d12 && sound) {
        setSpeaking(true);
        speak(response.speech ?? response.text, after);
      } else after();
      const container = feed.current;
      const nearBottom =
        !container ||
        container.scrollHeight - container.scrollTop - container.clientHeight <
          200;
      setMessages((current) => [
        ...current,
        {
          id: response.message_id,
          role: "assistant",
          text: response.text,
          response,
          error: response.kind === "error",
          request: payload,
        },
      ]);
      if (nearBottom) requestAnimationFrame(scrollDown);
      else setUnread(true);
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ApiError && error.kind === "unauthorized") {
        onExit(true);
        return;
      }
      setMessages((current) => [
        ...current,
        {
          id: id(),
          role: "assistant",
          text: error instanceof Error ? error.message : T.err_server,
          detail: error instanceof ApiError ? error.detail : undefined,
          error: true,
          request: payload,
        },
      ]);
      requestAnimationFrame(scrollDown);
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function send(
    text: string,
    source: MessageSource = "text",
    button?: Button,
    selected?: { message: string; index: number },
  ) {
    const trimmed = text.trim();
    if (
      !trimmed ||
      trimmed.length > 300 ||
      inFlight.current ||
      (recording && source !== "voice")
    )
      return;
    setMessages((current) => [
      ...current.map((message) =>
        selected?.message === message.id
          ? { ...message, selectedButton: selected.index }
          : message,
      ),
      { id: id(), role: "user", text: button?.label ?? trimmed, source },
    ]);
    setDraft("");
    stopSpeaking();
    const payload: ChatRequest = {
      conversation_id: conversation.current,
      text: trimmed,
      source,
      action: button && "action" in button.send ? button.send.action : null,
      client_time: clientTime(),
      timezone: userTimezone(),
    };
    void execute(payload);
    requestAnimationFrame(scrollDown);
  }
  function reset() {
    stopSpeaking();
    setMessages([]);
    remove(`feed:${feedKey}`);
    conversation.current = id();
    setModal(false);
    setUnread(false);
  }
  function recordSaved(messageId: string, record: RecordItem) {
    setMessages((current) =>
      current.map((message) =>
        message.id === messageId && message.response
          ? {
              ...message,
              response: {
                ...message.response,
                records: message.response.records.map((item) =>
                  item.id === record.id ? record : item,
                ),
              },
              edited: [...(message.edited ?? []), record.id!],
            }
          : message,
      ),
    );
    setCalendarKey((value) => value + 1);
  }
  const mascot: MascotState = recording
    ? "listening"
    : busy
      ? "thinking"
      : speaking
        ? "speaking"
        : "idle";
  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          {messages.length > 0 && (
            <button
              className="new-dialog"
              disabled={busy || recording}
              onClick={() => setModal(true)}
              aria-label={T.btn_new_dialog}
            >
              <Plus strokeWidth={1.5} />
              <span>{T.btn_new_dialog}</span>
            </button>
          )}
        </div>
        <div className="header-brand">
          {features.d14 && <Mascot state={mascot} size={30} />}
          {T.app_name}
        </div>
        <div className="header-right" ref={menuRef}>
          {features.d12 && (
            <button
              className="icon-plain"
              aria-label={sound ? T.sound_on : T.sound_off}
              aria-pressed={sound}
              onClick={() => {
                if (sound) stopSpeaking();
                setSound(!sound);
                write("sound", !sound);
              }}
            >
              {sound ? (
                <Volume2 strokeWidth={1.5} />
              ) : (
                <VolumeX strokeWidth={1.5} />
              )}
            </button>
          )}
          {features.d6 && (
            <button
              className="icon-plain"
              aria-label={calendar ? T.cal_close : T.cal_open}
              aria-pressed={calendar}
              onClick={() => setCalendar((value) => !value)}
            >
              <CalendarDays strokeWidth={1.5} />
            </button>
          )}
          <button
            className="avatar-button"
            aria-label={T.profile_label}
            aria-expanded={menu}
            disabled={busy || recording}
            onClick={() => setMenu((value) => !value)}
          >
            {session.user.name.charAt(0).toUpperCase()}
          </button>
          {menu && (
            <div
              className="profile-menu"
              role="menu"
              onKeyDown={(event) => {
                if (event.key !== "ArrowDown" && event.key !== "ArrowUp")
                  return;
                event.preventDefault();
                const items = Array.from(
                  event.currentTarget.querySelectorAll<HTMLButtonElement>(
                    "button",
                  ),
                );
                const current = items.indexOf(
                  document.activeElement as HTMLButtonElement,
                );
                items[
                  (current +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    items.length) %
                    items.length
                ]?.focus();
              }}
            >
              <p className="menu-caption">{session.user.email}</p>
              <p className="menu-section">{T.menu_features}</p>
              {featureList.map((feature) => (
                <button
                  key={feature.id}
                  role="menuitemcheckbox"
                  aria-checked={features[feature.id]}
                  className="menu-check"
                  onClick={() => {
                    setFeature(feature.id, !features[feature.id]);
                    location.reload();
                  }}
                >
                  <span className="menu-check-box">
                    {features[feature.id] && <Check strokeWidth={2} />}
                  </span>
                  {feature.title}
                </button>
              ))}
              <p className="menu-hint">{T.features_hint}</p>
              <button
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  stopSpeaking();
                  onExit();
                }}
              >
                {T.menu_logout}
              </button>
            </div>
          )}
        </div>
      </header>
      <div className="app-body">
        <div className="chat-column">
          <div
            className="feed"
            ref={feed}
            onScroll={() => {
              const node = feed.current;
              if (
                node &&
                node.scrollHeight - node.scrollTop - node.clientHeight < 200
              )
                setUnread(false);
            }}
          >
            {messages.length === 0 ? (
              <div className="start-screen">
                {features.d14 && <Mascot state={mascot} size={96} />}
                <p>{T.start_subtitle}</p>
                <div className="pill-row" aria-label={T.examples_label}>
                  {T.examples.map((example) => (
                    <Pill
                      key={example}
                      disabled={busy || recording}
                      onClick={() => send(example, "button")}
                    >
                      {example}
                    </Pill>
                  ))}
                </div>
              </div>
            ) : (
              <div
                className="feed-column"
                role="log"
                aria-label={T.messages_label}
                aria-live="polite"
              >
                {messages.map((message, index) =>
                  message.role === "user" ? (
                    <div className="user-message" key={message.id}>
                      {message.source === "voice" && (
                        <Mic strokeWidth={1.5} aria-hidden="true" />
                      )}
                      <p>{message.text}</p>
                    </div>
                  ) : (
                    <Answer
                      key={message.id}
                      message={message}
                      token={session.token}
                      active={
                        index === messages.length - 1 && !busy && !recording
                      }
                      locked={busy || recording}
                      onRetry={() => {
                        if (message.request)
                          void execute(message.request, message.id);
                      }}
                      onButton={(button, buttonIndex) =>
                        send(
                          "text" in button.send
                            ? button.send.text
                            : button.label,
                          "button",
                          button,
                          { message: message.id, index: buttonIndex },
                        )
                      }
                      onRecordSaved={(record) =>
                        recordSaved(message.id, record)
                      }
                    />
                  ),
                )}
                {busy && thinking && (
                  <div className="thinking-line" role="status">
                    <span className="thinking">
                      <i />
                      <i />
                      <i />
                    </span>
                    {slow && <span>{T.thinking_slow}</span>}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="app-bottom">
            {unread && (
              <Pill className="scroll-new" onClick={scrollDown}>
                <ArrowDown strokeWidth={1.5} />
                {T.scroll_to_new}
              </Pill>
            )}
            <Composer
              busy={busy}
              value={draft}
              onChange={setDraft}
              onSend={send}
              onRecording={setRecording}
              status={serverStatus}
              listenSignal={listenSignal}
            />
            <p className="environment-note">{T.real_hint}</p>
          </div>
        </div>
        {features.d6 && calendar && (
          <CalendarPanel
            token={session.token}
            refreshKey={calendarKey}
            onClose={() => setCalendar(false)}
            onUnauthorized={() => onExit(true)}
          />
        )}
      </div>
      {modal && (
        <Modal
          title={T.new_dialog_title}
          text={T.new_dialog_text}
          confirm={T.new_dialog_confirm}
          onCancel={() => setModal(false)}
          onConfirm={reset}
        />
      )}
    </main>
  );
}
