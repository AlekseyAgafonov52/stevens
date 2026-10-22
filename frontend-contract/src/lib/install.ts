/**
 * PWA: «Установить как приложение». Chrome и Edge присылают beforeinstallprompt, когда страницу можно установить;
 * сохраняем его и показываем пункт меню. Safari такого события не шлёт — там «Файл → Добавить в Dock», пункта нет.
 */
import { useSyncExternalStore } from 'react';

interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferred: InstallPrompt | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferred = event as InstallPrompt;
    notify();
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    notify();
  });
}

export function useCanInstall(): boolean {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => deferred !== null,
    () => false,
  );
}

export async function install(): Promise<void> {
  const prompt = deferred;
  if (!prompt) return;
  await prompt.prompt();
  await prompt.userChoice;
  deferred = null;
  notify();
}

/** Уже открыто как установленное приложение — пункт меню не нужен */
export function isInstalled(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true;
}

/** Подсказка, как установить вручную, когда браузер не прислал beforeinstallprompt (Safari, Firefox, Chrome без манифеста) */
export function installHintKey(): 'install_safari' | 'install_manual' {
  const ua = navigator.userAgent;
  return /Safari/.test(ua) && !/Chrome|Chromium|Edg|CriOS|Android/.test(ua) ? 'install_safari' : 'install_manual';
}
