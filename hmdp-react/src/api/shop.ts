import client from './client';

export function getShopTypes() {
  return client.get('/shop-type/list');
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

export function getShopReviews(shopId: number | string, current: number = 1) {
  return client.get(`/shop-review/${shopId}`, { params: { current } });
}
