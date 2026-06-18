import client from './client';

export function translateBlog(blogId: number | string, targetLang: string = 'en') {
  return client.post('/translate/blog', null, { params: { blogId, targetLang } });
}

export function translateComment(commentId: number | string, targetLang: string = 'en') {
  return client.post('/translate/comment', null, { params: { commentId, targetLang } });
}
