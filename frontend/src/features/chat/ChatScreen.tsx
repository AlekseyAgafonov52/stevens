import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, ChevronDown, Mic, Plus } from "lucide-react";
import { chat, ApiError } from "../../api";
import type { Button, ChatRequest, MessageSource } from "../../api/types";
import { apiMode, apiUrl } from "../../config/features";
import { T } from "../../content/texts";
import { Pill } from "../../components/Pill";
import { Modal } from "../../components/Modal";
import { clientTime, userTimezone } from "../../lib/clock";
import { loadFeed, remove, saveFeed, type Session } from "../../storage";
import { Answer } from "./Answer";
import { Composer } from "./Composer";
import type { Message } from "./types";

const id = () => crypto.randomUUID();
export function ChatScreen({
  session,
  onExit,
  serverStatus,
}: {
  session: Session | null;
  onExit: (expired?: boolean) => void;
  serverStatus: string;
}) {
  const feedKey = `${apiMode}:${apiUrl}:${session ? `user:${session.user.id}` : "sandbox"}`;
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
  const [modal, setModal] = useState<"new" | "reset" | null>(null);
  const [unread, setUnread] = useState(false);
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
        session?.token ?? null,
      );
      if (!mounted.current) return;
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
      if (
        error instanceof ApiError &&
        error.kind === "unauthorized" &&
        session
      ) {
        onExit(true);
        return;
      }
      setMessages((current) => [
        ...current,
        {
          id: id(),
          role: "assistant",
          text: error instanceof Error ? error.message : T.err_server,
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
    setMessages([]);
    remove(`feed:${feedKey}`);
    conversation.current = id();
    setModal(null);
    setUnread(false);
  }
  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          {messages.length > 0 && (
            <button
              className="new-dialog"
              disabled={busy || recording}
              onClick={() => setModal("new")}
              aria-label={T.btn_new_dialog}
            >
              <Plus strokeWidth={1.5} />
              <span>{T.btn_new_dialog}</span>
            </button>
          )}
        </div>
        <div className="header-brand">{T.app_name}</div>
        <div className="header-right" ref={menuRef}>
          <button
            className={session ? "avatar-button" : "mode-button"}
            aria-label={session ? T.profile_label : T.mode_mock}
            aria-expanded={menu}
            disabled={busy || recording}
            onClick={() => setMenu((value) => !value)}
          >
            {session ? (
              session.user.name.charAt(0).toUpperCase()
            ) : (
              <>
                {T.mode_mock}
                <ChevronDown strokeWidth={1.5} />
              </>
            )}
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
              {session && <p className="menu-caption">{session.user.email}</p>}
              {!session && (
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenu(false);
                    setModal("reset");
                  }}
                >
                  {T.menu_reset_sandbox}
                </button>
              )}
              <button
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  onExit();
                }}
              >
                {session ? T.menu_logout : T.menu_go_auth}
              </button>
            </div>
          )}
        </div>
      </header>
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
                  active={index === messages.length - 1 && !busy && !recording}
                  onRetry={() => {
                    if (message.request)
                      void execute(message.request, message.id);
                  }}
                  onButton={(button, buttonIndex) =>
                    send(
                      "text" in button.send ? button.send.text : button.label,
                      "button",
                      button,
                      { message: message.id, index: buttonIndex },
                    )
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
        />
        <p className="environment-note">
          {apiMode === "mock" ? T.mock_hint : T.real_hint}
        </p>
      </div>
      {modal && (
        <Modal
          title={modal === "new" ? T.new_dialog_title : T.reset_title}
          text={modal === "new" ? T.new_dialog_text : T.reset_text}
          confirm={modal === "new" ? T.new_dialog_confirm : T.reset_confirm}
          onCancel={() => setModal(null)}
          onConfirm={reset}
        />
      )}
    </main>
  );
}
