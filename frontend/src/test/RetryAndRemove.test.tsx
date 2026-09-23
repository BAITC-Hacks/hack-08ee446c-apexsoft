import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { chat, emptyCart, filledCart, integrations, product } from './fixtures';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
beforeEach(() => window.history.replaceState({}, '', '/'));

it('reuses the same chat request id after a lost reply, but not for the next message', async () => {
  const bodies: {request_id:string; message:string; attachment_ids:string[]}[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path:string, init?:RequestInit) => {
    if (path === '/api/session') return json({session_id:'test',csrf_token:'csrf',cart:emptyCart,integrations});
    if (path === '/api/attachments') return json({attachment_id:'file-1',name:'spec.pdf',kind:'document',extracted_text:'test',warnings:[]});
    if (path === '/api/chat') {
      bodies.push(JSON.parse(String(init?.body)));
      if (bodies.length === 1) throw new TypeError('simulated lost response');
      return json({...chat,message_id:`reply-${bodies.length}`});
    }
    throw new Error(path);
  }));
  const user = userEvent.setup(); render(<App />);
  const field = screen.getByRole('textbox',{name:'Ваш запрос консультанту'});
  await waitFor(()=>expect(screen.getByLabelText('Файл для консультанта')).toBeEnabled());
  await user.upload(screen.getByLabelText('Файл для консультанта'),new File(['test'],'spec.pdf',{type:'application/pdf'}));
  await screen.findByRole('button',{name:'Убрать файл spec.pdf'});
  await user.type(field,'Найди товар');
  await user.click(screen.getByRole('button',{name:'Отправить сообщение'}));
  await screen.findByText(/Нет соединения с консультантом/);
  expect(field).toHaveValue('Найди товар');
  expect(screen.getByRole('button',{name:'Убрать файл spec.pdf'})).toBeInTheDocument();
  await user.click(screen.getByRole('button',{name:'Отправить сообщение'}));
  await screen.findByText(chat.text);
  expect(bodies[0].request_id).toMatch(/^[\w-]{10,100}$/);
  expect(bodies[1]).toEqual(bodies[0]);
  expect(screen.queryByRole('button',{name:'Убрать файл spec.pdf'})).not.toBeInTheDocument();
  await user.type(field,'Найди товар');
  await user.click(screen.getByRole('button',{name:'Отправить сообщение'}));
  await waitFor(()=>expect(bodies).toHaveLength(3));
  expect(bodies[2].request_id).not.toBe(bodies[0].request_id);
});

it.each(['/', '/cart'])('removes a cart line only on explicit click and shows the server total at %s', async path => {
  window.history.replaceState({}, '', path);
  const removed: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url:string, init?:RequestInit) => {
    if (url === '/api/session') return json({session_id:'test',csrf_token:'csrf',cart:filledCart,integrations});
    if (url === '/api/cart/remove') {
      removed.push(JSON.parse(String(init?.body)));
      return json({cart:{...emptyCart,version:2}});
    }
    throw new Error(url);
  }));
  const user = userEvent.setup(); render(<App />);
  const button = await screen.findByRole('button',{name:`Удалить ${product.name} из корзины`});
  expect(removed).toHaveLength(0);
  await user.click(button);
  await screen.findByText(`«${product.name}» удалён из корзины.`);
  expect(removed).toEqual([{product_id:product.id,version:1,confirmed:true}]);
  expect(screen.queryByRole('button',{name:`Удалить ${product.name} из корзины`})).not.toBeInTheDocument();
  expect(screen.getByRole('link',{name:/Моя корзина\s*0/})).toBeInTheDocument();
});

it('keeps the cart line and total when deletion fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url:string) => {
    if (url === '/api/session') return json({session_id:'test',csrf_token:'csrf',cart:filledCart,integrations});
    if (url === '/api/cart/remove') return json({error:{code:'unavailable',message:'Удаление не выполнено.'}},503);
    throw new Error(url);
  }));
  const user = userEvent.setup(); render(<App />);
  await user.click(await screen.findByRole('button',{name:`Удалить ${product.name} из корзины`}));
  await screen.findByText('Удаление не выполнено.');
  expect(screen.getByRole('button',{name:`Удалить ${product.name} из корзины`})).toBeEnabled();
  expect(screen.getByRole('link',{name:/Моя корзина\s*2/})).toBeInTheDocument();
});
