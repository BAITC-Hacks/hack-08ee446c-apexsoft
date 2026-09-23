import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import {
  chat,
  emptyCart,
  filledCart,
  integrations,
  makeProposal,
  product,
} from "./fixtures";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
let calls: { path: string; options?: RequestInit }[];
let chatResponse: typeof chat;
let confirmStatus: number;
let chatFails: boolean;
let cancelFails: boolean;
let confirmWait: Promise<void> | null;
let chatWait: Promise<void> | null;
let cartStatus: number;
let attachmentName: string;
const scrollIntoView = vi.fn();

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  calls = [];
  chatResponse = structuredClone(chat);
  confirmStatus = 200;
  chatFails = false;
  cancelFails = false;
  confirmWait = null;
  chatWait = null;
  cartStatus = 200;
  attachmentName = "spec.pdf";
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoView,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      calls.push({ path, options });
      if (path === "/api/session")
        return json({
          session_id: "test-session",
          csrf_token: "test-csrf",
          cart: emptyCart,
          integrations,
        });
      if (path === "/api/chat" && chatWait) await chatWait;
      if (path === "/api/chat")
        return chatFails
          ? json(
              {
                error: {
                  code: "upstream_unavailable",
                  message: "Каталог временно недоступен.",
                },
              },
              503,
            )
          : json(chatResponse);
      if (path === "/api/cart/propose")
        return json({ proposal: makeProposal(), cart: emptyCart });
      if (path === "/api/cart/cancel")
        return cancelFails
          ? json(
              {
                error: {
                  code: "upstream_unavailable",
                  message: "Не удалось отменить предложение.",
                },
              },
              503,
            )
          : json({ cart: emptyCart });
      if (path === "/api/cart/confirm" && confirmWait) await confirmWait;
      if (path === "/api/cart/confirm")
        return confirmStatus === 409
          ? json(
              {
                error: {
                  code: "stock_changed",
                  message: "Остаток изменился. Проверьте предложение снова.",
                },
              },
              409,
            )
          : json({
              cart: filledCart,
              text: "Добавлено 2 в демонстрационную корзину.",
            });
      if (path === "/api/cart")
        return cartStatus === 200
          ? json(filledCart)
          : json(
              {
                error: {
                  code:
                    cartStatus === 403
                      ? "session_required"
                      : "upstream_unavailable",
                  message: "Не удалось обновить корзину.",
                },
              },
              cartStatus,
            );
      if (path === "/api/attachments")
        return json({
          attachment_id: "file-1",
          name: attachmentName,
          extracted_text: "Тестовый список",
          kind: "document",
          warnings: [],
        });
      throw new Error(`Unexpected request: ${path}`);
    }),
  );
});

async function search() {
  const user = userEvent.setup();
  render(<App />);
  const field = screen.getByRole("textbox", {
    name: "Ваш запрос консультанту",
  });
  await user.type(field, "Тестовый кабель");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Отправить сообщение" }));
  await screen.findByText("Найден тестовый товар.");
  return user;
}
async function propose() {
  const user = await search();
  await user.clear(screen.getByRole("spinbutton", { name: "Количество" }));
  await user.type(screen.getByRole("spinbutton", { name: "Количество" }), "2");
  await user.click(
    screen.getByRole("button", { name: "Проверить и добавить" }),
  );
  await screen.findByRole("button", { name: "Да, добавить 2" });
  return user;
}

describe("chat scrolling and focus", () => {
  it.each([false, true])(
    "keeps the composer in view during sending and after a reply (failure: %s)",
    async (fails) => {
      chatFails = fails;
      let finish!: () => void;
      chatWait = new Promise((resolve) => {
        finish = resolve;
      });
      const user = userEvent.setup();
      render(<App />);
      const field = screen.getByRole("textbox", {
        name: "Ваш запрос консультанту",
      });
      await user.type(field, "Проверить кабель");
      const send = screen.getByRole("button", { name: "Отправить сообщение" });
      await waitFor(() => expect(send).toBeEnabled());
      expect(scrollIntoView).not.toHaveBeenCalled();
      await user.click(send);
      await screen.findByText("Проверяю каталог и готовлю ответ…");
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      const target = scrollIntoView.mock.contexts[0] as HTMLElement;
      // The end anchor must include the composer and its error area, not stop
      // above them and leave the next action below the viewport.
      expect(
        field.compareDocumentPosition(target) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(scrollIntoView).toHaveBeenLastCalledWith({
        behavior: "auto",
        block: "end",
      });
      const focus = vi.spyOn(field, "focus");
      finish();
      await screen.findByText(
        fails ? "Каталог временно недоступен." : "Найден тестовый товар.",
      );
      await waitFor(() => expect(field).toHaveFocus());
      expect(field).toBeEnabled();
      expect(field).toHaveValue(fails ? "Проверить кабель" : "");
      expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
      expect(scrollIntoView).toHaveBeenCalledTimes(2);
      expect(scrollIntoView.mock.contexts[1]).toBe(target);
      focus.mockRestore();
    },
  );

  it("does not pull readers to the bottom when editing or refreshing the cart", async () => {
    const user = await search();
    scrollIntoView.mockClear();
    await user.type(
      screen.getByRole("textbox", { name: "Ваш запрос консультанту" }),
      "Следующий вопрос",
    );
    const refresh = within(
      screen.getByRole("complementary", { name: "Ваш подбор" }),
    ).getByRole("button", { name: "Обновить корзину" });
    await user.click(refresh);
    await screen.findByRole("heading", { name: "Корзина 2" });
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(refresh).toHaveFocus();
  });
});

describe("recoverable response errors", () => {
  it("preserves the conversation and draft when a successful chat response is malformed", async () => {
    const user = await search();
    chatResponse.products = null as unknown as typeof chat.products;
    const field = screen.getByRole("textbox", {
      name: "Ваш запрос консультанту",
    });
    await user.type(field, "Следующий вопрос");
    await user.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await screen.findByRole("alert");
    expect(screen.getByText("Найден тестовый товар.")).toBeInTheDocument();
    expect(field).toHaveValue("Следующий вопрос");
    expect(field).toBeEnabled();
    expect(field).toHaveFocus();
  });

  it.each([503, 403])(
    "shows a cart failure and recovery inside the open mobile dialog (%s)",
    async (status) => {
      Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
        configurable: true,
        value: function (this: HTMLDialogElement) {
          this.open = true;
        },
      });
      const user = userEvent.setup();
      render(<App />);
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Прикрепить файл" }),
        ).toBeEnabled(),
      );
      await user.click(
        screen.getByRole("button", { name: "Открыть корзину, товаров: 0" }),
      );
      const dialog = within(screen.getByRole("dialog"));
      cartStatus = status;
      await user.click(
        dialog.getByRole("button", { name: "Обновить корзину" }),
      );
      expect(await dialog.findByRole("alert")).toHaveTextContent(
        "Не удалось обновить корзину.",
      );
      cartStatus = 200;
      if (status === 403) {
        await user.click(
          dialog.getByRole("button", { name: "Подключиться повторно" }),
        );
        await waitFor(() =>
          expect(
            dialog.getByRole("button", { name: "Обновить корзину" }),
          ).toBeEnabled(),
        );
        expect(
          calls.filter((call) => call.path === "/api/session"),
        ).toHaveLength(2);
      }
      await user.click(
        dialog.getByRole("button", { name: "Обновить корзину" }),
      );
      await dialog.findByRole("heading", { name: "Тестовый кабель" });
      expect(dialog.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});

describe("explicit cart consent and honest data", () => {
  it("renders API and file HTML as text and omits executable source and certificate links", async () => {
    const payloads = {
      text: '<script>alert("reply")</script>',
      name: '<img src=x onerror="alert(1)">',
      description: '<svg onload="alert(2)">description</svg>',
      warning: '<b onclick="alert(3)">warning</b>',
      source: '<em onmouseover="alert(4)">source</em>',
      file: '<img src=x onerror="alert(5)">.pdf',
    };
    attachmentName = payloads.file;
    chatResponse = {
      ...chat,
      text: payloads.text,
      warnings: [payloads.warning],
      products: [
        {
          ...product,
          name: payloads.name,
          description: payloads.description,
          certificates: [
            { name: "Опасный сертификат", url: "javascript:alert(6)" },
          ],
        },
      ],
      sources: [
        { title: payloads.source, url: "https://ekt.kz/catalog/" },
        { title: "Опасный источник", url: "javascript:alert(7)" },
      ],
    };
    const user = userEvent.setup();
    const { container } = render(<App />);
    const input = screen.getByLabelText("Файл для консультанта");
    await waitFor(() => expect(input).toBeEnabled());
    await user.upload(
      input,
      new File(["synthetic document"], payloads.file, {
        type: "application/pdf",
      }),
    );
    await screen.findByText(payloads.file);
    await user.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await screen.findByText(payloads.text);
    await user.click(screen.getByText("Характеристики и документы"));
    for (const text of Object.values(payloads))
      expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: payloads.source })).toHaveAttribute(
      "href",
      "https://ekt.kz/catalog/",
    );
    expect(
      screen.queryByRole("link", { name: "Опасный источник" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Опасный сертификат" }),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector(
        'script, img, [onerror], [onload], [onclick], [onmouseover], a[href^="javascript:"]',
      ),
    ).toBeNull();
  });

  it("does not confirm during search or proposal; confirms only after the explicit button, with CSRF and cookie", async () => {
    const user = await propose();
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(0);
    expect(
      screen.queryByText("Добавлено 2 в демонстрационную корзину."),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Да, добавить 2" }));
    await screen.findByText("Добавлено 2 в демонстрационную корзину.");
    const confirms = calls.filter((call) => call.path === "/api/cart/confirm");
    expect(confirms).toHaveLength(1);
    expect(JSON.parse(String(confirms[0].options?.body))).toEqual({
      confirmation_id: "test-confirmation",
      confirmed: true,
    });
    for (const call of calls.filter(
      (call) => call.options?.method === "POST",
    )) {
      expect(call.options?.credentials).toBe("include");
      expect(call.options?.headers).toMatchObject({
        "X-CSRF-Token": "test-csrf",
      });
    }
    expect(
      screen.queryByRole("button", { name: "Да, добавить 2" }),
    ).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole("complementary", { name: "Ваш подбор" }),
      ).getByRole("heading", { name: "Корзина 2" }),
    ).toBeInTheDocument();
  });

  it("invalidates a stale proposal after 409 and requires a fresh check before another confirmation", async () => {
    confirmStatus = 409;
    const user = await propose();
    await user.click(screen.getByRole("button", { name: "Да, добавить 2" }));
    await screen.findByText("Остаток изменился. Проверьте предложение снова.");
    expect(
      screen.queryByRole("button", { name: "Да, добавить 2" }),
    ).not.toBeInTheDocument();
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(1);
    confirmStatus = 200;
    await user.click(screen.getByRole("button", { name: "Проверить заново" }));
    await screen.findByRole("button", { name: "Да, добавить 2" });
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(1);
  });

  it("never turns an unknown price or stock into available inventory", async () => {
    chatResponse.products = [{ ...product, price: null, stock: null }];
    await search();
    expect(screen.getByText("Цена не указана")).toBeInTheDocument();
    expect(screen.getByText("Наличие уточняется")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Проверить и добавить" }),
    ).toBeDisabled();
    expect(
      calls.filter((call) => call.path.startsWith("/api/cart/")),
    ).toHaveLength(0);
  });

  it("distinguishes an unknown warehouse quantity from a confirmed zero", async () => {
    chatResponse.products = [
      {
        ...product,
        warehouses: [
          { name: "Неизвестный склад", stock: null },
          { name: "Пустой склад", stock: 0 },
        ],
      },
    ];
    const user = await search();
    await user.click(screen.getByText("Характеристики и документы"));
    expect(screen.getByText("Неизвестный склад")).toHaveTextContent(
      "Наличие уточняется",
    );
    expect(screen.getByText("Пустой склад")).toHaveTextContent("Пустой склад0");
  });

  it("rejects quantities over the available stock before proposing", async () => {
    const user = await search();
    const input = screen.getByRole("spinbutton", { name: "Количество" });
    await user.clear(input);
    await user.type(input, "13");
    expect(
      screen.getByRole("button", { name: "Проверить и добавить" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Доступно 12, в корзине уже 0."),
    ).toBeInTheDocument();
  });

  it("preserves the query when upstream chat fails and does not invent a response", async () => {
    chatFails = true;
    const user = userEvent.setup();
    render(<App />);
    const field = screen.getByRole("textbox", {
      name: "Ваш запрос консультанту",
    });
    await user.type(field, "Важный запрос");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Отправить сообщение" }),
      ).toBeEnabled(),
    );
    await user.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await screen.findByText("Каталог временно недоступен.");
    expect(field).toHaveValue("Важный запрос");
    expect(
      screen.queryByText("Найден тестовый товар."),
    ).not.toBeInTheDocument();
  });

  it("uploads a document once and sends only its session attachment id with the message", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText("Файл для консультанта");
    await waitFor(() => expect(input).toBeEnabled());
    await user.upload(
      input,
      new File(["synthetic document"], "spec.pdf", { type: "application/pdf" }),
    );
    await screen.findByText("spec.pdf");
    await user.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await screen.findByText("Найден тестовый товар.");
    const upload = calls.find((call) => call.path === "/api/attachments");
    expect(upload?.options?.body).toBeInstanceOf(FormData);
    expect(upload?.options?.headers).not.toHaveProperty("Content-Type");
    const request = calls.find((call) => call.path === "/api/chat");
    expect(JSON.parse(String(request?.options?.body))).toMatchObject({
      attachment_ids: ["file-1"],
    });
  });

  it("cancels on the server and keeps the pending proposal when cancellation fails", async () => {
    const user = await propose();
    cancelFails = true;
    await user.click(screen.getByRole("button", { name: "Не добавлять" }));
    await screen.findByText("Не удалось отменить предложение.");
    expect(
      screen.getByRole("button", { name: "Да, добавить 2" }),
    ).toBeInTheDocument();
    cancelFails = false;
    await user.click(screen.getByRole("button", { name: "Не добавлять" }));
    await screen.findByText("Предложение отменено. Корзина не изменена.");
    expect(
      screen.queryByRole("button", { name: "Да, добавить 2" }),
    ).not.toBeInTheDocument();
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(0);
    expect(
      calls.filter((call) => call.path === "/api/cart/cancel"),
    ).toHaveLength(2);
  });

  it("locks a confirmation during a pending response, including double clicks", async () => {
    const user = await propose();
    let finish!: () => void;
    confirmWait = new Promise((resolve) => {
      finish = resolve;
    });
    await user.dblClick(screen.getByRole("button", { name: "Да, добавить 2" }));
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Да, добавить 2" }),
    ).toBeDisabled();
    finish();
    await screen.findByText("Добавлено 2 в демонстрационную корзину.");
    expect(
      calls.filter((call) => call.path === "/api/cart/confirm"),
    ).toHaveLength(1);
  });

  it("shows the session cart directly on /cart and refreshes it from the server", async () => {
    window.history.replaceState({}, "", "/cart");
    const user = userEvent.setup();
    render(<App />);
    const buttons = await screen.findAllByRole("button", {
      name: "Обновить корзину",
    });
    await waitFor(() => expect(buttons[0]).toBeEnabled());
    await user.click(buttons[0]);
    await screen.findByRole("heading", { name: "Тестовый кабель" });
    expect(
      within(screen.getByRole("main")).getByText("Демонстрационная корзина"),
    ).toBeInTheDocument();
  });
});
