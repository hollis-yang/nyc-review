import client from './client';

export interface FavoriteShopAsset {
  id: number;
  shopId: number;
  name: string;
  images?: string;
  address?: string;
  borough?: string;
  neighborhood?: string;
  createdAt: string;
}

export interface SavedItineraryAsset {
  id: number;
  runId: string;
  title: string;
  shopIds: number[];
  shopNames: string[];
  itinerary: {
    total_estimated_cost_cents?: number;
    warnings?: string[];
  };
  updatedAt: string;
}

export interface OwnedVoucherAsset {
  orderId: number;
  voucherId: number;
  shopId?: number;
  title: string;
  subTitle?: string;
  shopName?: string;
  type: number;
  payValue: number;
  actualValue: number;
  orderStatus: number;
  createdAt: string;
  expiresAt: string;
  expired: boolean;
}

export interface FlashSaleReminderAsset {
  id: number;
  voucherId: number;
  shopId?: number;
  voucherTitle: string;
  shopName?: string;
  remindAt: string;
  saleBeginsAt?: string;
  status: string;
}

export interface AgentMemoryAsset {
  id: number;
  key: string;
  value: string;
  source: string;
  confidence: number;
  updatedAt: string;
}

export interface ProfileAssets {
  favorites: FavoriteShopAsset[];
  itineraries: SavedItineraryAsset[];
  vouchers: OwnedVoucherAsset[];
  reminders: FlashSaleReminderAsset[];
  memories: AgentMemoryAsset[];
  counts: {
    favorites: number;
    itineraries: number;
    vouchers: number;
    reminders: number;
    memories: number;
  };
}

export function getProfileAssets() {
  return client.get('/profile/assets');
}

export function getShopFavoriteStatus(shopId: number | string) {
  return client.get(`/profile/assets/favorites/${shopId}`);
}

export function favoriteShop(shopId: number | string) {
  return client.put(`/profile/assets/favorites/${shopId}`);
}

export function unfavoriteShop(shopId: number | string) {
  return client.delete(`/profile/assets/favorites/${shopId}`);
}

export function updateAgentMemory(id: number, value: string) {
  return client.put(`/profile/assets/memories/${id}`, { value });
}

export function deleteAgentMemory(id: number) {
  return client.delete(`/profile/assets/memories/${id}`);
}
