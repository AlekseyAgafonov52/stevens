/** События для допов (09-extensions.md, раздел 2): onAssistantResponse и onUiActivity. */
import type { ChatRequest, ChatResponse } from '../api/types';

export type UiActivity =
  | 'typing'
  | 'recording-start'
  | 'recording-stop'
  | 'request-start'
  | 'request-end'
  | 'button-press'
  | 'new-dialog'
  | 'tab-hidden'
  /** Сохранена форма «Исправить» в ленте (Д10) — персонаж «готово» */
  | 'edit-saved';

type ResponseListener = (response: ChatResponse, request: ChatRequest) => void;
type ActivityListener = (kind: UiActivity) => void;

const responseListeners = new Set<ResponseListener>();
const activityListeners = new Set<ActivityListener>();

export function onAssistantResponse(listener: ResponseListener): () => void {
  responseListeners.add(listener);
  return () => responseListeners.delete(listener);
}

export function onUiActivity(listener: ActivityListener): () => void {
  activityListeners.add(listener);
  return () => activityListeners.delete(listener);
}

export function emitResponse(response: ChatResponse, request: ChatRequest): void {
  responseListeners.forEach((listener) => listener(response, request));
}

export function emitActivity(kind: UiActivity): void {
  activityListeners.forEach((listener) => listener(kind));
}

/** Календарь перечитывается после своих правок в ленте (Д10) */
const recordsChangedListeners = new Set<() => void>();
export function onRecordsChanged(listener: () => void): () => void {
  recordsChangedListeners.add(listener);
  return () => recordsChangedListeners.delete(listener);
}
export function emitRecordsChanged(): void {
  recordsChangedListeners.forEach((listener) => listener());
}

/** Озвучка (Д12) для автослушания (Д13): start — начали говорить, end — договорили, cancelled — оборвали */
export type SpeechPhase = 'start' | 'end' | 'cancelled';
const speechListeners = new Set<(phase: SpeechPhase) => void>();
let speaking = false;
export function isSpeaking(): boolean {
  return speaking;
}
export function onSpeech(listener: (phase: SpeechPhase) => void): () => void {
  speechListeners.add(listener);
  return () => speechListeners.delete(listener);
}
export function emitSpeech(phase: SpeechPhase): void {
  speaking = phase === 'start';
  speechListeners.forEach((listener) => listener(phase));
}

/** Персонаж (Д14) кланяется после входа: экран чата появляется позже события, поэтому флаг, а не событие */
let greeting = false;
export function requestGreeting(): void {
  greeting = true;
}
export function takeGreeting(): boolean {
  const value = greeting;
  greeting = false;
  return value;
}
