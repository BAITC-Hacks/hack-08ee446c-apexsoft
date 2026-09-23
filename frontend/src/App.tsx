import { useRef, useState, type FormEvent } from 'react';
import { ArrowUp, ArrowUpRight, Cable, Check, ChevronRight, ClipboardList, FileText, Grid2X2, Headphones, MessageSquare, Plus, ShieldCheck, ShoppingCart, X, Zap } from 'lucide-react';

const starters = [
  { icon: Cable, title: 'Подобрать кабель', description: 'По сечению, марке и вашей задаче', prompt: 'Помогите подобрать кабель. Какие параметры нужно указать?' },
  { icon: Zap, title: 'Найти аналог', description: 'Сравнить важные характеристики', prompt: 'Нужен аналог товара. Какие характеристики и артикул вам нужны?' },
  { icon: ClipboardList, title: 'Собрать список', description: 'Проверить товары для проекта', prompt: 'Хочу собрать товары для проекта. Помогите проверить мой список.' },
];

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? 'brand-compact' : ''}`}><span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span><strong>ЕКТ</strong><span className="brand-caption">ЭЛЕКТРОКОМПЛЕКТ</span></div>;
}

export function EmptyCart() {
  return <div className="empty-cart"><div className="empty-cart-icon"><ShoppingCart size={27} strokeWidth={1.4} /></div><h3>Здесь будет ваш подбор</h3><p>Найдём нужные товары, проверим количество и добавим их после вашего подтверждения.</p><span className="small-rule" /></div>;
}

export default function App() {
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState('');
  const composer = useRef<HTMLTextAreaElement>(null);
  const cartDialog = useRef<HTMLDialogElement>(null);
  function start(text: string) { setDraft(text); setNotice(''); composer.current?.focus(); }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) setNotice('Консультант готовится к работе. Ваш запрос остался в поле — отправьте его, когда подключение будет готово.');
  }
  return <div className="app-shell">
    <aside className="sidebar" aria-label="Навигация">
      <a className="brand-link" href="https://ekt.kz/" target="_blank" rel="noreferrer"><Brand /></a>
      <div className="workspace-label">ПОМОЩНИК В ЗАКУПКАХ</div>
      <nav><a className="nav-item selected" href="#chat" aria-current="page"><MessageSquare size={19} />Консультант<span className="nav-dot" /></a><a className="nav-item" href="https://ekt.kz/catalog/" target="_blank" rel="noreferrer"><Grid2X2 size={19} />Каталог товаров<ArrowUpRight size={15} /></a></nav>
      <button className="new-chat" onClick={() => start('')}><Plus size={18} />Новый запрос</button>
      <div className="sidebar-bottom"><div className="advisor-note"><ShieldCheck size={22} /><p>Сначала проверяем.<br /><strong>Потом покупаем.</strong></p></div><a className="support-link" href="https://ekt.kz/about/contacts/" target="_blank" rel="noreferrer"><Headphones size={17} />Связаться с менеджером<ArrowUpRight size={14} /></a><span className="sidebar-footer">Электротехника для ваших задач</span></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="mobile-brand"><Brand compact /></div><div className="page-heading"><span>ЕКТ / Помощник</span><h1>Консультант по электротехнике</h1></div><div className="topbar-actions"><span className="connection-status"><span />Подключение готовится</span><button className="mobile-cart icon-button" aria-label="Открыть корзину" onClick={() => cartDialog.current?.showModal()}><ShoppingCart size={22} /></button><a className="store-link" href="https://ekt.kz/" target="_blank" rel="noreferrer">В магазин<ArrowUpRight size={16} /></a></div></header>
      <div className="workflow" aria-label="Этапы подбора"><span className="workflow-step current"><span>1</span>Ваш запрос</span><ChevronRight size={14} /><span className="workflow-step"><span>2</span>Подбор товаров</span><ChevronRight size={14} /><span className="workflow-step"><span>3</span>Подтверждение</span></div>
      <div className="work-area">
        <main className="chat-panel" id="chat">
          <div className="conversation">
            <section className="welcome"><div className="assistant-mark"><Zap size={24} strokeWidth={1.8} /><span>ЕКТ • КОНСУЛЬТАНТ</span></div><h2>От вашей задачи<br />к нужному товару<span>.</span></h2><p className="welcome-copy">Опишите, что ищете, или укажите артикул.<br className="desktop-break" /> Помогу разобраться в характеристиках и собрать заказ.</p>
              <div className="starter-grid">{starters.map(({ icon: Icon, title, description, prompt }) => <button className="starter" key={title} onClick={() => start(prompt)}><Icon size={24} strokeWidth={1.6} /><strong>{title}</strong><span>{description}</span><ArrowUpRight className="starter-arrow" size={17} /></button>)}</div>
              <div className="attachment-hint"><FileText size={21} /><p><strong>Уже есть спецификация?</strong><span>Можно будет приложить Excel, Word, PDF или фото списка.</span></p></div>
            </section>
          </div>
          <div className="composer-area">{notice && <div className="inline-notice" role="status">{notice}</div>}<form className="composer" onSubmit={submit}><label className="sr-only" htmlFor="message">Ваш запрос консультанту</label><textarea id="message" ref={composer} rows={2} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Например: нужен кабель для проводки в квартире…" onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><div className="composer-tools"><span className="composer-tip">Артикул, название или задача</span><button className="send-button" type="submit" disabled={!draft.trim()} aria-label="Отправить сообщение"><ArrowUp size={21} /></button></div></form><p className="composer-note"><ShieldCheck size={14} />Товары попадут в корзину только с вашего согласия.</p></div>
        </main>
        <aside className="cart-panel" aria-label="Ваш подбор"><div className="panel-title"><div><span className="eyebrow">ВАШ ЗАКАЗ</span><h2>Корзина <span className="count-badge">0</span></h2></div><ShoppingCart size={21} /></div><EmptyCart /><div className="cart-guide"><span className="eyebrow">КАК ЭТО РАБОТАЕТ</span><p><Check size={16} />Подбираем по характеристикам</p><p><Check size={16} />Проверяем доступное количество</p><p><Check size={16} />Ждём вашего подтверждения</p></div><div className="help-card"><span>Есть вопросы об условиях?</span><button onClick={() => start('Расскажите об условиях оплаты и доставки. Есть ли минимальная партия?')}>Оплата и доставка<ArrowUpRight size={17} /></button></div></aside>
      </div>
    </div>
    <dialog className="cart-dialog" ref={cartDialog}><div className="dialog-heading"><h2>Ваша корзина</h2><button className="icon-button" aria-label="Закрыть корзину" onClick={() => cartDialog.current?.close()}><X size={22} /></button></div><EmptyCart /></dialog>
  </div>;
}
