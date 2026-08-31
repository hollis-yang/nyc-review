import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import { Toast } from 'antd-mobile';
import { getShopTypes } from '../../api/shop';
import {
  getMapViewport,
  type MapClusterItem,
  type MapLayerMode,
  type MapShopItem,
  type MapViewportData,
  type MapViewportItem,
} from '../../api/map';
import FootBar from '../../components/FootBar';
import 'leaflet/dist/leaflet.css';
import styles from './Map.module.css';
import MerchantVisual from '../../components/MerchantVisual';

interface ShopType {
  id: number;
  name: string;
  icon: string;
  slug?: string;
  mapColor?: string;
}

interface ViewportState {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
  centerLat: number;
  centerLng: number;
}

interface InitialMapState {
  center: [number, number];
  zoom: number;
  selectedTypeIds: Set<number>;
}

const TYPE_COLORS: Record<number, string> = {
  1: '#FF6B35',
  2: '#9B59B6',
  3: '#E74C3C',
  4: '#2ECC71',
  5: '#3498DB',
  6: '#F39C12',
};

const FALLBACK_TYPES: ShopType[] = [
  { id: 1, name: 'Food & Dining', icon: '' },
  { id: 2, name: 'Cafes & Desserts', icon: '' },
  { id: 3, name: 'Bars & Nightlife', icon: '' },
  { id: 4, name: 'Entertainment & Attractions', icon: '' },
  { id: 5, name: 'Fitness & Wellness', icon: '' },
  { id: 6, name: 'Beauty & Personal Care', icon: '' },
];

const NYC_CENTER: [number, number] = [40.758, -73.9855];
const DEFAULT_ZOOM = 12;
const DETAIL_ZOOM = 15;
const MAX_ZOOM = 22;
const VIEWPORT_DEBOUNCE_MS = 180;

const USER_LOCATION_ICON = L.divIcon({
  className: '',
  html: '<div class="map-user-location-marker"></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

function parseFiniteNumber(value: string | null): number | null {
  if (value === null || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseInitialMapState(searchParams: URLSearchParams): InitialMapState {
  const lat = parseFiniteNumber(searchParams.get('lat'));
  const lng = parseFiniteNumber(searchParams.get('lng'));
  const zoom = parseFiniteNumber(searchParams.get('zoom'));
  const hasValidCenter = lat !== null && lng !== null
    && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
  const normalizedZoom = zoom !== null
    ? Math.min(MAX_ZOOM, Math.max(8, Math.round(zoom)))
    : DEFAULT_ZOOM;
  const selectedTypeIds = new Set(
    (searchParams.get('types') ?? '')
      .split(',')
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0),
  );

  return {
    center: hasValidCenter ? [lat, lng] : NYC_CENTER,
    zoom: normalizedZoom,
    selectedTypeIds,
  };
}

function normalizeCoordinate(value: number): number {
  return Number(value.toFixed(6));
}

function viewportKey(viewport: ViewportState): string {
  return [
    viewport.west,
    viewport.south,
    viewport.east,
    viewport.north,
    viewport.zoom,
  ].join(':');
}

function resolveTypeColor(type: ShopType | undefined): string {
  if (type?.mapColor && /^#[0-9a-f]{6}$/i.test(type.mapColor)) {
    return type.mapColor;
  }
  return TYPE_COLORS[type?.id ?? 0] ?? '#777777';
}

function safeMarkerInitial(name: string): string {
  const firstCharacter = Array.from(name.trim())[0] ?? '?';
  return /[\p{L}\p{N}]/u.test(firstCharacter) ? firstCharacter : '?';
}

function createTypeIcon(typeName: string, color: string) {
  return L.divIcon({
    className: 'map-shop-marker',
    html: `<div class="map-shop-pin" style="--map-pin-color:${color}" aria-hidden="true"><span>${safeMarkerInitial(typeName)}</span></div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 30],
    popupAnchor: [0, -30],
  });
}

function createClusterIcon(
  count: number,
  mode: Exclude<MapLayerMode, 'SHOP_MARKERS'>,
  locale: string,
) {
  const safeCount = Math.max(0, Math.round(count));
  const label = new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(safeCount);
  const size = Math.min(58, 38 + Math.log10(Math.max(1, safeCount)) * 6);
  const levelClass = mode === 'BOROUGH_CLUSTERS' ? 'borough' : 'neighborhood';

  return L.divIcon({
    className: `map-cluster-icon map-cluster-icon--${levelClass}`,
    html: `<span aria-hidden="true">${label}</span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function getItemPosition(item: MapViewportItem): [number, number] | null {
  const lat = item.lat ?? item.y;
  const lng = item.lng ?? item.x;
  if (lat === undefined || lng === undefined || !Number.isFinite(lat) || !Number.isFinite(lng)) {
    return null;
  }
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  return [lat, lng];
}

function haversine(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const earthRadiusKm = 6371;
  const latitudeDelta = ((lat2 - lat1) * Math.PI) / 180;
  const longitudeDelta = ((lng2 - lng1) * Math.PI) / 180;
  const value =
    Math.sin(latitudeDelta / 2) * Math.sin(latitudeDelta / 2) +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) *
    Math.sin(longitudeDelta / 2) * Math.sin(longitudeDelta / 2);
  return earthRadiusKm * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function formatDistance(km: number): string {
  const miles = km * 0.621371;
  if (miles < 0.1) return `${Math.round(km * 3280.84)}ft`;
  return `${miles.toFixed(1)}mi`;
}

function isCanceledRequest(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const candidate = error as { code?: string; name?: string };
  return candidate.code === 'ERR_CANCELED' || candidate.name === 'CanceledError' || candidate.name === 'AbortError';
}

function normalizeSelection(selected: Set<number>, types: ShopType[]): Set<number> {
  if (selected.size === 0) return selected;
  const validIds = new Set(types.map((type) => type.id));
  const normalized = new Set([...selected].filter((id) => validIds.has(id)));
  if (normalized.size === validIds.size) return new Set();
  if (normalized.size === selected.size && [...normalized].every((id) => selected.has(id))) {
    return selected;
  }
  return normalized;
}

function MapEvents({
  centerOn,
  onViewportChange,
}: {
  centerOn: [number, number] | null;
  onViewportChange: (viewport: ViewportState) => void;
}) {
  const map = useMap();
  const debounceTimer = useRef<number | null>(null);

  const publishViewport = useCallback(() => {
    const bounds = map.getBounds();
    const center = map.getCenter();
    onViewportChange({
      west: normalizeCoordinate(bounds.getWest()),
      south: normalizeCoordinate(bounds.getSouth()),
      east: normalizeCoordinate(bounds.getEast()),
      north: normalizeCoordinate(bounds.getNorth()),
      zoom: map.getZoom(),
      centerLat: normalizeCoordinate(center.lat),
      centerLng: normalizeCoordinate(center.lng),
    });
  }, [map, onViewportChange]);

  const scheduleViewportPublish = useCallback(() => {
    if (debounceTimer.current !== null) window.clearTimeout(debounceTimer.current);
    debounceTimer.current = window.setTimeout(publishViewport, VIEWPORT_DEBOUNCE_MS);
  }, [publishViewport]);

  useMapEvents({
    moveend: scheduleViewportPublish,
    zoomend: scheduleViewportPublish,
  });

  useEffect(() => {
    const initialTimer = window.setTimeout(publishViewport, 0);
    return () => {
      window.clearTimeout(initialTimer);
      if (debounceTimer.current !== null) window.clearTimeout(debounceTimer.current);
    };
  }, [publishViewport]);

  useEffect(() => {
    if (centerOn) map.flyTo(centerOn, DETAIL_ZOOM, { duration: 1 });
  }, [centerOn, map]);

  return null;
}

function MapResizeObserver() {
  const map = useMap();

  useEffect(() => {
    const mapElement = map.getContainer();
    const invalidateSize = () => map.invalidateSize({ pan: false, animate: false });
    const initialTimer = window.setTimeout(invalidateSize, 0);

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', invalidateSize);
      return () => {
        window.clearTimeout(initialTimer);
        window.removeEventListener('resize', invalidateSize);
      };
    }

    const observer = new ResizeObserver(invalidateSize);
    observer.observe(mapElement);
    return () => {
      window.clearTimeout(initialTimer);
      observer.disconnect();
    };
  }, [map]);

  return null;
}

function MapLayers({
  data,
  types,
  userPos,
}: {
  data: MapViewportData | null;
  types: ShopType[];
  userPos: [number, number] | null;
}) {
  const { t: tt, i18n } = useTranslation();
  const navigate = useNavigate();
  const map = useMap();
  const typeMap = useMemo(
    () => new Map(types.map((type) => [type.id, type])),
    [types],
  );
  const typeIcons = useMemo(
    () => new Map(types.map((type) => [
      type.id,
      createTypeIcon(type.name, resolveTypeColor(type)),
    ])),
    [types],
  );
  const locale = i18n.resolvedLanguage ?? i18n.language ?? 'en';

  return (
    <>
      {userPos && (
        <Marker position={userPos} icon={USER_LOCATION_ICON}>
          <Popup>{tt('map.myLocation')}</Popup>
        </Marker>
      )}

      {data?.items.map((item) => {
        const position = getItemPosition(item);
        if (!position) return null;

        if (data.mode !== 'SHOP_MARKERS') {
          const cluster = item as MapClusterItem;
          const clusterName = cluster.name === '__UNASSIGNED__'
            ? tt('map.unassignedLocations', { borough: cluster.borough ?? '' })
            : (cluster.name || cluster.borough || cluster.id);
          const targetZoom = data.mode === 'BOROUGH_CLUSTERS'
            ? Math.max(11, Math.min((data.detailZoom || DETAIL_ZOOM) - 1, map.getZoom() + 2))
            : Math.min(MAX_ZOOM, Math.max(data.detailZoom || DETAIL_ZOOM, map.getZoom() + 1));
          return (
            <Marker
              key={`${data.mode}:${cluster.id}`}
              position={position}
              icon={createClusterIcon(cluster.count, data.mode, locale)}
              alt={`${clusterName}: ${cluster.count}`}
              title={`${clusterName}: ${cluster.count}`}
              eventHandlers={{
                click: () => map.flyTo(position, targetZoom, { duration: 0.65 }),
              }}
            >
              <Tooltip direction="top" offset={[0, -18]} opacity={0.94}>
                <strong>{clusterName}</strong>
                <br />
                {tt('map.shopCount', { count: cluster.count })}
              </Tooltip>
            </Marker>
          );
        }

        const shop = item as MapShopItem;
        const shopType = typeMap.get(shop.typeId);
        const icon = typeIcons.get(shop.typeId)
          ?? createTypeIcon(shopType?.name ?? '?', resolveTypeColor(shopType));
        const distance = userPos
          ? haversine(userPos[0], userPos[1], position[0], position[1])
          : null;
        const score = shop.score == null
          ? null
          : (shop.score > 5 ? shop.score / 10 : shop.score);
        return (
          <Marker
            key={`shop:${shop.id}`}
            position={position}
            icon={icon}
            alt={shop.name}
            title={shop.name}
          >
            <Popup>
              <div className={styles.popupContent}>
                <div className={styles.popupSummary}>
                  <MerchantVisual
                    shopId={shop.id}
                    name={shop.name}
                    typeId={shop.typeId}
                    images={shop.thumbnailUrl || shop.images}
                    alt={shop.name}
                    className={styles.popupImage}
                    loading="lazy"
                  />
                  <div className={styles.popupText}>
                    <div className={styles.popupName}>{shop.name}</div>
                    <div className={styles.popupMeta}>
                      {shopType?.name
                        ? tt(`shopTypes.${shopType.name}`, shopType.name)
                        : tt('map.unknownCategory')}
                      {score !== null && ` · ⭐${score.toFixed(1)}`}
                      {shop.avgPrice != null && ` · $${shop.avgPrice}/${tt('map.person')}`}
                    </div>
                    <div className={styles.popupArea}>
                      {shop.neighborhood || shop.area || ''}
                      {distance !== null && ` · ${formatDistance(distance)}`}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className={styles.popupDetailButton}
                  onClick={() => navigate(`/shop-detail/${shop.id}`)}
                >
                  {tt('map.viewDetail')}
                </button>
              </div>
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}

export default function MapPage() {
  const { t: tt } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [initialMapState] = useState(() => parseInitialMapState(searchParams));
  const [types, setTypes] = useState<ShopType[]>(FALLBACK_TYPES);
  const [typesReady, setTypesReady] = useState(false);
  const [selectedTypeIds, setSelectedTypeIds] = useState(initialMapState.selectedTypeIds);
  const [viewport, setViewport] = useState<ViewportState | null>(null);
  const [mapData, setMapData] = useState<MapViewportData | null>(null);
  const [mapLoading, setMapLoading] = useState(true);
  const [mapError, setMapError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);
  const requestSequence = useRef(0);
  const lastViewportKey = useRef('');

  const selectedTypeKey = useMemo(
    () => [...selectedTypeIds].sort((a, b) => a - b).join(','),
    [selectedTypeIds],
  );

  useEffect(() => {
    let active = true;
    getShopTypes()
      .then((response) => {
        if (!active) return;
        const payload = response.data ?? response;
        const loadedTypes = Array.isArray(payload) && payload.length > 0
          ? payload as ShopType[]
          : FALLBACK_TYPES;
        setTypes(loadedTypes);
        setSelectedTypeIds((current) => normalizeSelection(current, loadedTypes));
      })
      .catch(() => {
        if (!active) return;
        setTypes(FALLBACK_TYPES);
        setSelectedTypeIds((current) => normalizeSelection(current, FALLBACK_TYPES));
        Toast.show({ icon: 'fail', content: tt('map.categoriesLoadFailed') });
      })
      .finally(() => {
        if (active) setTypesReady(true);
      });

    return () => {
      active = false;
    };
  }, [tt]);

  useEffect(() => {
    if (!viewport || !typesReady) return undefined;

    const abortController = new AbortController();
    const sequence = ++requestSequence.current;
    let active = true;
    const typeIds = selectedTypeKey
      ? selectedTypeKey.split(',').map((value) => Number(value))
      : [];

    getMapViewport({
      west: viewport.west,
      south: viewport.south,
      east: viewport.east,
      north: viewport.north,
      zoom: viewport.zoom,
      typeIds,
    }, abortController.signal)
      .then((response) => {
        if (!active || sequence !== requestSequence.current) return;
        if (!response.data || !Array.isArray(response.data.items)) {
          throw new Error('Invalid map response');
        }
        setMapData(response.data);
      })
      .catch((error: unknown) => {
        if (!active || sequence !== requestSequence.current || isCanceledRequest(error)) return;
        setMapData(null);
        setMapError(true);
        Toast.show({ icon: 'fail', content: tt('map.loadFailed') });
      })
      .finally(() => {
        if (active && sequence === requestSequence.current) setMapLoading(false);
      });

    return () => {
      active = false;
      abortController.abort();
    };
  }, [retryToken, selectedTypeKey, tt, typesReady, viewport]);

  useEffect(() => {
    if (!viewport) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('lat', viewport.centerLat.toFixed(5));
      next.set('lng', viewport.centerLng.toFixed(5));
      next.set('zoom', String(viewport.zoom));
      if (selectedTypeKey) next.set('types', selectedTypeKey);
      else next.delete('types');
      return next.toString() === current.toString() ? current : next;
    }, { replace: true });
  }, [selectedTypeKey, setSearchParams, viewport]);

  const handleViewportChange = useCallback((nextViewport: ViewportState) => {
    const nextKey = viewportKey(nextViewport);
    if (lastViewportKey.current === nextKey) return;
    lastViewportKey.current = nextKey;
    setMapLoading(true);
    setMapError(false);
    setViewport(nextViewport);
  }, []);

  const toggleType = useCallback((typeId: number) => {
    const next = selectedTypeIds.size === 0
      ? new Set([typeId])
      : new Set(selectedTypeIds);
    if (selectedTypeIds.size > 0) {
      if (next.has(typeId)) next.delete(typeId);
      else next.add(typeId);
    }
    const normalized = next.size === 0 || next.size === types.length ? new Set<number>() : next;
    setMapLoading(true);
    setMapError(false);
    setSelectedTypeIds(normalized);
  }, [selectedTypeIds, types.length]);

  const selectAllTypes = useCallback(() => {
    if (selectedTypeIds.size === 0) return;
    setMapLoading(true);
    setMapError(false);
    setSelectedTypeIds(new Set());
  }, [selectedTypeIds.size]);

  const retryMap = useCallback(() => {
    setMapLoading(true);
    setMapError(false);
    setRetryToken((value) => value + 1);
  }, []);

  const locateMe = useCallback(() => {
    const fallbackToNyc = () => {
      setUserPos(NYC_CENTER);
      setFlyTo([...NYC_CENTER]);
    };

    if (!('geolocation' in navigator)) {
      fallbackToNyc();
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coordinates: [number, number] = [
          position.coords.latitude,
          position.coords.longitude,
        ];
        setUserPos(coordinates);
        setFlyTo(coordinates);
        Toast.show({ icon: 'success', content: tt('map.located') });
      },
      fallbackToNyc,
    );
  }, [tt]);

  const modeLabel = mapData?.mode === 'BOROUGH_CLUSTERS'
    ? tt('map.boroughView')
    : mapData?.mode === 'NEIGHBORHOOD_CLUSTERS'
      ? tt('map.neighborhoodView')
      : tt('map.shopView');

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerTitle}>{tt('map.title')}</div>
      </div>

      <div className={styles.mapWrap}>
        <div className={styles.filterPanel}>
          <div className={styles.filterScroller} role="group" aria-label={tt('map.categoryFilter')}>
            <button
              type="button"
              className={`${styles.filterChip} ${selectedTypeIds.size === 0 ? styles.filterChipActive : ''}`}
              aria-pressed={selectedTypeIds.size === 0}
              onClick={selectAllTypes}
            >
              {tt('map.allCategories')}
            </button>
            {types.map((type) => {
              const selected = selectedTypeIds.has(type.id);
              return (
                <button
                  key={type.id}
                  type="button"
                  className={`${styles.filterChip} ${selected ? styles.filterChipActive : ''}`}
                  aria-pressed={selected}
                  onClick={() => toggleType(type.id)}
                >
                  <span
                    className={styles.filterDot}
                    style={{ background: resolveTypeColor(type) }}
                    aria-hidden="true"
                  />
                  {tt(`shopTypes.${type.name}`, type.name)}
                </button>
              );
            })}
          </div>
        </div>

        <div className={styles.mapCanvas}>
          <MapContainer
            center={initialMapState.center}
            zoom={initialMapState.zoom}
            minZoom={8}
            maxZoom={MAX_ZOOM}
            className={styles.map}
            zoomControl={false}
            preferCanvas
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapResizeObserver />
            <MapEvents centerOn={flyTo} onViewportChange={handleViewportChange} />
            <MapLayers data={mapData} types={types} userPos={userPos} />
          </MapContainer>

          {mapData && (
            <div className={styles.modeBadge} aria-live="polite">
              {modeLabel}
              {mapLoading && <span className={styles.updatingDot} aria-label={tt('map.updating')} />}
            </div>
          )}

          {mapLoading && !mapData && (
            <div className={styles.loadingOverlay} role="status">
              <span className={styles.spinner} />
              {tt('map.loading')}
            </div>
          )}

          {mapError && !mapData && !mapLoading && (
            <div className={styles.errorOverlay} role="alert">
              <span>{tt('map.loadFailed')}</span>
              <button type="button" onClick={retryMap}>
                {tt('map.retry')}
              </button>
            </div>
          )}

          {!mapLoading && !mapError && mapData?.items.length === 0 && (
            <div className={styles.emptyBadge}>{tt('map.noShopsInView')}</div>
          )}

          {(mapData?.tooDense || mapData?.truncated) && (
            <div className={styles.densityNotice} role="status">
              {tt('map.zoomInForShops', {
                zoom: mapData.minZoomRequired ?? mapData.detailZoom ?? DETAIL_ZOOM,
              })}
            </div>
          )}

          <button
            type="button"
            className={styles.locateBtn}
            onClick={locateMe}
            aria-label={tt('map.locateMe')}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true">
              <path d="M12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm8.94 3A8.994 8.994 0 0 0 13 3.06V1h-2v2.06A8.994 8.994 0 0 0 3.06 11H1v2h2.06A8.994 8.994 0 0 0 11 20.94V23h2v-2.06A8.994 8.994 0 0 0 20.94 13H23v-2h-2.06zM12 19c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z" />
            </svg>
          </button>
        </div>
      </div>

      <FootBar activeBtn={2} />
    </div>
  );
}
