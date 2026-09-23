import type { ChatEntry } from "./types";
import { responseChecks } from "./responseValidation";
import { containsPaymentData, PAYMENT_REDACTED } from "./privacy";

export const CHAT_STORAGE_KEY = "ekt.chat.v1";
export interface SavedChat {
  draft: string;
  messages: ChatEntry[];
  sessionTag: string | null;
  pendingProposal: boolean;
  pendingFiles: boolean;
  attempt: { payload: string; id: string } | null;
}
const empty = (): SavedChat => ({ draft: "", messages: [], sessionTag: null,
  pendingProposal: false, pendingFiles: false, attempt: null });

function withoutPaymentData(value: SavedChat): SavedChat {
  return { ...value,
    draft: containsPaymentData(value.draft) ? "" : value.draft,
    messages: value.messages.map(row =>
      containsPaymentData(row.text) || row.files?.some(containsPaymentData)
        || (row.response && containsPaymentData(row.response.text))
        ? { id: row.id, role: row.role, text: PAYMENT_REDACTED } : row),
    attempt: value.attempt && containsPaymentData(value.attempt.payload) ? null : value.attempt,
  };
}

function entry(value: unknown): value is ChatEntry {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return typeof row.id === "string" && typeof row.text === "string"
    && (row.role === "user" || row.role === "assistant")
    && (row.files === undefined || Array.isArray(row.files) && row.files.every(x => typeof x === "string"))
    && (row.response === undefined || responseChecks.chat(row.response));
}

export function loadChat(): SavedChat {
  try {
    const raw = sessionStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw || raw.length > 2_000_000) return empty();
    const data = JSON.parse(raw);
    if (data.version !== 1 || typeof data.draft !== "string" || !Array.isArray(data.messages)
      || !data.messages.every(entry)) return empty();
    const restored: SavedChat = { draft: data.draft.slice(0, 3000), messages: data.messages.slice(-100),
      sessionTag: typeof data.sessionTag === "string" ? data.sessionTag : null,
      pendingProposal: data.pendingProposal === true, pendingFiles: data.pendingFiles === true,
      attempt: data.attempt && typeof data.attempt.payload === "string" && typeof data.attempt.id === "string"
        ? { payload: data.attempt.payload, id: data.attempt.id } : null };
    const safe = withoutPaymentData(restored);
    if (JSON.stringify(safe) !== JSON.stringify(restored)) {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
      saveChat(safe);
    }
    return safe;
  } catch { return empty(); }
}

export function saveChat(value: SavedChat): boolean {
  try {
    const safe = withoutPaymentData(value);
    if (JSON.stringify(safe) !== JSON.stringify(value)) sessionStorage.removeItem(CHAT_STORAGE_KEY);
    // Cache display data only. Cart state is refreshed from the server; saved
    // messages must never restore a confirmation capability or upload content.
    const messages = safe.messages.slice(-100).map(row => ({ ...row,
      ...(row.response ? { response: { ...row.response, proposal: null } } : {}) }));
    let encoded = JSON.stringify({ ...safe, messages, version: 1 });
    while (encoded.length > 2_000_000 && messages.length > 2) {
      messages.splice(0, 2);
      encoded = JSON.stringify({ ...safe, messages, version: 1 });
    }
    if (encoded.length > 2_000_000) return false;
    sessionStorage.setItem(CHAT_STORAGE_KEY, encoded);
    return true;
  } catch { return false; }
}

export async function sessionTag(id: string): Promise<string | null> {
  if (!crypto.subtle) return null;
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(id));
  return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
}
