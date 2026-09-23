import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import {
  chat,
  emptyCart,
  integrations,
  makeProposal,
  product,
} from "./fixtures";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("request failures", () => {
  it.each([
    [
      "session token",
      () => api.session(),
      { session_id: "s", cart: emptyCart, integrations },
    ],
    ["chat products", () => api.chat("Тест", []), { ...chat, products: null }],
    [
      "nested product",
      () => api.chat("Тест", []),
      { ...chat, products: [{ ...product, warnings: null }] },
    ],
    [
      "proposal",
      () => api.propose("p", 1),
      { cart: emptyCart, proposal: { ...makeProposal(), quantity: "1" } },
    ],
    [
      "confirmation cart",
      () => api.confirm("confirmation"),
      { text: "Добавлено", cart: { ...emptyCart, items: null } },
    ],
    ["cancel cart", () => api.cancel("confirmation"), { cart: null }],
    [
      "cart item",
      () => api.cart(),
      { ...emptyCart, items: [{ product, quantity: 1, line_total: null }] },
    ],
    ["product price", () => api.product("p"), { ...product, price: "150" }],
    [
      "alternatives",
      () => api.alternatives("p"),
      { products: [], warnings: {} },
    ],
    [
      "attachment",
      () => api.upload(new File(["test"], "test.pdf")),
      { name: "test.pdf", kind: "document", extracted_text: "", warnings: [] },
    ],
  ])(
    "rejects malformed successful %s data before returning it",
    async (_name, call, data) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response(JSON.stringify(data), { status: 200 })),
      );
      await expect(call()).rejects.toMatchObject({
        code: "invalid_response",
        status: 200,
      });
    },
  );

  it("keeps the HTTP status when an error response has an invalid shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("null", { status: 403 })),
    );
    await expect(api.chat("Тест", [])).rejects.toMatchObject({
      code: "invalid_response",
      status: 403,
    });
  });

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
