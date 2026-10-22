/* Пуш-уведомления Stevens, как в мессенджере: человек не на вкладке — пуш, на вкладке — пуша нет,
   там сообщение Стивенса появляется само. У пуша кнопки «Посмотреть» и «Через 10 минут»:
   «Посмотреть» (и клик по самому пушу) открывает приложение, и Стивенс присылает запись в чат,
   «Через 10 минут» просит сервер напомнить ещё раз. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

const ACTIONS = [
  { action: 'view', title: 'Посмотреть' },
  { action: 'snooze', title: 'Через 10 минут' },
];

/** Номер записи из tag вида «id@дата Tвремя» — если сервер его не прислал отдельно */
function recordIdOf(data) {
  if (Number.isInteger(data.record_id)) return data.record_id;
  const id = parseInt(String(data.tag || '').split('@')[0], 10);
  return Number.isInteger(id) ? id : null;
}

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }
  const recordId = recordIdOf(data);
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const visible = list.filter((c) => c.visibilityState === 'visible');
      if (visible.length) {
        visible.forEach((c) => c.postMessage({ type: 'stevens-reminder', tag: data.tag, recordId, snoozed: !!data.snoozed }));
        return undefined;
      }
      return self.registration.showNotification(data.title || 'Stevens', {
        body: data.body || '',
        tag: data.tag,
        renotify: !!data.snoozed,
        icon: '/icon-192.png',
        badge: '/icon-192.png',
        requireInteraction: true,
        actions: recordId === null ? [] : ACTIONS,
        data: { recordId },
      });
    }),
  );
});

/** Открыть вкладку и попросить Стивенса показать запись в чате */
function openRecord(recordId) {
  return self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    const open = list.find((c) => 'focus' in c);
    if (open) {
      if (recordId !== null) open.postMessage({ type: 'stevens-open', recordId });
      return open.focus();
    }
    return self.clients.openWindow(recordId === null ? '/' : `/?remind=${recordId}`);
  });
}

/** «Через 10 минут»: сервер узнаёт браузер по адресу подписки. Пуша нет — откладывает открытая вкладка */
function snooze(recordId) {
  return self.registration.pushManager.getSubscription()
    .then((sub) => {
      if (!sub) throw new Error('no subscription');
      return fetch('/api/push/snooze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: sub.endpoint, record_id: recordId }),
      });
    })
    .then((response) => {
      if (!response.ok) throw new Error(String(response.status));
    })
    .catch(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((list) => list.forEach((c) => c.postMessage({ type: 'stevens-snooze', recordId }))));
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const recordId = event.notification.data?.recordId ?? recordIdOf({ tag: event.notification.tag });
  if (event.action === 'snooze' && recordId !== null) {
    event.waitUntil(snooze(recordId));
    return;
  }
  event.waitUntil(openRecord(recordId));
});
