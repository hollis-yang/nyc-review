import client from './client';

export function getHotBlogs(current: number) {
  return client.get('/blog/hot', { params: { current } });
}

export function getBlogById(id: number | string) {
  return client.get(`/blog/${id}`);
}

export function getBlogLikes(id: number | string) {
  return client.get(`/blog/likes/${id}`);
}

export function likeBlog(id: number | string) {
  return client.put(`/blog/like/${id}`);
}

export function getBlogsOfMe(current: number = 1) {
  return client.get('/blog/of/me', { params: { current } });
}

export function getBlogsOfFollow(params: { offset: number; lastId: number }) {
  return client.get('/blog/of/follow', { params });
}

export function getBlogsOfUser(id: number | string, current: number = 1) {
  return client.get('/blog/of/user', { params: { id, current } });
}

export function getBlogComments(blogId: number | string) {
  return client.get('/blog-comments', { params: { blogId } });
}

export function createBlogComment(data: {
  blogId: number;
  content: string;
  parentId?: number;
  answerId?: number;
}) {
  return client.post('/blog-comments', data);
}

export function createBlog(data: {
  title: string;
  content: string;
  images: string;
  shopId: number;
}) {
  return client.post('/blog', data);
}
