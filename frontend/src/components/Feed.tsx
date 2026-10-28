/** Лента */
import { ArrowDown, CircleAlert, Mic, RotateCw } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { T } from '../content/texts';
import { useMedia } from '../lib/install';
import { useBriefingOffer } from '../state/briefing';
import { retry, send } from '../state/chat';
import { emitActivity } from '../state/events';
import { lastAnswerId, store, useApp, type FeedMessage, type PendingMessage } from '../state/store';
import { Answer } from './Answer';
import { BriefingOffer } from './BriefingOffer';
import { Pill } from './Pill';

const NEAR_BOTTOM = 200;
const SLOW_AFTER = 8000;

function Thinking({ message }: { message: PendingMessage }) {
  const server = useApp((s) => s.server);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), Math.max(0, SLOW_AFTER - (Date.now() - message.startedAt)));
    return () => clearTimeout(timer);
  }, [message.startedAt]);
  if (server === 'waking') {
    return <div className="thinking" aria-hidden="true"><span className="thinking__text">{T.status_waking}</span></div>;
  }
  // Пока ждём ответ, думает персонаж; через 8 с — подпись
  if (!slow) return <div className="thinking thinking--empty" />;
  return (
    <div className="thinking" aria-hidden="true">
      <span className="thinking__text">{T.thinking_slow}</span>
    </div>
  );
}

function FeedItem({ message, isLast, lastError }: { message: FeedMessage; isLast: boolean; lastError: boolean }) {
  const waiting = useApp((s) => s.waiting);
  if (message.kind === 'user') {
    return (
      <div className="user-row anim-appear">
        <div className="bubble">
          {message.source === 'voice' && <Mic className="bubble__mic" size={14} strokeWidth={1.5} aria-hidden="true" />}
          <span>{message.text}</span>
        </div>
      </div>
    );
  }
  if (message.kind === 'pending') return <Thinking message={message} />;
  if (message.kind === 'error') {
    return (
      <div className="answer anim-appear">
        <div className="feed-error">
          <CircleAlert className="feed-error__icon" size={18} strokeWidth={1.5} aria-hidden="true" />
          <span>{message.text}</span>
        </div>
        <div className="answer__buttons">
          <Pill
            variant={lastError && !waiting ? 'primary' : 'dimmed'}
            icon={<RotateCw size={15} strokeWidth={1.5} aria-hidden="true" />}
            onClick={() => retry(message.id)}
          >
            {T.btn_retry}
          </Pill>
        </div>
      </div>
    );
  }
  return <Answer message={message} isLast={isLast} />;
}

function StartScreen() {
  const waiting = useApp((s) => s.waiting);
  const offer = useBriefingOffer();
  const phone = useMedia('(max-width: 760px)');
  const examples = phone ? T.examples_phone : T.examples_desktop;
  return (
    <div className="start">
      <div className="start__subtitle">{T.start_lead}</div>
      {offer ? (
        <BriefingOffer className="start__offer" />
      ) : (
        <div className="start__examples">
          <div className="start__caption">{T.examples_caption}</div>
          {examples.map((example) => (
            <Pill key={example} className="pill--example" disabled={waiting} onClick={() => { emitActivity('button-press'); send(example, 'button'); }}>
              {example}
            </Pill>
          ))}
        </div>
      )}
    </div>
  );
}

export function Feed() {
  const messages = useApp((s) => s.messages);
  const unseen = useApp((s) => s.unseen);
  const ref = useRef<HTMLDivElement>(null);
  const count = useRef(messages.length);
  /** Был ли человек внизу до прихода ответа */
  const atBottom = useRef(true);
  const lastAnswer = lastAnswerId(messages);
  const last = messages[messages.length - 1];

  const nearBottom = () => {
    const el = ref.current;
    return !el || el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
  };
  const toBottom = (smooth: boolean) => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  // Восстановленная лента — сразу внизу
  useLayoutEffect(() => {
    toBottom(false);
  }, []);

  useLayoutEffect(() => {
    const previous = count.current;
    count.current = messages.length;
    if (messages.length <= previous) return;
    const added = messages.slice(previous);
    if (added.some((m) => m.kind === 'user')) {
      toBottom(false); // своя отправка — всегда вниз
      atBottom.current = true;
      store.set({ unseen: 0 });
    }
  }, [messages]);

  // Пришёл ответ (pending → answer/error): внизу — вниз, выше — «К новым»
  const lastKind = last?.kind;
  const lastId = last?.id;
  const wasPending = useRef(false);
  useEffect(() => {
    if (lastKind === 'pending') {
      wasPending.current = true;
      return;
    }
    if (!wasPending.current) return;
    wasPending.current = false;
    if (atBottom.current) toBottom(true);
    else store.set((s) => ({ unseen: s.unseen + 1 }));
  }, [lastKind, lastId]);

  const onScroll = () => {
    atBottom.current = nearBottom();
    if (unseen && atBottom.current) store.set({ unseen: 0 });
  };

  const lastErrorId = last && last.kind === 'error' ? last.id : null;

  return (
    <div className="feed-wrap">
      <div ref={ref} className="feed feed--with-mascot" role="log" aria-live="polite" onScroll={onScroll}>
        {messages.length === 0 ? (
          <StartScreen />
        ) : (
          <div className="feed__column">
            {messages.map((m) => (
              <FeedItem key={m.id} message={m} isLast={m.id === lastAnswer} lastError={m.id === lastErrorId} />
            ))}
            <BriefingOffer className="feed__offer" />
          </div>
        )}
      </div>
      {unseen > 0 && (
        <div className="to-new">
          <Pill
            className="to-new__pill"
            icon={<ArrowDown size={16} strokeWidth={1.5} aria-hidden="true" />}
            onClick={() => { store.set({ unseen: 0 }); toBottom(true); }}
          >
            {T.scroll_to_new}
          </Pill>
        </div>
      )}
    </div>
  );
}
