import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("request failures", () => {
  it("reports a timeout when the response body stalls after headers arrive", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, options: RequestInit) => ({
        ok: true,
        status: 200,
        json: () =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener(
              "abort",
              () => reject(new DOMException("Aborted", "AbortError")),
              { once: true },
            );
          }),
      })),
    );
    const result = api.chat("Тестовый запрос", []).catch((error) => error);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await result).toMatchObject({
      code: "timeout",
      message: "Ответ занял слишком много времени. Попробуйте ещё раз.",
    });
  });

  it("still identifies a non-JSON server response as unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () => new Response("<html>Bad gateway</html>", { status: 502 }),
      ),
    );
    await expect(api.chat("Тестовый запрос", [])).rejects.toMatchObject({
      code: "invalid_response",
      status: 502,
      message: "Сервис пока недоступен. Попробуйте подключиться ещё раз.",
    });
  });
});
