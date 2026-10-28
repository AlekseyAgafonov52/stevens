/** Плашка «Рассказать план на сегодня?» — вместо примеров в пустом чате или в конце ленты. */
import { T, fill } from '../content/texts';
import { pluralKey } from '../lib/dates';
import { acceptBriefing, declineBriefing, useBriefingOffer } from '../state/briefing';
import { emitActivity } from '../state/events';
import { useApp } from '../state/store';
import { Pill } from './Pill';

export function BriefingOffer({ className = '' }: { className?: string }) {
  const offer = useBriefingOffer();
  const busy = useApp((s) => s.waiting || s.recording);
  if (!offer) return null;
  return (
    <div className={`offer ${className}`} role="group" aria-label={T.briefing_title}>
      <div className="offer__title">{T.briefing_title}</div>
      <div className="offer__text">{fill(T[`briefing_count_${pluralKey(offer.count)}`], { count: offer.count })}</div>
      <div className="offer__actions">
        <Pill variant="primary" disabled={busy} onClick={() => { emitActivity('button-press'); acceptBriefing(); }}>{T.wake_yes}</Pill>
        <Pill variant="secondary" onClick={() => { emitActivity('button-press'); declineBriefing(); }}>{T.wake_no}</Pill>
      </div>
    </div>
  );
}
