/**
 * Что сервер умеет сверх основного: список из GET /api/health. Сейчас там бывает только `stt` —
 * распознавание речи на сервере, когда есть ключ Yandex Cloud. Список держим до перезагрузки.
 */
import { createStore } from '../state/store';

export type ServerFeature = 'stt';

const serverFeatures = createStore<{ list: string[] | null }>({ list: null });

export function setServerFeatures(list: string[] | null): void {
  if (list === null && serverFeatures.get().list !== null) return;
  serverFeatures.set({ list });
}

export function serverHas(key: ServerFeature): boolean {
  return !!serverFeatures.get().list?.includes(key);
}
