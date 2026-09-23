import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { chat, emptyCart, integrations, product } from "./fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const scrollIntoView = vi.fn();

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoView,
  });
});

describe("analogue search feedback", () => {
  it.each(["found", "empty", "error"] as const)(
    "reveals progress and the %s outcome without losing the draft or changing the cart",
    async (outcome) => {
      const paths: string[] = [];
      let finish!: () => void;
      const pending = new Promise<void>((resolve) => { finish = resolve; });
      const replacement = { ...product, id: "replacement", name: "Доступный аналог" };
      vi.stubGlobal("fetch", vi.fn(async (path: string) => {
        paths.push(path);
        if (path === "/api/session")
          return json({ session_id: "test-session", csrf_token: "test-csrf", cart: emptyCart, integrations });
        if (path === "/api/chat")
          return json({ ...chat, products: [{ ...product, stock: 0 }] });
        if (path === "/api/products/test-product/alternatives") {
          await pending;
          return outcome === "error"
            ? json({ error: { code: "upstream_unavailable", message: "Подбор аналогов временно недоступен." } }, 503)
            : json({ products: outcome === "found" ? [replacement] : [], warnings: [] });
        }
        throw new Error(`Unexpected request: ${path}`);
      }));
      const user = userEvent.setup();
      render(<App />);
      const field = screen.getByRole("textbox", { name: "Ваш запрос консультанту" });
      await user.type(field, "Есть провод?");
      const send = screen.getByRole("button", { name: "Отправить сообщение" });
      await waitFor(() => expect(send).toBeEnabled());
      await user.click(send);
      const choose = await screen.findByRole("button", { name: "Подобрать аналог" });
      await waitFor(() => expect(field).toBeEnabled());
      await user.type(field, "Неотправленный вопрос");
      scrollIntoView.mockClear();

      await user.click(choose);
      await screen.findByText("Подбираю доступные аналоги…");
      expect(choose).toBeDisabled();
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      const anchor = scrollIntoView.mock.contexts[0] as HTMLElement;
      expect(field.compareDocumentPosition(anchor) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      finish();

      await screen.findByText(outcome === "found"
        ? "Альтернативы для «Тестовый кабель». Сравните характеристики перед выбором."
        : outcome === "empty"
          ? "Подходящие доступные аналоги пока не найдены. Уточните параметры или обратитесь к менеджеру."
          : "Подбор аналогов временно недоступен.");
      if (outcome === "found") await screen.findByRole("heading", { name: "Доступный аналог" });
      await waitFor(() => expect(field).toHaveFocus());
      expect(field).toHaveValue("Неотправленный вопрос");
      expect(field).toBeEnabled();
      expect(choose).toBeEnabled();
      expect(scrollIntoView).toHaveBeenCalledTimes(2);
      expect(scrollIntoView.mock.contexts[1]).toBe(anchor);
      expect(scrollIntoView).toHaveBeenLastCalledWith({ behavior: "auto", block: "end" });
      expect(paths.filter((path) => path.includes("/alternatives"))).toHaveLength(1);
      expect(paths.some((path) => path.startsWith("/api/cart"))).toBe(false);
      expect(within(screen.getByRole("complementary", { name: "Ваш подбор" }))
        .getByText("Здесь будет ваш подбор")).toBeInTheDocument();
    },
  );
});
