import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { chat, emptyCart, filledCart, integrations } from './fixtures';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status});
let uploads: Set<string>;
let paths: string[];
let failRemove: boolean;
let failReset: boolean;

beforeEach(() => {
  window.history.replaceState({}, '', '/');
  uploads = new Set(); paths = []; failRemove = false; failReset = false;
  let nextId = 0;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    paths.push(path);
    if (path === '/api/session') return json({session_id:'session', csrf_token:'csrf', cart:emptyCart, integrations});
    if (path === '/api/attachments') {
      if (uploads.size >= 8) return json({error:{code:'attachment_too_large',message:'Лимит вложений.'}},413);
      const id = `file-${++nextId}`; uploads.add(id);
      return json({attachment_id:id,name:'spec.pdf',kind:'document',extracted_text:'Товар',warnings:[]});
    }
    if (path === '/api/attachments/remove') {
      if (failRemove) return json({error:{code:'unavailable',message:'Файл не удалён. Повторите.'}},503);
      const body = JSON.parse(String(init?.body));
      body.attachment_ids.forEach((id:string) => uploads.delete(id));
      return json({removed:true});
    }
    if (path === '/api/chat') return json(chat);
    if (path === '/api/chat/reset') return failReset
      ? json({error:{code:'unavailable',message:'Не удалось начать новый запрос.'}},503)
      : json({cart:filledCart});
    throw new Error(`Unexpected request: ${path}`);
  }));
});

async function open() {
  const user = userEvent.setup(); render(<App />);
  await waitFor(() => expect(screen.getByLabelText('Файл для консультанта')).toBeEnabled());
  return user;
}

it('releases removed uploads on the server so nine successive selections work', async () => {
  const user = await open();
  for (let i=0;i<9;i++) {
    await user.upload(screen.getByLabelText('Файл для консультанта'),new File(['test'],'spec.pdf',{type:'application/pdf'}));
    const remove = await screen.findByRole('button',{name:'Убрать файл spec.pdf'});
    await user.click(remove);
    await waitFor(() => expect(screen.queryByRole('button',{name:'Убрать файл spec.pdf'})).not.toBeInTheDocument());
  }
  expect(paths.filter(p=>p==='/api/attachments/remove')).toHaveLength(9);
  expect(uploads.size).toBe(0);
});

it('keeps a file visible when removing it on the server fails', async () => {
  const user = await open(); failRemove=true;
  await user.upload(screen.getByLabelText('Файл для консультанта'),new File(['test'],'spec.pdf',{type:'application/pdf'}));
  await user.click(await screen.findByRole('button',{name:'Убрать файл spec.pdf'}));
  await screen.findByText('Файл не удалён. Повторите.');
  expect(screen.getByRole('button',{name:'Убрать файл spec.pdf'})).toBeInTheDocument();
  expect(uploads.size).toBe(1);
});

it.each([false,true])('resets server conversation, clearing UI only on success (failure: %s)', async (fails) => {
  const user=await open(); failReset=fails;
  const field=screen.getByRole('textbox',{name:'Ваш запрос консультанту'});
  await user.type(field,'Найди товар');
  await user.click(screen.getByRole('button',{name:'Отправить сообщение'}));
  await screen.findByText(chat.text);
  await user.type(field,'Новый черновик');
  await user.click(screen.getByRole('button',{name:'Новый запрос'}));
  await waitFor(()=>expect(paths).toContain('/api/chat/reset'));
  if (fails) {
    await screen.findByText('Не удалось начать новый запрос.');
    expect(field).toHaveValue('Новый черновик');
    expect(screen.getByText(chat.text)).toBeInTheDocument();
  } else {
    await waitFor(()=>expect(screen.queryByText(chat.text)).not.toBeInTheDocument());
    expect(field).toHaveValue('');
    expect(field).toHaveFocus();
    expect(screen.getByRole('link',{name:/Моя корзина\s*2/})).toBeInTheDocument();
  }
});
