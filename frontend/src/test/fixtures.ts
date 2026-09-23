// Synthetic data used only by isolated UI tests; never imported by the application.
import type {
  Cart,
  ChatResponse,
  Integrations,
  Product,
  Proposal,
} from "../types";

export const product: Product = {
  id: "test-product",
  article: "TEST-001",
  name: "Тестовый кабель",
  description: "Синтетический товар для проверки интерфейса.",
  category: "Тест",
  price: 150,
  currency: "KZT",
  stock: 12,
  min_quantity: 1,
  quantity_step: 1,
  image_url: null,
  product_url: "https://ekt.kz/catalog/",
  specifications: [{ name: "Сечение", value: "3 × 2,5 мм²" }],
  certificates: [],
  warehouses: [{ name: "Тестовый склад", stock: 12 }],
  warnings: [],
  source: "snapshot",
  checked_at: "2026-09-23T08:00:00Z",
  analogue_reason: null,
};
export const integrations: Integrations = {
  catalog: "snapshot",
  ai: "fallback",
  cart: "demo",
  indexed_products: 1,
  index_complete: false,
  notice: "Тестовая выборка.",
};
export const emptyCart: Cart = {
  mode: "demo",
  items: [],
  total: 0,
  currency: "KZT",
  count: 0,
  version: 0,
  url: "/cart",
  notice: "Не меняет корзину ekt.kz.",
};
export const filledCart: Cart = {
  ...emptyCart,
  items: [{ product, quantity: 2, line_total: 300 }],
  total: 300,
  count: 2,
  version: 1,
};
export function makeProposal(): Proposal {
  return {
    confirmation_id: "test-confirmation",
    operation: "add",
    product,
    quantity: 2,
    existing_quantity: 0,
    resulting_quantity: 2,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
  };
}
export const chat: ChatResponse = {
  message_id: "test-message",
  text: "Найден тестовый товар.",
  products: [product],
  proposal: null,
  cart: emptyCart,
  sources: [{ title: "Каталог EKT", url: "https://ekt.kz/catalog/" }],
  warnings: [],
  suggestions: [],
  integrations,
};
