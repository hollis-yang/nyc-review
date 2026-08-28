import client from './client';

const MAX_IMAGE_SIZE = 5 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function uploadBlogImage(file: File) {
  if (file.size > MAX_IMAGE_SIZE) {
    throw new Error('Images cannot exceed 5 MB');
  }
  if (file.type && !ALLOWED_IMAGE_TYPES.has(file.type)) {
    throw new Error('Only JPEG, PNG, and WebP images are supported');
  }
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/upload/blog', formData);
}

export function deleteBlogImage(filePath: string) {
  return client.delete('/upload/blog', { params: { name: filePath } });
}
