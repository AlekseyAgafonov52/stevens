/**
 * Точки расширения: места на экране для допов. Код допа грузится динамическим импортом;
 * фича выключена на сервере (GET /api/health) — точка пуста.
 */
import { lazy, Suspense, useSyncExternalStore, type ReactNode } from 'react';
import type { RecordItem } from '../api/types';
import { serverFeatures, serverHas, type ServerFeature } from '../config/server';
import { store, type AnswerMessage } from '../state/store';

const calendar = () => import('../extras/calendar');
const edit = () => import('../extras/edit');
const mascot = () => import('../extras/mascot');
const deleted = () => import('../extras/deleted-card');
const tour = () => import('../extras/tour');

const CalendarToggle = lazy(() => calendar().then((m) => ({ default: m.CalendarToggle })));
const CalendarPanel = lazy(() => calendar().then((m) => ({ default: m.CalendarPanel })));
const EditButton = lazy(() => edit().then((m) => ({ default: m.EditButton })));
const FeedEditForm = lazy(() => edit().then((m) => ({ default: m.FeedEditForm })));
const MascotPerch = lazy(() => mascot().then((m) => ({ default: m.MascotPerch })));
const MascotTitle = lazy(() => mascot().then((m) => ({ default: m.MascotTitle })));
const TourBar = lazy(() => tour().then((m) => ({ default: m.TourBar })));
const DeletedLabel = lazy(() => deleted().then((m) => ({ default: m.DeletedLabel })));

const wrap = (node: ReactNode) => <Suspense fallback={null}>{node}</Suspense>;

/** Фича включена на сервере (GET /api/health): нет — места на экране не занимает */
function useServer(key: ServerFeature): boolean {
  useSyncExternalStore(serverFeatures.subscribe, serverFeatures.get);
  return serverHas(key);
}

/** Д6 / Ф13: кнопка календаря в шапке */
export function HeaderRightStart() {
  const on = useServer('f13');
  return on ? wrap(<CalendarToggle />) : null;
}

/** Д6 / Ф13: панель календаря справа */
export function LayoutSidePanel() {
  const on = useServer('f13');
  const editing = useServer('f12');
  return on ? wrap(<CalendarPanel canComplete={editing} canDelete={editing} />) : null;
}

/** Д10: «Исправить» первой в ряду кнопок ответа created с одной записью; активна только у последнего */
export function AnswerExtraButtons({ message, isLast }: { message: AnswerMessage; isLast: boolean }) {
  const on = useServer('f12');
  if (!on) return null;
  const { response } = message;
  if (response.kind !== 'created' || response.records.length !== 1 || response.records[0].id === null) return null;
  if (response.records[0].marks.includes('deleted')) return null;
  return wrap(<EditButton message={message} isLast={isLast} />);
}

/**
 * Д10: в ответе created с несколькими записями (плотный график) любую карточку можно открыть
 * и поправить нажатием. undefined — карточка не нажимается
 */
export function cardEditHandler(message: AnswerMessage, record: RecordItem, active: boolean) {
  const { response } = message;
  if (!active || response.kind !== 'created' || response.records.length < 2) return undefined;
  if (record.id === null || record.marks.includes('deleted')) return undefined;
  const id = record.id;
  return () => store.set({ editing: { messageId: message.id, recordId: id } });
}

/** Д10: форма правки на месте карточки в ленте. null — обычная карточка */
export function RecordCardOverride({ message, record, editing }: { message: AnswerMessage; record: RecordItem; editing: boolean }) {
  if (!editing) return null;
  return wrap(<FeedEditForm message={message} record={record} />);
}

/** Состояние «Удалено» (Д2 или Д10): подпись в мете */
export function RecordCardState({ record }: { record: RecordItem }) {
  if (!record.marks.includes('deleted')) return null;
  return wrap(<DeletedLabel />);
}

/** Д14: персонаж на строке ввода */
export function InputBarOverlay() {
  const on = useServer('f22');
  return on ? wrap(<MascotPerch />) : null;
}

/** Д14: персонаж справа от «Stevens» на экране входа */
export function LoginTitleAside() {
  const on = useServer('f22');
  return on ? wrap(<MascotTitle />) : null;
}

/** Д15: обучение в песочнице — над строкой статуса */
export function BottomTop() {
  const on = useServer('f23');
  return on ? wrap(<TourBar />) : null;
}

/** Д15: «Пройти обучение» в меню песочницы и аккаунта */
export function tourMenuItem(label: string): { label: string; onSelect: () => void }[] {
  return serverHas('f23') ? [{ label, onSelect: () => void import('../extras/tour/state').then((m) => m.startTour()) }] : [];
}
