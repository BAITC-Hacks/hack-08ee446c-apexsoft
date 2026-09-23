export interface Product {
  id: string;
  article: string;
  name: string;
  description: string;
  category: string;
  price: number | null;
  currency: "KZT";
  stock: number | null;
  min_quantity: number;
  quantity_step: number;
  image_url: string | null;
  product_url: string;
  specifications: { name: string; value: string }[];
  certificates: { name: string; url: string }[];
  warehouses: { name: string; stock: number | null }[];
  warnings: string[];
  source: "live" | "snapshot";
  checked_at: string;
  analogue_reason: string | null;
}
export interface Cart {
  mode: "demo";
  items: { product: Product; quantity: number; line_total: number }[];
  total: number;
  currency: "KZT";
  count: number;
  version: number;
  url: string;
  notice: string;
}
export interface Proposal {
  confirmation_id: string;
  operation: "add";
  product: Product;
  quantity: number;
  existing_quantity: number;
  resulting_quantity: number;
  expires_at: string;
}
export interface Integrations {
  catalog: "live" | "snapshot" | "unavailable";
  ai: "openai" | "fallback";
  cart: "demo";
  indexed_products: number;
  index_complete: boolean;
  notice: string;
}
export interface Session {
  session_id: string;
  csrf_token: string;
  cart: Cart;
  integrations: Integrations;
}
export interface ChatResponse {
  message_id: string;
  text: string;
  products: Product[];
  proposal: Proposal | null;
  cart: Cart;
  sources: { title: string; url: string }[];
  warnings: string[];
  suggestions: string[];
  integrations: Integrations;
}
export interface Attachment {
  attachment_id: string;
  name: string;
  extracted_text: string;
  kind: "document" | "image";
  warnings: string[];
}
export interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  files?: string[];
  response?: ChatResponse;
}
