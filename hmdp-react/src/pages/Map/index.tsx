import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Toast } from 'antd-mobile';
import { getAllShops, getShopTypes } from '../../api/shop';
import FootBar from '../../components/FootBar';
import 'leaflet/dist/leaflet.css';
import styles from './Map.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

interface Shop {
  id: number;
  name: string;
  typeId: number;
  x: number;
  y: number;
  images: string;
  score: number;
  avgPrice: number;
  area: string;
}

const TYPE_COLORS: Record<number, string> = {
  1: '#FF6B35',
  2: '#9B59B6',
  3: '#E74C3C',
  4: '#2ECC71',
  5: '#3498DB',
  6: '#F39C12',
};

const NYC_CENTER: [number, number] = [40.758, -73.9855];

function haversine(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) *
    Math.sin(dLng / 2) * Math.sin(dLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function formatDistance(km: number): string {
  const miles = km * 0.621371;
  if (miles < 0.1) return `${Math.round(km * 3280.84)}ft`;
  return `${miles.toFixed(1)}mi`;
}

function createTypeIcon(typeName: string, color: string) {
  return L.divIcon({
    className: 'custom-marker',
    html: `<div style="
      background:${color};
      color:#fff;
      width:28px;
      height:28px;
      border-radius:50% 50% 50% 0;
      transform:rotate(-45deg);
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:12px;
      font-weight:bold;
      box-shadow:0 2px 6px rgba(0,0,0,0.3);
      border:2px solid #fff;
    "><span style="transform:rotate(45deg)">${typeName.charAt(0)}</span></div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 28],
    popupAnchor: [0, -28],
  });
}

function MapController({ centerOn }: { centerOn: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (centerOn) {
      map.flyTo(centerOn, 15, { duration: 1 });
    }
  }, [centerOn, map]);
  return null;
}

export default function MapPage() {
  const { t: tt } = useTranslation();
  const navigate = useNavigate();
  const [shops, setShops] = useState<Shop[]>([]);
  const [types, setTypes] = useState<ShopType[]>([]);
  const [loading, setLoading] = useState(true);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);

  useEffect(() => {
    Promise.all([
      getAllShops().then((res) => res.data ?? res),
      getShopTypes().then((res) => res.data ?? res),
    ])
      .then(([shopList, typeList]) => {
        const sl = Array.isArray(shopList) ? shopList : [];
        setShops(sl);
        setTypes(Array.isArray(typeList) ? typeList : []);
      })
      .catch(() => Toast.show({ icon: 'fail', content: tt('map.loadFailed') }))
      .finally(() => setLoading(false));
  }, []);

  const locateMe = useCallback(() => {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const coords: [number, number] = [pos.coords.latitude, pos.coords.longitude];
          setUserPos(coords);
          setFlyTo(coords);
          Toast.show({ icon: 'success', content: tt('map.located') });
        },
        () => {
          const fallback: [number, number] = NYC_CENTER;
          setUserPos(fallback);
          setFlyTo(fallback);
        }
      );
    } else {
      const fallback: [number, number] = NYC_CENTER;
      setUserPos(fallback);
      setFlyTo(fallback);
    }
  }, []);

  const typeMap = new Map<number, ShopType>();
  types.forEach((t) => typeMap.set(t.id, t));

  const defaultCenter: [number, number] = NYC_CENTER;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerTitle}>{tt('map.title')}</div>
        <button className={styles.aiButton} onClick={() => navigate('/ai')}>AI</button>
      </div>

      <div className={styles.mapWrap}>
        {loading ? (
          <div className={styles.loading}>{tt('map.loading')}</div>
        ) : (
          <MapContainer
            center={defaultCenter}
            zoom={12}
            className={styles.map}
            zoomControl={false}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapController centerOn={flyTo} />
            {userPos && (
              <Marker
                position={userPos}
                icon={L.divIcon({
                  className: '',
                  html: '<div style="background:#2196F3;width:16px;height:16px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 3px #2196F3;"></div>',
                  iconSize: [22, 22],
                  iconAnchor: [11, 11],
                })}
              >
                <Popup>{tt('map.myLocation')}</Popup>
              </Marker>
            )}
            {shops.map((shop) => {
              const t = typeMap.get(shop.typeId);
              const color = TYPE_COLORS[shop.typeId] || '#999';
              const dist = userPos ? haversine(userPos[0], userPos[1], shop.y, shop.x) : null;
              const scoreText = shop.score ? (shop.score / 10).toFixed(1) : '-';
              return (
                <Marker
                  key={shop.id}
                  position={[shop.y, shop.x]}
                  icon={createTypeIcon(t?.name || '?', color)}
                >
                  <Popup>
                    <div className={styles.popupContent}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <img
                          src={shop.images ? shop.images.split(',')[0] : '/imgs/icons/default-icon.png'}
                          alt={shop.name}
                          style={{ width: 50, height: 50, borderRadius: 6, objectFit: 'cover' }}
                        />
                        <div>
                          <div style={{ fontWeight: 700, fontSize: 14 }}>{shop.name}</div>
                          <div style={{ fontSize: 12, color: '#999' }}>
                            {(t?.name ? tt(`shopTypes.${t.name}`, t.name) : '')} · ⭐{scoreText} · ${shop.avgPrice || '-'}/person
                          </div>
                          <div style={{ fontSize: 11, color: '#bbb' }}>
                            {shop.area || ''}
                            {dist !== null && ` · ${formatDistance(dist)}`}
                          </div>
                        </div>
                      </div>
                      <div
                        style={{ marginTop: 6, textAlign: 'center', color: '#F63', fontSize: 13, cursor: 'pointer' }}
                        onClick={() => navigate(`/shop-detail/${shop.id}`)}
                      >
                        {tt('map.viewDetail')}
                      </div>
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MapContainer>
        )}

        <div className={styles.locateBtn} onClick={locateMe}>
        <svg viewBox="0 0 24 24" width="22" height="22" fill="#F63">
          <path d="M12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm8.94 3A8.994 8.994 0 0 0 13 3.06V1h-2v2.06A8.994 8.994 0 0 0 3.06 11H1v2h2.06A8.994 8.994 0 0 0 11 20.94V23h2v-2.06A8.994 8.994 0 0 0 20.94 13H23v-2h-2.06zM12 19c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z"/>
        </svg>
      </div>
      </div>

      <div className={styles.legend}>
        {types.map((tp2) => (
          <div key={tp2.id} className={styles.legendItem}>
            <span
              className={styles.legendDot}
              style={{ background: TYPE_COLORS[tp2.id] || '#999' }}
            />
            <span>{tt(`shopTypes.${tp2.name}`, tp2.name)}</span>
          </div>
        ))}
      </div>

      <FootBar activeBtn={2} />
    </div>
  );
}
