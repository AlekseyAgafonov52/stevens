import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

function stubStorage(saved: Record<string, string> = {}) {
  const store = { ...saved };
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
  });
  return store;
}

describe("допы и заголовок X-Stevens-Features (15.2)", () => {
  it("по умолчанию включены все допы, в заголовок идут только d2, d3, d10", async () => {
    stubStorage();
    const module = await import("./features");
    expect(Object.values(module.features).every(Boolean)).toBe(true);
    expect(module.featuresHeader()).toBe("d2,d3,d10");
  });

  it("доп можно выключить при сборке и в меню", async () => {
    vi.stubEnv("VITE_FEATURE_D2", "false");
    stubStorage({
      "stevens-contract:features": JSON.stringify({ d10: false }),
    });
    const module = await import("./features");
    expect(module.features.d2).toBe(false);
    expect(module.features.d10).toBe(false);
    expect(module.featuresHeader()).toBe("d3");
  });

  it("без допов для бэка заголовок пустой", async () => {
    stubStorage({
      "stevens-contract:features": JSON.stringify({
        d2: false,
        d3: false,
        d10: false,
      }),
    });
    expect((await import("./features")).featuresHeader()).toBe("");
  });
});
