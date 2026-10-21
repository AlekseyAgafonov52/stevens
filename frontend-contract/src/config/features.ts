/**
 * Допы контракта v1.4 (раздел 15). По умолчанию включены все; значение по
 * умолчанию можно поменять при сборке (VITE_FEATURE_D2=false и т. п.), а
 * каждый доп — включить или выключить на лету в меню профиля «Допы».
 * Выбор хранится в браузере, после переключения страница перезагружается.
 */
export type FeatureId = "d2" | "d3" | "d10" | "d6" | "d12" | "d13" | "d14";

export const featureList: { id: FeatureId; title: string; backend: boolean }[] =
  [
    { id: "d2", title: "Д2 Удаление", backend: true },
    { id: "d3", title: "Д3 Отметка выполненной", backend: true },
    { id: "d10", title: "Д10 Отменить и исправить", backend: true },
    { id: "d6", title: "Д6 Календарь", backend: true },
    { id: "d12", title: "Д12 Озвучка", backend: false },
    { id: "d13", title: "Д13 Автослушание", backend: false },
    { id: "d14", title: "Д14 Персонаж", backend: false },
  ];

const storageKey = "stevens-contract:features";

function defaults(): Record<FeatureId, boolean> {
  return Object.fromEntries(
    featureList.map(({ id }) => [
      id,
      import.meta.env[`VITE_FEATURE_${id.toUpperCase()}`] !== "false",
    ]),
  ) as Record<FeatureId, boolean>;
}

function load(): Record<FeatureId, boolean> {
  const result = defaults();
  try {
    const saved = JSON.parse(
      localStorage.getItem(storageKey) ?? "{}",
    ) as Partial<Record<FeatureId, unknown>>;
    for (const { id } of featureList)
      if (typeof saved[id] === "boolean") result[id] = saved[id];
  } catch {
    /* Хранилище необязательно. */
  }
  return result;
}

export const features: Readonly<Record<FeatureId, boolean>> = load();

export function setFeature(id: FeatureId, value: boolean): void {
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify({ ...features, [id]: value }),
    );
  } catch {
    /* Хранилище необязательно. */
  }
}

/** Значение заголовка X-Stevens-Features (15.2): только допы, которым нужен бэк в /api/chat */
export function featuresHeader(): string {
  return (["d2", "d3", "d10"] as const).filter((id) => features[id]).join(",");
}

/** Адрес бэка. Пусто — тот же адрес, что у страницы (nginx проксирует /api) */
export const apiUrl: string = import.meta.env.VITE_API_URL ?? "";
