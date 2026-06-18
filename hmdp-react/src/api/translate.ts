import client from './client';
import { getCached, setCached, makeKey } from '../utils/translateCache';

export async function translateBlog(blogId: number | string, targetLang: string = 'en') {
  const key = makeKey('blog', blogId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post('/translate/blog', null, { params: { blogId, targetLang } });
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateComment(commentId: number | string, targetLang: string = 'en') {
  const key = makeKey('comment', commentId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post('/translate/comment', null, { params: { commentId, targetLang } });
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateShop(shopId: number | string, targetLang: string = 'en') {
  const key = makeKey('shop', shopId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post('/translate/shop', null, { params: { shopId, targetLang } });
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}
