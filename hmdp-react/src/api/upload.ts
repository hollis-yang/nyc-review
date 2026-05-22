import client from './client';

export function uploadBlogImage(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/upload/blog', formData);
}

export function deleteBlogImage(filePath: string) {
  return client.get('/upload/blog/delete', { params: { name: filePath } });
}
