import type {
  Attachment,
  Cart,
  ChatResponse,
  Integrations,
  Product,
  Proposal,
  Session,
} from "./types";

export type ResponseCheck<T> = (value: unknown) => value is T;

function objectOf<T>(fields: {
  [K in keyof T]-?: ResponseCheck<T[K]>;
}): ResponseCheck<T> {
  return (value): value is T => {
    if (value === null || typeof value !== "object" || Array.isArray(value))
      return false;
    const record = value as Record<string, unknown>;
    return Object.keys(fields).every((key) =>
      fields[key as keyof T](record[key]),
    );
  };
}
function arrayOf<T>(check: ResponseCheck<T>): ResponseCheck<T[]> {
  return (value): value is T[] => Array.isArray(value) && value.every(check);
}
function nullable<T>(check: ResponseCheck<T>): ResponseCheck<T | null> {
  return (value): value is T | null => value === null || check(value);
}
function oneOf<T extends string>(...values: T[]): ResponseCheck<T> {
  return (value): value is T =>
    typeof value === "string" && values.includes(value as T);
}
const string: ResponseCheck<string> = (value): value is string =>
  typeof value === "string";
const identifier: ResponseCheck<string> = (value): value is string =>
  string(value) && value.trim().length > 0;
const boolean: ResponseCheck<boolean> = (value): value is boolean =>
  typeof value === "boolean";
const nonNegative: ResponseCheck<number> = (value): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;
const positive: ResponseCheck<number> = (value): value is number =>
  nonNegative(value) && value > 0;
const strings = arrayOf(string);

const product = objectOf<Product>({
  id: identifier,
  article: string,
  name: string,
  description: string,
  category: string,
  price: nullable(nonNegative),
  currency: oneOf("KZT"),
  stock: nullable(nonNegative),
  min_quantity: positive,
  quantity_step: positive,
  image_url: nullable(string),
  product_url: string,
  specifications: arrayOf(
    objectOf<{ name: string; value: string }>({ name: string, value: string }),
  ),
  certificates: arrayOf(
    objectOf<{ name: string; url: string }>({ name: string, url: string }),
  ),
  warehouses: arrayOf(
    objectOf<Product["warehouses"][number]>({
      name: string,
      stock: nullable(nonNegative),
    }),
  ),
  warnings: strings,
  source: oneOf("live", "snapshot"),
  checked_at: string,
  analogue_reason: nullable(string),
});
const cart = objectOf<Cart>({
  mode: oneOf("demo"),
  items: arrayOf(
    objectOf<Cart["items"][number]>({
      product,
      quantity: positive,
      line_total: nonNegative,
    }),
  ),
  total: nonNegative,
  currency: oneOf("KZT"),
  count: nonNegative,
  version: nonNegative,
  url: string,
  notice: string,
});
const proposal = objectOf<Proposal>({
  confirmation_id: identifier,
  operation: oneOf("add"),
  product,
  quantity: positive,
  existing_quantity: nonNegative,
  resulting_quantity: positive,
  expires_at: string,
});
const integrations = objectOf<Integrations>({
  catalog: oneOf("live", "snapshot", "unavailable"),
  ai: oneOf("openai", "fallback"),
  cart: oneOf("demo"),
  indexed_products: nonNegative,
  index_complete: boolean,
  notice: string,
});

// Check the API contract before data reaches React. Extra fields are allowed,
// but missing or malformed fields are not silently converted into usable data.
export const responseChecks = {
  session: objectOf<Session>({
    session_id: identifier,
    csrf_token: identifier,
    cart,
    integrations,
  }),
  chat: objectOf<ChatResponse>({
    message_id: identifier,
    text: string,
    products: arrayOf(product),
    proposal: nullable(proposal),
    cart,
    sources: arrayOf(
      objectOf<{ title: string; url: string }>({ title: string, url: string }),
    ),
    warnings: strings,
    suggestions: strings,
    integrations,
  }),
  propose: objectOf<{ proposal: Proposal; cart: Cart }>({ proposal, cart }),
  confirm: objectOf<{ cart: Cart; text: string }>({ cart, text: string }),
  cartResult: objectOf<{ cart: Cart }>({ cart }),
  removed: objectOf<{ removed: true }>({
    removed: (value): value is true => value === true,
  }),
  cart,
  product,
  alternatives: objectOf<{ products: Product[]; warnings: string[] }>({
    products: arrayOf(product),
    warnings: strings,
  }),
  attachment: objectOf<Attachment>({
    attachment_id: identifier,
    name: string,
    extracted_text: string,
    kind: oneOf("document", "image"),
    warnings: strings,
  }),
  failure: objectOf<{ error: { code: string; message: string } }>({
    error: objectOf({ code: string, message: string }),
  }),
};
