import { expect, it } from "vitest";
import { CHAT_STORAGE_KEY, loadChat, saveChat, type SavedChat } from "../chatStorage";
import { containsPaymentData, PAYMENT_REDACTED } from "../privacy";

const sensitive = "Моя карта 4242 4242 4242 4242, CVV: 123";
const initial = (): SavedChat => ({ draft: "", messages: [], sessionTag: null,
  pendingProposal: false, pendingFiles: false, attempt: null });

it.each(["4242-4242-4242-4242", "4242424242424242", "3782 822463 10005", "4222222222222",
  "4000000000000000006", "Карта 4242 4242 4242 4242 12/30", "4242 4242 4242 4242 123",
  "CVV: 123", "CVC2=1234", "код безопасности 123", "Қауіпсіздік коды: 123",
  "Карта, артикул: 4242424242424242"])("detects synthetic payment data: %s", value => {
  expect(containsPaymentData(value)).toBe(true);
});

it.each(["Артикул: 4242424242424242", "SKU 4242424242424242", "EAN: 4222222222222",
  "Артикул ABC-4242424242424242", "GL 1004D 220 В 40 Вт", "150200334_",
  "LED ДВО ECO-PRISMA 36W 3240Lm 595x595x17 6500K IP20", "Можно оплатить картой?", "Что такое CVV?",
  "1234567890123456", "0000000000000000"])("preserves product data and ordinary questions: %s", value => {
  expect(containsPaymentData(value)).toBe(false);
});

it("does not persist payment data in drafts, messages, filenames or retry payloads", () => {
  const value: SavedChat = { ...initial(), draft: sensitive,
    messages: [{ id: "1", role: "user", text: sensitive },
      { id: "2", role: "user", text: "Файл", files: ["CVV 123.docx"] },
      { id: "3", role: "user", text: "Нужно 3 кабеля" }],
    attempt: { id: "test-request", payload: JSON.stringify([sensitive, []]) } };
  expect(saveChat(value)).toBe(true);
  const raw = sessionStorage.getItem(CHAT_STORAGE_KEY)!;
  expect(raw).not.toContain("4242");
  expect(raw).not.toContain("CVV 123");
  const result = loadChat();
  expect(result.draft).toBe("");
  expect(result.attempt).toBeNull();
  expect(result.messages[0].text).toBe(PAYMENT_REDACTED);
  expect(result.messages[1].files).toBeUndefined();
  expect(result.messages[2].text).toBe("Нужно 3 кабеля");
});

it("cleans sensitive data saved by older builds before restoring it", () => {
  sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify({ ...initial(), version: 1,
    draft: sensitive, messages: [{ id: "legacy", role: "user", text: sensitive }] }));
  expect(loadChat().draft).toBe("");
  expect(sessionStorage.getItem(CHAT_STORAGE_KEY)).not.toContain("4242");
});
