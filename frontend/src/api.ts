import type {
  Attachment,
  Cart,
  ChatResponse,
  Product,
  Proposal,
  Session,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(message: string, status = 0, code = "network") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

let csrfToken = "";
let sessionRequest: Promise<Session> | null = null;

async function request<T>(
  path: string,
  body?: Record<string, unknown> | FormData,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60_000);
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body) headers["X-CSRF-Token"] = csrfToken;
    if (body && !(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      credentials: "include",
      headers,
      body:
        body instanceof FormData
          ? body
          : body
            ? JSON.stringify(body)
            : undefined,
      signal: controller.signal,
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new ApiError(
        "Сервис пока недоступен. Попробуйте подключиться ещё раз.",
        response.status,
        "invalid_response",
      );
    }
    if (!response.ok)
      throw new ApiError(
        data.error?.message ||
          "Не удалось выполнить запрос. Попробуйте ещё раз.",
        response.status,
        data.error?.code || "request_failed",
      );
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError")
      throw new ApiError(
        "Ответ занял слишком много времени. Попробуйте ещё раз.",
        0,
        "timeout",
      );
    throw new ApiError(
      "Нет соединения с консультантом. Проверьте подключение и повторите запрос.",
    );
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  session: () => {
    // React StrictMode and concurrent consumers share the same initialization.
    if (!sessionRequest)
      sessionRequest = request<Session>("/api/session")
        .then((data) => {
          csrfToken = data.csrf_token;
          return data;
        })
        .finally(() => {
          sessionRequest = null;
        });
    return sessionRequest;
  },
  chat: (message: string, attachment_ids: string[]) =>
    request<ChatResponse>("/api/chat", { message, attachment_ids }),
  propose: (product_id: string, quantity: number) =>
    request<{ proposal: Proposal; cart: Cart }>("/api/cart/propose", {
      product_id,
      quantity,
    }),
  confirm: (confirmation_id: string) =>
    request<{ cart: Cart; text: string }>("/api/cart/confirm", {
      confirmation_id,
      confirmed: true,
    }),
  cancel: (confirmation_id: string) =>
    request<{ cart: Cart }>("/api/cart/cancel", { confirmation_id }),
  cart: () => request<Cart>("/api/cart"),
  product: (id: string) =>
    request<Product>(`/api/products/${encodeURIComponent(id)}`),
  alternatives: (id: string) =>
    request<{ products: Product[]; warnings: string[] }>(
      `/api/products/${encodeURIComponent(id)}/alternatives`,
    ),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Attachment>("/api/attachments", body);
  },
};

export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Не удалось выполнить действие. Попробуйте ещё раз.";
}

export function safeUrl(
  value: string | null | undefined,
  allowLocal = false,
): string | undefined {
  if (!value || /[\u0000-\u001f\u007f]/.test(value)) return undefined;
  if (allowLocal && /^\/(?!\/)[^\\]*$/.test(value)) return value;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export const money = (value: number | null) =>
  value === null || !Number.isFinite(value)
    ? "Цена не указана"
    : `${new Intl.NumberFormat("ru-KZ", { maximumFractionDigits: 2 }).format(value)} ₸`;
export const number = (value: number) =>
  new Intl.NumberFormat("ru-KZ", { maximumFractionDigits: 3 }).format(value);

export function quantityError(
  product: Product,
  quantity: number,
  existing = 0,
): string | null {
  if (!Number.isFinite(quantity) || quantity <= 0)
    return "Укажите положительное количество.";
  if (product.stock === null) return "Доступный остаток пока неизвестен.";
  if (product.price === null) return "Цена пока неизвестна.";
  if (quantity < product.min_quantity)
    return `Минимальная партия — ${number(product.min_quantity)}.`;
  const step = product.quantity_step > 0 ? product.quantity_step : 1;
  if (Math.abs(quantity / step - Math.round(quantity / step)) > 0.000001)
    return `Количество должно быть кратно ${number(step)}.`;
  if (quantity + existing > product.stock)
    return `Доступно ${number(product.stock)}, в корзине уже ${number(existing)}.`;
  return null;
}
