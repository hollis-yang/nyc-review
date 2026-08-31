import client from './client';

export function getShopTypes() {
  return client.get('/shop-type/list');
}

export function getAllShops() {
  return client.get('/shop/list');
}

export function getShopById(id: number | string) {
  return client.get(`/shop/${id}`);
}

export function getShopsByType(params: {
  typeId: number | string;
  current: number;
  sortBy?: string;
  sortOrder?: string;
  x?: number;
  y?: number;
}) {
  return client.get('/shop/of/type', { params });
}

export function getShopsByName(name: string, current: number = 1) {
  return client.get('/shop/of/name', { params: { name, current } });
}

export function getShopLinkOptions(params: {
  typeId?: number;
  query?: string;
  current?: number;
  size?: number;
}) {
  return client.get('/shop/link-options', { params });
}

export function getShopReviews(shopId: number | string, current: number = 1) {
  return client.get(`/shop-review/${shopId}`, { params: { current } });
}

export function createShopReview(data: {
  shopId: number;
  rating?: number;
  content: string;
  images?: string;
  parentId?: number;
}) {
  return client.post('/shop-review', data);
}

export function toggleShopReviewLike(reviewId: number | string) {
  return client.put(`/shop-review/${reviewId}/like`);
}
