/** Строка статуса: один текст за раз, по приоритету. */
import { CircleAlert } from 'lucide-react';
import { T } from '../content/texts';
import { useApp } from '../state/store';

type Key = keyof typeof T;

export function StatusLine() {
  const server = useApp((s) => s.server);
  const resetError = useApp((s) => s.resetError);
  const hint = useApp((s) => s.hint);
  const atLimit = useApp((s) => s.input.length >= 300 && !s.recording);

  if (server === 'down') {
    return (
      <div className="status status--alarm" role="status">
        <CircleAlert size={14} strokeWidth={1.5} aria-hidden="true" />
        {T.status_server_down}
      </div>
    );
  }
  let key: Key | null = null;
  if (server === 'waking') key = 'status_waking';
  else if (resetError) key = resetError.key as Key;
  else if (hint) key = hint.key as Key;
  else if (atLimit) key = 'char_limit';
  if (!key) return null;
  return <div className="status" role="status">{String(T[key])}</div>;
}
