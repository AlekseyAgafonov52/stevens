/* Пуш-уведомления Stevens, как в мессенджере: человек не на вкладке — пуш, на вкладке — пуша нет,
   там сообщение Стивенса появляется само. Клик по пушу — открыть или показать вкладку. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const visible = list.filter((c) => c.visibilityState === 'visible');
      if (visible.length) {
        visible.forEach((c) => c.postMessage({ type: 'stevens-reminder', tag: data.tag }));
        return undefined;
      }
      return self.registration.showNotification(data.title || 'Stevens', {
        body: data.body || '',
        tag: data.tag,
        icon: '/icon-192.png',
        badge: '/icon-192.png',
        requireInteraction: true,
        data: { url: '/' },
      });
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const open = list.find((c) => 'focus' in c);
      return open ? open.focus() : self.clients.openWindow('/');
    }),
  );
});
