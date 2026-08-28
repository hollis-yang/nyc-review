import client from './client';

export type MapLayerMode =
  | 'BOROUGH_CLUSTERS'
  | 'NEIGHBORHOOD_CLUSTERS'
  | 'SHOP_MARKERS';

export interface MapViewportQuery {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
  typeIds: number[];
}

export interface MapClusterBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface MapClusterItem {
  kind: 'BOROUGH' | 'NEIGHBORHOOD';
  id: string;
  name: string;
  borough?: string;
  lat?: number;
  lng?: number;
  x?: number;
  y?: number;
  count: number;
  bounds?: MapClusterBounds;
  countsByType?: Record<string, number>;
}

export interface MapShopItem {
  kind: 'SHOP';
  id: number;
  name: string;
  typeId: number;
  lat?: number;
  lng?: number;
  x?: number;
  y?: number;
  score?: number | null;
  avgPrice?: number | null;
  neighborhood?: string;
  area?: string;
  thumbnailUrl?: string;
  images?: string;
  sourceType?: string;
  illustrativeImage?: boolean;
  syntheticScore?: boolean;
}

export type MapViewportItem = MapClusterItem | MapShopItem;

export interface MapViewportData {
  mode: MapLayerMode;
  zoom: number;
  detailZoom: number;
  dataVersion?: string;
  matchedCount?: number;
  truncated?: boolean;
  tooDense?: boolean;
  minZoomRequired?: number;
  items: MapViewportItem[];
}

interface MapViewportEnvelope {
  success: boolean;
  errorMsg?: string;
  data: MapViewportData;
}

export function getMapViewport(query: MapViewportQuery, signal?: AbortSignal) {
  const params: Record<string, string | number> = {
    west: query.west,
    south: query.south,
    east: query.east,
    north: query.north,
    zoom: query.zoom,
  };

  if (query.typeIds.length > 0) {
    params.typeIds = [...query.typeIds].sort((a, b) => a - b).join(',');
  }

  return client.get<never, MapViewportEnvelope>('/shop/map', { params, signal });
}
