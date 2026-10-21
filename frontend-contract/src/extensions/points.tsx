/**
 * Точки расширения — 09-extensions.md, раздел 2. Флаг проверяется только здесь;
 * код допа грузится динамическим импортом. Флаги выключены — точки пусты.
 */
import { lazy, Suspense, type ReactNode } from 'react';
import type { RecordItem } from '../api/types';
import { features } from '../config/features';
import type { AnswerMessage } from '../state/store';

const calendar = () => import('../extras/calendar');
const edit = () => import('../extras/edit');
const mascot = () => import('../extras/mascot');
const deleted = () => import('../extras/deleted-card');

const CalendarToggle = features.d6_calendar ? lazy(() => calendar().then((m) => ({ default: m.CalendarToggle }))) : null;
const CalendarPanel = features.d6_calendar ? lazy(() => calendar().then((m) => ({ default: m.CalendarPanel }))) : null;
const EditButton = features.d10_undo ? lazy(() => edit().then((m) => ({ default: m.EditButton }))) : null;
const FeedEditForm = features.d10_undo ? lazy(() => edit().then((m) => ({ default: m.FeedEditForm }))) : null;
const MascotPerch = features.d14_mascot ? lazy(() => mascot().then((m) => ({ default: m.MascotPerch }))) : null;
const MascotTitle = features.d14_mascot ? lazy(() => mascot().then((m) => ({ default: m.MascotTitle }))) : null;
const DeletedLabel =
  features.d2_delete || features.d10_undo ? lazy(() => deleted().then((m) => ({ default: m.DeletedLabel }))) : null;

const wrap = (node: ReactNode) => <Suspense fallback={null}>{node}</Suspense>;

/** Д6: кнопка календаря в шапке */
export function HeaderRightStart() {
  return CalendarToggle ? wrap(<CalendarToggle />) : null;
}

/** Д6: панель календаря справа */
export function LayoutSidePanel() {
  return CalendarPanel ? wrap(<CalendarPanel canComplete={features.d3_complete} canDelete={features.d2_delete} />) : null;
}

/** Д10: «Исправить» первой в ряду кнопок ответа created с одной записью; активна только у последнего */
export function AnswerExtraButtons({ message, isLast }: { message: AnswerMessage; isLast: boolean }) {
  if (!EditButton) return null;
  const { response } = message;
  if (response.kind !== 'created' || response.records.length !== 1 || response.records[0].id === null) return null;
  if (response.records[0].marks.includes('deleted')) return null;
  return wrap(<EditButton message={message} isLast={isLast} />);
}

/** Д10: форма правки на месте карточки в ленте. null — обычная карточка */
export function RecordCardOverride({ message, record, editing }: { message: AnswerMessage; record: RecordItem; editing: boolean }) {
  if (!FeedEditForm || !editing) return null;
  return wrap(<FeedEditForm message={message} record={record} />);
}

/** Состояние «Удалено» (Д2 или Д10): подпись в мете */
export function RecordCardState({ record }: { record: RecordItem }) {
  if (!DeletedLabel || !record.marks.includes('deleted')) return null;
  return wrap(<DeletedLabel />);
}

/** Д14: персонаж на строке ввода */
export function InputBarOverlay() {
  return MascotPerch ? wrap(<MascotPerch />) : null;
}

/** Д14: персонаж справа от «Stevens» на экране входа */
export function LoginTitleAside() {
  return MascotTitle ? wrap(<MascotTitle />) : null;
}
