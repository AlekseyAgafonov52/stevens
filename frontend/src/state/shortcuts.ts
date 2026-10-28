/**
 * Ярлыки установленного приложения (долгое нажатие на иконку, manifest.webmanifest → shortcuts):
 * /?do=new — поле ввода с «Напомни », /?do=today — вопрос «Что у меня сегодня?».
 * Срабатывают, как только открылся чат (после входа, если нужно войти).
 */
import { send } from './chat';
import { store } from './store';

const NEW_PREFIX = 'Напомни ';

function takeParam(): string | null {
  if (typeof location === 'undefined') return null;
  const url = new URL(location.href);
  const value = url.searchParams.get('do');
  if (value === null) return null;
  url.searchParams.delete('do');
  history.replaceState(history.state, '', url);
  return value;
}

function focusInput(): void {
  setTimeout(() => {
    const field = document.querySelector<HTMLTextAreaElement>('.composer__field textarea');
    if (!field) return;
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  }, 50);
}

export function initShortcuts(): void {
  let pending = takeParam();
  if (pending !== 'new' && pending !== 'today') return;
  const run = () => {
    const state = store.get();
    if (!pending || state.screen !== 'app' || state.waiting || state.recording) return;
    const what = pending;
    pending = null;
    unsubscribe();
    // Не меняем store прямо из его же подписчика
    queueMicrotask(() => {
      if (what === 'new') {
        store.set({ input: NEW_PREFIX });
        focusInput();
      } else send('Что у меня сегодня?', 'text');
    });
  };
  const unsubscribe = store.subscribe(run);
  run();
}
