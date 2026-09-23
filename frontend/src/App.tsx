import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowUp,
  ArrowUpRight,
  Cable,
  Check,
  ChevronRight,
  ClipboardList,
  FileText,
  Grid2X2,
  Headphones,
  LoaderCircle,
  MessageSquare,
  Paperclip,
  Plus,
  ShieldCheck,
  ShoppingCart,
  X,
  Zap,
} from "lucide-react";
import { api, ApiError, errorMessage, number, safeUrl } from "./api";
import {
  Brand,
  CartContent,
  Confirmation,
  ProductCard,
  Warnings,
} from "./components";
import type {
  Attachment,
  Cart,
  ChatEntry,
  ChatResponse,
  Integrations,
  Product,
  Proposal,
} from "./types";

const starters = [
  {
    icon: Cable,
    title: "Подобрать кабель",
    description: "По сечению, марке и вашей задаче",
    prompt: "Помогите подобрать кабель. Какие параметры нужно указать?",
  },
  {
    icon: Zap,
    title: "Найти аналог",
    description: "Сравнить важные характеристики",
    prompt: "Нужен аналог товара. Какие характеристики и артикул вам нужны?",
  },
  {
    icon: ClipboardList,
    title: "Собрать список",
    description: "Проверить товары для проекта",
    prompt: "Хочу собрать товары для проекта. Помогите проверить мой список.",
  },
];
type Busy =
  | "chat"
  | "propose"
  | "confirm"
  | "upload"
  | "cart"
  | "alternatives"
  | "cancel"
  | null;
const operationLabels: Record<Exclude<Busy, null>, string> = {
  chat: "Проверяю каталог и готовлю ответ…",
  propose: "Проверяю цену и доступное количество…",
  confirm: "Подтверждаю добавление…",
  upload: "Читаю вложение…",
  cart: "Обновляю корзину…",
  alternatives: "Подбираю доступные аналоги…",
  cancel: "Отменяю предложение…",
};

export default function App() {
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [busy, setBusy] = useState<Busy>(null);
  const [cart, setCart] = useState<Cart | null>(null);
  const [cartDialogOpen, setCartDialogOpen] = useState(false);
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [proposalStale, setProposalStale] = useState(false);
  const [now, setNow] = useState(Date.now());
  const composer = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cartDialog = useRef<HTMLDialogElement>(null);
  const conversationEnd = useRef<HTMLDivElement>(null);
  const followSubmittedChat = useRef(false);
  const requestLock = useRef(false);
  const isCartPage = window.location.pathname === "/cart";
  const expired =
    !!proposal &&
    (proposalStale ||
      !Number.isFinite(Date.parse(proposal.expires_at)) ||
      Date.parse(proposal.expires_at) <= now);
  const disabled = !!busy || connecting || !connected;

  const connect = useCallback(async () => {
    setConnecting(true);
    setNotice("");
    try {
      const data = await api.session();
      setCart(data.cart);
      setIntegrations(data.integrations);
      setConnected(true);
    } catch (error) {
      setNotice(errorMessage(error));
      setConnected(false);
    } finally {
      setConnecting(false);
    }
  }, []);
  useEffect(() => {
    void connect();
  }, [connect]);
  useEffect(() => {
    if (!proposal) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [proposal]);
  useLayoutEffect(() => {
    // Only a submitted chat should move the viewport, not unrelated cart work
    // or rerenders while the user is reading earlier messages.
    if (!followSubmittedChat.current) return;
    if (!busy) {
      followSubmittedChat.current = false;
      composer.current?.focus({ preventScroll: true });
    }
    conversationEnd.current?.scrollIntoView?.({
      behavior: "auto",
      block: "end",
    });
  }, [messages.length, busy, notice]);

  function start(text: string) {
    setDraft(text);
    setNotice("");
    composer.current?.focus();
  }
  function handleFailure(error: unknown) {
    setNotice(errorMessage(error));
    if (error instanceof ApiError && error.status === 403) {
      setConnected(false);
      setProposal(null);
      setAttachments([]);
    }
  }
  async function run(kind: Exclude<Busy, null>, task: () => Promise<void>) {
    if (requestLock.current || !connected) return;
    requestLock.current = true;
    if (kind === "chat") followSubmittedChat.current = true;
    setBusy(kind);
    setNotice("");
    try {
      await task();
    } catch (error) {
      handleFailure(error);
    } finally {
      requestLock.current = false;
      setBusy(null);
    }
  }
  function applyChat(
    response: ChatResponse,
    userText?: string,
    files?: string[],
  ) {
    const entries: ChatEntry[] = [];
    if (userText !== undefined)
      entries.push({
        id: crypto.randomUUID(),
        role: "user",
        text: userText,
        files,
      });
    entries.push({
      id: response.message_id,
      role: "assistant",
      text: response.text,
      response,
    });
    setMessages((current) => [...current, ...entries]);
    setCart(response.cart);
    setIntegrations(response.integrations);
    setProposal(response.proposal);
    setProposalStale(false);
    setNow(Date.now());
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if ((!draft.trim() && !attachments.length) || disabled) return;
    const text = draft.trim();
    const selected = [...attachments];
    if (proposal) setProposalStale(true);
    void run("chat", async () => {
      const response = await api.chat(
        text || "Проверьте товары из приложенного файла.",
        selected.map((file) => file.attachment_id),
      );
      applyChat(
        response,
        text || "Проверьте приложенный список.",
        selected.map((file) => file.name),
      );
      setDraft("");
      setAttachments([]);
    });
  }
  function propose(product: Product, quantity: number) {
    void run("propose", async () => {
      const data = await api.propose(product.id, quantity);
      setProposal(data.proposal);
      setProposalStale(false);
      setNow(Date.now());
      setCart(data.cart);
    });
  }
  function confirm() {
    if (!proposal || expired) return;
    const id = proposal.confirmation_id;
    void run("confirm", async () => {
      try {
        const result = await api.confirm(id);
        setCart(result.cart);
        setProposal(null);
        setMessages((current) => [
          ...current,
          { id: crypto.randomUUID(), role: "assistant", text: result.text },
        ]);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409)
          setProposalStale(true);
        throw error;
      }
    });
  }
  function alternatives(product: Product) {
    void run("alternatives", async () => {
      const result = await api.alternatives(product.id);
      if (!cart || !integrations) return;
      applyChat({
        message_id: crypto.randomUUID(),
        text: result.products.length
          ? `Альтернативы для «${product.name}». Сравните характеристики перед выбором.`
          : "Подходящие доступные аналоги пока не найдены. Уточните параметры или обратитесь к менеджеру.",
        products: result.products,
        proposal: null,
        cart,
        sources: [],
        warnings: result.warnings,
        suggestions: [],
        integrations,
      });
    });
  }
  function refreshCart() {
    void run("cart", async () => {
      setCart(await api.cart());
    });
  }
  function upload(file: File | undefined) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      setNotice("Файл слишком большой. Максимальный размер — 8 МБ.");
      return;
    }
    if (/\.doc$/i.test(file.name)) {
      setNotice(
        "Сохраните документ Word в формате .docx и прикрепите его снова.",
      );
      return;
    }
    if (!/\.(jpe?g|png|pdf|docx|xlsx|xls)$/i.test(file.name)) {
      setNotice("Поддерживаются JPEG, PNG, PDF, DOCX, XLSX и XLS.");
      return;
    }
    if (attachments.length >= 4) {
      setNotice(
        "Можно отправить до 4 вложений за один запрос. Сначала отправьте текущие файлы.",
      );
      return;
    }
    void run("upload", async () => {
      const data = await api.upload(file);
      setAttachments((current) => [...current, data]);
    });
  }
  function cancelProposal(resetInput = false) {
    if (!proposal) return;
    void run("cancel", async () => {
      const result = await api.cancel(proposal.confirmation_id);
      setCart(result.cart);
      setProposal(null);
      setNotice("Предложение отменено. Корзина не изменена.");
      if (resetInput) {
        setDraft("");
        setAttachments([]);
        composer.current?.focus();
      }
    });
  }
  function beginNewQuery() {
    if (busy) return;
    if (proposal) {
      cancelProposal(true);
      return;
    }
    // A new input is not a new server session. Never hide cart or pretend context was reset.
    start("");
    setAttachments([]);
    setProposal(null);
  }
  const connectionLabel = connecting
    ? "Подключение…"
    : !connected
      ? "Нет подключения"
      : integrations?.catalog === "live"
        ? "Каталог подключён"
        : integrations?.catalog === "snapshot"
          ? "Демонстрационные данные"
          : "Каталог недоступен";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Навигация">
        <a
          className="brand-link"
          href="https://ekt.kz/"
          target="_blank"
          rel="noreferrer"
        >
          <Brand />
        </a>
        <div className="workspace-label">ПОМОЩНИК В ЗАКУПКАХ</div>
        <nav>
          <a
            className={`nav-item ${!isCartPage ? "selected" : ""}`}
            href="/"
            aria-current={!isCartPage ? "page" : undefined}
          >
            <MessageSquare size={19} />
            Консультант{!isCartPage && <span className="nav-dot" />}
          </a>
          <a
            className="nav-item"
            href="https://ekt.kz/catalog/"
            target="_blank"
            rel="noreferrer"
          >
            <Grid2X2 size={19} />
            Каталог товаров
            <ArrowUpRight size={15} />
          </a>
          <a
            className={`nav-item ${isCartPage ? "selected" : ""}`}
            href="/cart"
            aria-current={isCartPage ? "page" : undefined}
          >
            <ShoppingCart size={19} />
            Моя корзина
            <span className="nav-cart-count">{cart?.count ?? 0}</span>
          </a>
        </nav>
        {!isCartPage && (
          <button
            className="new-chat"
            disabled={!!busy}
            onClick={beginNewQuery}
          >
            <Plus size={18} />
            Новый запрос
          </button>
        )}
        <div className="sidebar-bottom">
          <div className="advisor-note">
            <ShieldCheck size={22} />
            <p>
              Сначала проверяем.
              <br />
              <strong>Потом покупаем.</strong>
            </p>
          </div>
          <a
            className="support-link"
            href="https://ekt.kz/about/contacts/"
            target="_blank"
            rel="noreferrer"
          >
            <Headphones size={17} />
            Связаться с менеджером
            <ArrowUpRight size={14} />
          </a>
          <span className="sidebar-footer">Электротехника для ваших задач</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <a href="/" className="mobile-brand">
            <Brand compact />
          </a>
          <div className="page-heading">
            <span>ЕКТ / Помощник</span>
            <h1>
              {isCartPage ? "Ваша корзина" : "Консультант по электротехнике"}
            </h1>
          </div>
          <div className="topbar-actions">
            <span
              className={`connection-status ${connected && integrations?.catalog === "live" ? "online" : ""}`}
            >
              <span />
              {connectionLabel}
            </span>
            <button
              className="mobile-cart icon-button"
              aria-label={`Открыть корзину, товаров: ${cart?.count ?? 0}`}
              onClick={() => {
                cartDialog.current?.showModal();
                setCartDialogOpen(true);
              }}
            >
              <ShoppingCart size={22} />
              {!!cart?.count && <span>{cart.count}</span>}
            </button>
            <a
              className="store-link"
              href="https://ekt.kz/"
              target="_blank"
              rel="noreferrer"
            >
              В магазин
              <ArrowUpRight size={16} />
            </a>
          </div>
        </header>
        <div className="workflow" aria-label="Этапы подбора">
          <span
            className={`workflow-step ${!messages.length && !isCartPage ? "current" : ""}`}
          >
            <span>1</span>Ваш запрос
          </span>
          <ChevronRight size={14} />
          <span
            className={`workflow-step ${messages.length && !proposal && !isCartPage ? "current" : ""}`}
          >
            <span>2</span>Подбор товаров
          </span>
          <ChevronRight size={14} />
          <span
            className={`workflow-step ${proposal || isCartPage ? "current" : ""}`}
          >
            <span>3</span>Подтверждение
          </span>
        </div>
        {integrations &&
          (integrations.catalog !== "live" ||
            !integrations.index_complete ||
            integrations.ai === "fallback") && (
            <div className="integration-notice" role="status">
              {integrations.catalog === "snapshot" ? (
                <strong>
                  Демонстрационные данные — цены и наличие не актуальны.{" "}
                </strong>
              ) : integrations.catalog === "unavailable" ? (
                <strong>Каталог сейчас недоступен. </strong>
              ) : null}
              {!integrations.index_complete && (
                <>
                  Поиск по доступной выборке:{" "}
                  {number(integrations.indexed_products)} товаров.{" "}
                </>
              )}
              {integrations.ai === "fallback" && (
                <>Работает поиск по каталогу без ИИ-консультации. </>
              )}
              {integrations.notice}
            </div>
          )}
        {isCartPage ? (
          <main className="full-cart-page">
            <a className="text-link" href="/">
              ← Вернуться к консультанту
            </a>
            <h2>Ваш подбор</h2>
            <p className="cart-page-intro">
              Товары, которые вы подтвердили в этой сессии.
            </p>
            {notice && (
              <div className="inline-notice" role="alert">
                {notice}
              </div>
            )}
            {!connected && !connecting && (
              <button className="primary-button" onClick={() => void connect()}>
                Подключиться повторно
              </button>
            )}
            <CartContent
              cart={cart}
              loading={disabled}
              onRefresh={refreshCart}
              full
            />
          </main>
        ) : (
          <div className="work-area">
            <main className="chat-panel" id="chat">
              <div className="conversation">
                {!messages.length && (
                  <section className="welcome">
                    <div className="assistant-mark">
                      <Zap size={24} strokeWidth={1.8} />
                      <span>ЕКТ • КОНСУЛЬТАНТ</span>
                    </div>
                    <h2>
                      От вашей задачи
                      <br />к нужному товару<span>.</span>
                    </h2>
                    <p className="welcome-copy">
                      Опишите, что ищете, или укажите артикул.
                      <br className="desktop-break" /> Помогу разобраться в
                      характеристиках и собрать заказ.
                    </p>
                    <div className="starter-grid">
                      {starters.map(
                        ({ icon: Icon, title, description, prompt }) => (
                          <button
                            className="starter"
                            key={title}
                            disabled={!!busy}
                            onClick={() => start(prompt)}
                          >
                            <Icon size={24} strokeWidth={1.6} />
                            <strong>{title}</strong>
                            <span>{description}</span>
                            <ArrowUpRight className="starter-arrow" size={17} />
                          </button>
                        ),
                      )}
                    </div>
                    <button
                      className="attachment-hint attachment-trigger"
                      disabled={disabled}
                      onClick={() => fileInput.current?.click()}
                    >
                      <FileText size={21} />
                      <span>
                        <strong>Уже есть спецификация?</strong>
                        <span>
                          Приложите Excel, Word, PDF или фото списка — до 8 МБ.
                        </span>
                      </span>
                      <Paperclip size={17} />
                    </button>
                  </section>
                )}
                <div
                  className="message-list"
                  role="log"
                  aria-label="Переписка с консультантом"
                  aria-live="polite"
                >
                  {messages.map((entry) => (
                    <div className={`message ${entry.role}`} key={entry.id}>
                      <div className="message-byline">
                        {entry.role === "assistant" ? (
                          <>
                            <Zap size={14} />
                            ЕКТ КОНСУЛЬТАНТ
                          </>
                        ) : (
                          "ВЫ"
                        )}
                      </div>
                      <div className="message-text">{entry.text}</div>
                      {entry.files?.map((name, index) => (
                        <div className="message-file" key={index}>
                          <FileText size={14} />
                          {name}
                        </div>
                      ))}
                      {entry.response && (
                        <>
                          <Warnings messages={entry.response.warnings} />
                          <div className="product-list">
                            {entry.response.products.map((product) => (
                              <ProductCard
                                key={product.id}
                                product={product}
                                busy={disabled}
                                existing={
                                  cart?.items.find(
                                    (item) => item.product.id === product.id,
                                  )?.quantity ?? 0
                                }
                                onPropose={propose}
                                onAlternatives={alternatives}
                              />
                            ))}
                          </div>
                          {entry.response.sources.length > 0 && (
                            <div className="message-sources">
                              <span>Источники</span>
                              {entry.response.sources.map((source, index) =>
                                safeUrl(source.url) ? (
                                  <a
                                    key={index}
                                    href={safeUrl(source.url)}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    {source.title}
                                    <ArrowUpRight size={13} />
                                  </a>
                                ) : null,
                              )}
                            </div>
                          )}
                          {entry.response.suggestions.length > 0 && (
                            <div className="suggestions">
                              {entry.response.suggestions.map(
                                (suggestion, index) => (
                                  <button
                                    disabled={disabled}
                                    key={index}
                                    onClick={() => start(suggestion)}
                                  >
                                    {suggestion}
                                    <ChevronRight size={13} />
                                  </button>
                                ),
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
                {proposal && (
                  <Confirmation
                    proposal={proposal}
                    expired={expired}
                    busy={disabled}
                    onConfirm={confirm}
                    onCancel={() => cancelProposal()}
                    onRefresh={() =>
                      propose(proposal.product, proposal.quantity)
                    }
                  />
                )}
                {busy && (
                  <div className="busy-indicator" role="status">
                    <LoaderCircle size={17} className="spin" />
                    {operationLabels[busy]}
                  </div>
                )}
              </div>
              <div className="composer-area">
                {notice && (
                  <div className="inline-notice" role="alert">
                    {notice}
                    {!connected && !connecting && (
                      <button
                        className="text-button"
                        onClick={() => void connect()}
                      >
                        Подключиться повторно
                      </button>
                    )}
                  </div>
                )}
                <div className="attachment-list">
                  {attachments.map((file) => (
                    <div className="attachment-chip" key={file.attachment_id}>
                      <FileText size={15} />
                      <span>{file.name}</span>
                      <Check size={14} />
                      <button
                        className="remove-file"
                        disabled={!!busy}
                        aria-label={`Убрать файл ${file.name}`}
                        onClick={() =>
                          setAttachments((current) =>
                            current.filter(
                              (item) =>
                                item.attachment_id !== file.attachment_id,
                            ),
                          )
                        }
                      >
                        <X size={14} />
                      </button>
                      <Warnings messages={file.warnings} />
                    </div>
                  ))}
                </div>
                <form className="composer" onSubmit={submit}>
                  <label className="sr-only" htmlFor="message">
                    Ваш запрос консультанту
                  </label>
                  <textarea
                    id="message"
                    ref={composer}
                    rows={2}
                    value={draft}
                    disabled={!!busy}
                    maxLength={3000}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="Например: нужен кабель для проводки в квартире…"
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        e.currentTarget.form?.requestSubmit();
                      }
                    }}
                  />
                  <div className="composer-tools">
                    <div className="attach-tools">
                      <button
                        className="attach-button"
                        type="button"
                        disabled={disabled}
                        aria-label="Прикрепить файл"
                        onClick={() => fileInput.current?.click()}
                      >
                        <Paperclip size={20} />
                      </button>
                      <span className="composer-tip">
                        Excel, Word, PDF, фото · до 8 МБ
                      </span>
                    </div>
                    <button
                      className="send-button"
                      type="submit"
                      disabled={
                        disabled || (!draft.trim() && !attachments.length)
                      }
                      aria-label="Отправить сообщение"
                    >
                      {busy === "chat" ? (
                        <LoaderCircle size={21} className="spin" />
                      ) : (
                        <ArrowUp size={21} />
                      )}
                    </button>
                  </div>
                </form>
                <input
                  ref={fileInput}
                  className="sr-only"
                  type="file"
                  aria-label="Файл для консультанта"
                  accept=".jpg,.jpeg,.png,.pdf,.docx,.xlsx,.xls,.doc"
                  disabled={disabled}
                  onChange={(e) => {
                    upload(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <p className="upload-privacy">
                  При включённом ИИ текст и вложения обрабатывает OpenAI. Не
                  прикладывайте платёжные данные и чужие персональные или
                  конфиденциальные сведения.
                </p>
                <p className="composer-note">
                  <ShieldCheck size={14} />
                  Товары попадут в демо-корзину только с вашего согласия.
                </p>
              </div>
              <div ref={conversationEnd} aria-hidden="true" />
            </main>
            <aside className="cart-panel" aria-label="Ваш подбор">
              <div className="panel-title">
                <div>
                  <span className="eyebrow">ВАШ ЗАКАЗ</span>
                  <h2>
                    Корзина{" "}
                    <span className="count-badge">{cart?.count ?? 0}</span>
                  </h2>
                </div>
                <ShoppingCart size={21} />
              </div>
              <CartContent
                cart={cart}
                loading={disabled}
                onRefresh={refreshCart}
              />
              <div className="cart-guide">
                <span className="eyebrow">КАК ЭТО РАБОТАЕТ</span>
                <p>
                  <Check size={16} />
                  Подбираем по характеристикам
                </p>
                <p>
                  <Check size={16} />
                  Проверяем доступное количество
                </p>
                <p>
                  <Check size={16} />
                  Ждём вашего подтверждения
                </p>
              </div>
              <div className="help-card">
                <span>Есть вопросы об условиях?</span>
                <button
                  disabled={!!busy}
                  onClick={() =>
                    start(
                      "Расскажите об условиях оплаты и доставки. Есть ли минимальная партия?",
                    )
                  }
                >
                  Оплата и доставка
                  <ArrowUpRight size={17} />
                </button>
              </div>
            </aside>
          </div>
        )}
      </div>
      <dialog
        className="cart-dialog"
        ref={cartDialog}
        onClose={() => setCartDialogOpen(false)}
      >
        <div className="dialog-heading">
          <h2>Ваша корзина</h2>
          <button
            className="icon-button"
            aria-label="Закрыть корзину"
            onClick={() => cartDialog.current?.close()}
          >
            <X size={22} />
          </button>
        </div>
        {cartDialogOpen && notice && (
          <div className="inline-notice" role="alert">
            {notice}
            {!connected && !connecting && (
              <button className="text-button" onClick={() => void connect()}>
                Подключиться повторно
              </button>
            )}
          </div>
        )}
        <CartContent cart={cart} loading={disabled} onRefresh={refreshCart} />
      </dialog>
    </div>
  );
}
