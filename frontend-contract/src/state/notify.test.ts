import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./chat', () => ({ setHint: vi.fn() }));
vi.mock('../api', () => ({ api: { records: vi.fn(async () => []) } }));

const { setHint } = await import('./chat');
const { enableNotify, notifyStore } = await import('./notify');

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

function iphone(standalone: boolean) {
  vi.stubGlobal('navigator', { userAgent: 'iPhone', standalone });
  vi.stubGlobal('window', { matchMedia: () => ({ matches: standalone }) });
}

describe('включение уведомлений на iPhone', () => {
  it('в Safari показывает существующую подсказку установки', async () => {
    iphone(false);
    await enableNotify();
    expect(setHint).toHaveBeenCalledWith('install_safari');
  });

  it('запрашивает разрешение сразу при нажатии и обрабатывает отказ API', async () => {
    iphone(true);
    const requestPermission = vi.fn(() => Promise.reject(new Error('unavailable')));
    const notification = { permission: 'default', requestPermission };
    vi.stubGlobal('Notification', notification);
    Object.assign(window, { Notification: notification });
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const pending = enableNotify();
    expect(requestPermission).toHaveBeenCalledOnce();
    await pending;
    expect(notifyStore.get().on).toBe(false);
    expect(setHint).toHaveBeenCalledWith('err_server');
    vi.restoreAllMocks();
  });
});
