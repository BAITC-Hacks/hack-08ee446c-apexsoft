import { useId, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  FileCheck2,
  Package,
  RefreshCw,
  ShieldCheck,
  ShoppingCart,
  X,
} from "lucide-react";
import type { Cart, Product, Proposal } from "./types";
import { money, number, quantityError, safeUrl } from "./api";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "brand-compact" : ""}`}>
      <span className="brand-symbol" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <strong>ЕКТ</strong>
      <span className="brand-caption">ЭЛЕКТРОКОМПЛЕКТ</span>
    </div>
  );
}

export function EmptyCart() {
  return (
    <div className="empty-cart">
      <div className="empty-cart-icon">
        <ShoppingCart size={27} strokeWidth={1.4} />
      </div>
      <h3>Здесь будет ваш подбор</h3>
      <p>
        Найдём нужные товары, проверим количество и добавим их после вашего
        подтверждения.
      </p>
      <span className="small-rule" />
    </div>
  );
}

export function Warnings({ messages }: { messages: string[] }) {
  return messages.length ? (
    <div className="warnings">
      {messages.map((text, index) => (
        <p key={index}>
          <AlertTriangle size={16} />
          <span>{text}</span>
        </p>
      ))}
    </div>
  ) : null;
}

export function ProductCard({
  product,
  busy,
  existing,
  onPropose,
  onAlternatives,
}: {
  product: Product;
  busy: boolean;
  existing: number;
  onPropose: (product: Product, quantity: number) => void;
  onAlternatives: (product: Product) => void;
}) {
  const quantityId = useId();
  const [quantity, setQuantity] = useState(String(product.min_quantity || 1));
  const [imageFailed, setImageFailed] = useState(false);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const error = quantityError(product, Number(quantity), existing);
  const image = safeUrl(product.image_url);
  const url = safeUrl(product.product_url);
  const productUrl = url && !/^\/(?:catalog\/?)?$/.test(new URL(url).pathname) ? url : null;
  const description = product.description.trim();
  const longDescription = description.length > 320;
  const date = new Date(product.checked_at);
  const stock = product.stock;
  return (
    <article className="product-card">
      <div className="product-summary">
        <div className="product-image">
          {image && !imageFailed ? (
            <img
              src={image}
              alt={product.name}
              loading="lazy"
              onError={() => setImageFailed(true)}
            />
          ) : (
            <span className="product-image-placeholder">
              <Package size={29} strokeWidth={1.3} aria-hidden="true" />
              <span>{imageFailed ? "Фото не загрузилось" : "Нет фото"}</span>
            </span>
          )}
        </div>
        <div>
          <span className="article-label">
            АРТ. {product.article || product.id}
          </span>
          <h3>{product.name}</h3>
          <div className={`stock-label ${stock === 0 ? "no-stock" : ""}`}>
            {stock === null
              ? "Наличие уточняется"
              : stock > 0
                ? `В наличии: ${number(stock)}`
                : "Нет в наличии"}
          </div>
        </div>
      </div>
      <div className="product-description">
        <p>{description
          ? longDescription && !descriptionExpanded
            ? `${description.slice(0, 320).replace(/\s+\S*$/, "")}…`
            : description
          : "Описание в каталоге не указано."}</p>
        {longDescription && (
          <button className="text-link" type="button" aria-expanded={descriptionExpanded}
            onClick={() => setDescriptionExpanded(!descriptionExpanded)}>
            {descriptionExpanded ? "Свернуть описание" : "Читать описание полностью"}
          </button>
        )}
      </div>
      {productUrl ? (
        <a className="text-link" href={productUrl} target="_blank" rel="noreferrer">
          Открыть товар на ekt.kz <ArrowUpRight size={14} />
        </a>
      ) : <p className="product-link-missing">Ссылка на товар в каталоге не указана.</p>}
      {product.analogue_reason && (
        <p className="analogue-reason">
          <RefreshCw size={15} />
          <span>{product.analogue_reason}</span>
        </p>
      )}
      <Warnings messages={product.warnings} />
      <details className="product-details">
        <summary>Характеристики и документы</summary>
        {product.specifications.length ? (
          <dl>
            {product.specifications.map((spec, index) => (
              <div key={index}>
                <dt>{spec.name}</dt>
                <dd>{spec.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p>Характеристики в каталоге не указаны.</p>
        )}
        {product.warehouses.length > 0 && (
          <div className="warehouses">
            {product.warehouses.map((w, index) => (
              <p key={index}>
                {w.name}
                <strong>
                  {w.stock === null ? "Наличие уточняется" : number(w.stock)}
                </strong>
              </p>
            ))}
          </div>
        )}
        <div className="certificates">
          {product.certificates.some((c) => safeUrl(c.url)) ? (
            product.certificates.map((c, index) =>
              safeUrl(c.url) ? (
                <a
                  key={index}
                  href={safeUrl(c.url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <FileCheck2 size={15} />
                  {c.name}
                  <ArrowUpRight size={13} />
                </a>
              ) : null,
            )
          ) : (
            <p>Сертификат в каталоге не указан.</p>
          )}
        </div>
      </details>
      <div className="product-price-row">
        <strong>{money(product.price)}</strong>
        <span>
          Мин. {number(product.min_quantity)} · шаг{" "}
          {number(product.quantity_step)}
        </span>
      </div>
      {stock === 0 ? (
        <button
          className="secondary-button full-width"
          disabled={busy}
          onClick={() => onAlternatives(product)}
        >
          <RefreshCw size={16} />
          Подобрать аналог
        </button>
      ) : (
        <>
          <div className="product-actions">
            <label htmlFor={quantityId}>
              Количество
              <input
                id={quantityId}
                type="number"
                inputMode="decimal"
                min={product.min_quantity}
                step={product.quantity_step}
                value={quantity}
                disabled={busy}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <button
              className="primary-button"
              disabled={busy || !!error}
              onClick={() => onPropose(product, Number(quantity))}
            >
              Проверить и добавить
              <ShoppingCart size={16} />
            </button>
          </div>
          {error && <p className="quantity-help">{error}</p>}
        </>
      )}
      <div
        className={`source-label ${product.source === "snapshot" ? "snapshot" : ""}`}
      >
        {product.source === "snapshot"
          ? "Демонстрационные данные; не актуальная цена/наличие"
          : "Данные каталога EKT"}
        {!Number.isNaN(date.getTime()) && (
          <span>
            {" "}
            ·{" "}
            {date.toLocaleString("ru-KZ", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        )}
      </div>
    </article>
  );
}

export function Confirmation({
  proposal,
  expired,
  busy,
  onConfirm,
  onCancel,
  onRefresh,
}: {
  proposal: Proposal;
  expired: boolean;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onRefresh: () => void;
}) {
  return (
    <section className="confirmation" aria-label="Подтверждение добавления">
      <div className="confirmation-eyebrow">
        <ShieldCheck size={18} />
        НУЖНО ВАШЕ ПОДТВЕРЖДЕНИЕ
      </div>
      <h3>{proposal.product.name}</h3>
      <dl>
        <div>
          <dt>Добавить</dt>
          <dd>{number(proposal.quantity)}</dd>
        </div>
        <div>
          <dt>Будет в корзине</dt>
          <dd>{number(proposal.resulting_quantity)}</dd>
        </div>
        <div>
          <dt>Цена за единицу</dt>
          <dd>{money(proposal.product.price)}</dd>
        </div>
      </dl>
      <Warnings messages={proposal.product.warnings} />
      {proposal.product.source === "snapshot" && (
        <p className="quantity-help">
          Демонстрационные данные; не актуальная цена/наличие.
        </p>
      )}
      {expired ? (
        <>
          <p className="expired-notice">
            Предложение устарело. Проверим цену и остаток ещё раз.
          </p>
          <button
            className="primary-button"
            disabled={busy}
            onClick={onRefresh}
          >
            <RefreshCw size={16} />
            Проверить заново
          </button>
        </>
      ) : (
        <>
          <p className="confirmation-note">
            Изменится только демонстрационная корзина. Перед добавлением снова
            проверим цену и наличие.
          </p>
          <button
            className="confirm-button"
            disabled={busy}
            onClick={onConfirm}
          >
            <Check size={18} />
            Да, добавить {number(proposal.quantity)}
          </button>
        </>
      )}
      <button className="cancel-button" disabled={busy} onClick={onCancel}>
        Не добавлять
      </button>
    </section>
  );
}

export function CartContent({
  cart,
  loading,
  onRefresh,
  onRemove,
  full = false,
}: {
  cart: Cart | null;
  loading: boolean;
  onRefresh: () => void;
  onRemove: (product: Product) => void;
  full?: boolean;
}) {
  return (
    <>
      <div className="demo-badge">Демонстрационная корзина</div>
      {cart?.items.length ? (
        <div className={`cart-items ${full ? "cart-items-full" : ""}`}>
          {cart.items.map((item) => (
            <article className="cart-item" key={item.product.id}>
              <span className="article-label">АРТ. {item.product.article}</span>
              <h3>{item.product.name}</h3>
              <div>
                <span>
                  {number(item.quantity)} × {money(item.product.price)}
                </span>
                <strong>{money(item.line_total)}</strong>
              </div>
              {item.product.source === "snapshot" && (
                <span className="source-label snapshot">
                  Демонстрационные данные
                </span>
              )}
              <button
                className="refresh-cart"
                disabled={loading}
                onClick={() => onRemove(item.product)}
                aria-label={`Удалить ${item.product.name} из корзины`}
              >
                <X size={14} /> Удалить из корзины
              </button>
            </article>
          ))}
          <div className="cart-total">
            <span>Итого</span>
            <strong>{money(cart.total)}</strong>
          </div>
          {!full && (
            <a className="primary-button full-width" href="/cart">
              Открыть корзину
              <ArrowUpRight size={16} />
            </a>
          )}
        </div>
      ) : (
        <EmptyCart />
      )}
      <p className="cart-disclaimer">
        {cart?.notice || "Не оформляет заказ и не меняет корзину на ekt.kz."}
      </p>
      <button className="refresh-cart" onClick={onRefresh} disabled={loading}>
        <RefreshCw size={14} />
        Обновить корзину
      </button>
    </>
  );
}
