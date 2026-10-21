import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("API mode selection", () => {
  it.each(["real", "", "misspelled-real"])(
    "does not silently use demonstration responses for mode %j",
    async (mode) => {
      vi.stubEnv("VITE_API_MODE", mode);
      vi.resetModules();
      expect((await import("./features")).apiMode).toBe("real");
    },
  );

  it("uses mocks only when explicitly requested", async () => {
    vi.stubEnv("VITE_API_MODE", "mock");
    vi.resetModules();
    expect((await import("./features")).apiMode).toBe("mock");
  });
});
