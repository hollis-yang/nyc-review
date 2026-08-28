import client, { type AuthAwareRequestConfig } from './client';
import { getCached, setCached, makeKey } from '../utils/translateCache';

function optionalTranslationConfig(params: Record<string, number | string>): AuthAwareRequestConfig {
  return { params, skipAuthRedirect: true };
}

export async function translateBlog(blogId: number | string, targetLang: string = 'en') {
  const key = makeKey('blog', blogId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post(
    '/translate/blog',
    null,
    optionalTranslationConfig({ blogId, targetLang })
  );
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateComment(commentId: number | string, targetLang: string = 'en') {
  const key = makeKey('comment', commentId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post(
    '/translate/comment',
    null,
    optionalTranslationConfig({ commentId, targetLang })
  );
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateReview(reviewId: number | string, targetLang: string = 'en') {
  const key = makeKey('review', reviewId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post(
    '/translate/review',
    null,
    optionalTranslationConfig({ reviewId, targetLang })
  );
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateShop(shopId: number | string, targetLang: string = 'en') {
  const key = makeKey('shop', shopId, targetLang);
  const cached = getCached(key);
  if (cached) return { data: cached };
  const res = await client.post(
    '/translate/shop',
    null,
    optionalTranslationConfig({ shopId, targetLang })
  );
  const val = res.data ?? res;
  if (val) setCached(key, String(val));
  return res;
}

export async function translateText(text: string, targetLang: string = 'en') {
  return client.post(
    '/translate/text',
    { text, targetLang },
    { skipAuthRedirect: true } as AuthAwareRequestConfig,
  );
}
