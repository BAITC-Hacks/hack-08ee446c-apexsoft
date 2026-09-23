import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { CHAT_STORAGE_KEY, saveChat } from "../chatStorage";
import { chat, emptyCart, filledCart, integrations, makeProposal } from "./fixtures";

const json = (value: unknown) => new Response(JSON.stringify(value));
let serverCart = emptyCart;
let requests: string[];
beforeEach(() => {
  window.history.replaceState({}, "", "/#chat");
  serverCart = emptyCart; requests = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    requests.push(path);
    if (path === "/api/session") return json({session_id:"session",csrf_token:"csrf",cart:serverCart,integrations});
    if (path === "/api/chat") return json(chat);
    if (path === "/api/chat/reset") return json({cart:serverCart});
    throw new Error(path);
  }));
});
const field = () => screen.getByRole("textbox", {name:"Ваш запрос консультанту"});
const ready = () => waitFor(() => expect(field()).toBeEnabled());

it("restores messages, product cards, draft and URL fragment after a page remount without resending", async () => {
  const user = userEvent.setup(); const first = render(<App />); await ready();
  await user.type(field(), "Найди кабель");
  await user.click(screen.getByRole("button", {name:"Отправить сообщение"}));
  await screen.findByText(chat.text);
  await user.type(field(), "Ещё нужно 3 метра");
  first.unmount(); serverCart = filledCart;
  render(<App />); await ready();
  expect(field()).toHaveValue("Ещё нужно 3 метра");
  expect(screen.getByText("Найди кабель")).toBeVisible();
  expect(screen.getByText(chat.text)).toBeVisible();
  expect(screen.getAllByRole("heading", {name:"Тестовый кабель"}).length).toBeGreaterThan(0);
  expect(requests.filter(p => p === "/api/chat")).toHaveLength(1);
  expect(screen.getByRole("link", {name:/Моя корзина\s*2/})).toBeInTheDocument();
  expect(window.location.hash).toBe("#chat");
});

it("keeps New request cleared after another reload and retains the server cart", async () => {
  const user = userEvent.setup(); const first = render(<App />); await ready();
  await user.type(field(), "Черновик");
  await user.click(screen.getByRole("button", {name:"Новый запрос"}));
  await waitFor(() => expect(field()).toHaveValue(""));
  first.unmount(); render(<App />); await ready();
  expect(field()).toHaveValue("");
  expect(screen.queryByText(chat.text)).not.toBeInTheDocument();
});

it("never restores or sends cached confirmation capabilities", async () => {
  const proposal = makeProposal();
  saveChat({draft:"",messages:[{id:"saved",role:"assistant",text:chat.text,response:{...chat,proposal}}],sessionTag:null,pendingProposal:true,pendingFiles:false,attempt:null});
  expect(sessionStorage.getItem(CHAT_STORAGE_KEY)).not.toContain(proposal.confirmation_id);
  render(<App />); await ready();
  expect(screen.getByText(chat.text)).toBeVisible();
  expect(screen.queryByRole("button", {name:/Да, добавить/})).not.toBeInTheDocument();
  expect(requests).toEqual(["/api/session"]);
});

it("ignores corrupt saved state and continues when storage is unavailable", async () => {
  sessionStorage.setItem(CHAT_STORAGE_KEY, "{bad json");
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage blocked"); });
  const user = userEvent.setup(); render(<App />); await ready();
  expect(field()).toHaveValue("");
  expect(screen.getByText(/Браузер не разрешил сохранить чат/)).toBeVisible();
  await user.type(field(), "Найди кабель");
  await user.click(screen.getByRole("button", {name:"Отправить сообщение"}));
  await screen.findByText(chat.text);
});
