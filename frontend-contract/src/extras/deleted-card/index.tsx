/** Состояние карточки «Удалено» (Д2, Д10) — 07-extras.md, раздел 5. Вид «приглушённой» даёт карточка. */
import { T } from '../../content/texts';

export function DeletedLabel() {
  return <span className="card__state">{T.label_deleted}</span>;
}
