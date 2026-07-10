import client from './client';

const MAX_IMAGE_SIZE = 5 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function uploadBlogImage(file: File) {
  if (file.size > MAX_IMAGE_SIZE) {
    throw new Error('图片不能超过5MB');
  }
  if (file.type && !ALLOWED_IMAGE_TYPES.has(file.type)) {
    throw new Error('仅支持JPEG、PNG或WebP图片');
  }
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/upload/blog', formData);
}

export function deleteBlogImage(filePath: string) {
  return client.delete('/upload/blog', { params: { name: filePath } });
}
