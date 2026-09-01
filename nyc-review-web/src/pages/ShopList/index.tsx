import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { getShopTypes, getShopsByType, getShopsByName } from '../../api/shop';
import { useTranslation } from 'react-i18next';
import ShopCard, { type ShopData } from '../../components/ShopCard';
import styles from './ShopList.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

interface DistanceOrigin {
  x: number;
  y: number;
  source: 'user' | 'times-square';
}

const TIMES_SQUARE_ORIGIN: DistanceOrigin = {
  x: -73.9855,
  y: 40.758,
  source: 'times-square',
};

export default function ShopList() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const typeId = searchParams.get('type') || '0';
  const typeName = searchParams.get('name') || '';
  const searchQuery = searchParams.get('query') || '';
  const [distanceOrigin, setDistanceOrigin] = useState<DistanceOrigin | null>(null);
  const sortOptions = [
    {
      label: t(distanceOrigin?.source === 'user'
        ? 'shopList.distanceFromYou'
        : 'shopList.distanceFromTimesSquare'),
      field: 'distance',
    },
    { label: t('shopList.popularity'), field: 'popularity' },
    { label: t('shopList.rating'), field: 'rating' },
  ] as const;

  const [types, setTypes] = useState<ShopType[]>([]);
  const [shops, setShops] = useState<ShopData[]>([]);
  const [visible, setVisible] = useState(false);
  const [sortBy, setSortBy] = useState('distance');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [current, setCurrent] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);
  const requestSequence = useRef(0);
  const requestAbortController = useRef<AbortController | null>(null);
  const underfillAttemptLength = useRef<number | null>(null);

  useEffect(() => {
    getShopTypes()
      .then((res) => setTypes(res.data ?? res))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    const applyFallback = () => {
      if (active) setDistanceOrigin(TIMES_SQUARE_ORIGIN);
    };

    if (!('geolocation' in navigator)) {
      queueMicrotask(applyFallback);
      return () => { active = false; };
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!active) return;
        setDistanceOrigin({
          x: position.coords.longitude,
          y: position.coords.latitude,
          source: 'user',
        });
      },
      applyFallback,
      { enableHighAccuracy: false, timeout: 5000, maximumAge: 300000 },
    );
    return () => { active = false; };
  }, []);

  const loadShops = useCallback(async () => {
    if (loadingRef.current || !hasMore || !distanceOrigin) return;
    const abortController = new AbortController();
    const sequence = ++requestSequence.current;
    requestAbortController.current = abortController;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = searchQuery
        ? await getShopsByName(searchQuery, current, abortController.signal)
        : await getShopsByType({
            typeId,
            current,
            sortBy,
            sortOrder,
            x: distanceOrigin.x,
            y: distanceOrigin.y,
          }, abortController.signal);
      if (sequence !== requestSequence.current || abortController.signal.aborted) return;
      const data = res.data ?? res;
      if (!data || data.length === 0) {
        setHasMore(false);
      } else {
        setShops((prev) => [...prev, ...data]);
        setCurrent((prev) => prev + 1);
      }
    } catch {
      // ignore
    } finally {
      if (sequence === requestSequence.current) {
        loadingRef.current = false;
        requestAbortController.current = null;
        setLoading(false);
      }
    }
  }, [typeId, current, sortBy, sortOrder, searchQuery, hasMore, distanceOrigin]);

  useEffect(() => {
    // Reset pagination when the user changes the query contract.
    requestAbortController.current?.abort();
    requestSequence.current += 1;
    loadingRef.current = false;
    underfillAttemptLength.current = null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShops([]);
    setCurrent(1);
    setHasMore(true);
    setLoading(false);
  }, [typeId, sortBy, sortOrder, searchQuery]);

  useEffect(() => () => {
    requestSequence.current += 1;
    requestAbortController.current?.abort();
  }, []);

  useEffect(() => {
    if (distanceOrigin && shops.length === 0 && hasMore) {
      // Initial and reset-triggered fetch; loadShops owns the async state updates.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadShops();
    }
  }, [distanceOrigin, shops.length, hasMore, typeId, sortBy, sortOrder, searchQuery]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const fillUnderfilledViewport = () => {
      if (
        shops.length === 0 ||
        !hasMore ||
        loadingRef.current ||
        el.scrollHeight > el.clientHeight + 1 ||
        underfillAttemptLength.current === shops.length
      ) return;

      underfillAttemptLength.current = shops.length;
      void loadShops();
    };

    const initialTimer = window.setTimeout(fillUnderfilledViewport, 0);
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', fillUnderfilledViewport);
      return () => {
        window.clearTimeout(initialTimer);
        window.removeEventListener('resize', fillUnderfilledViewport);
      };
    }

    const observer = new ResizeObserver(fillUnderfilledViewport);
    observer.observe(el);
    return () => {
      window.clearTimeout(initialTimer);
      observer.disconnect();
    };
  }, [hasMore, loadShops, shops.length]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop + offsetHeight + 1 > scrollHeight && !loadingRef.current && hasMore) {
      loadShops();
    }
  }, [loadShops, hasMore]);

  const handleSort = (field: string) => {
    setVisible(false);
    if (field === sortBy) {
      // toggle direction
      setSortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(field);
      setSortOrder('desc');
    }
    setShops([]);
    setCurrent(1);
    setHasMore(true);
  };

  const handleTypeChange = (t: ShopType) => {
    navigate(`/shop-list?type=${t.id}&name=${encodeURIComponent(t.name)}`);
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const listTitle = searchQuery
    ? t('shopList.searchResult', { query: searchQuery })
    : typeName
      ? t(`shopTypes.${typeName}`, typeName)
      : t('shopList.allCategories');

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <button type="button" className={styles.backBtn} onClick={handleBack} aria-label={t('auth.back')}>
          <LeftOutline fontSize={18} color="white" />
        </button>
        <div className={styles.title}>
          {listTitle}
        </div>
      </div>

      <div className={styles.contentShell}>
        <aside
          className={`${styles.categoryPanel} ${visible ? styles.categoryPanelOpen : ''}`}
          aria-label={t('shopList.allCategories')}
        >
          <div className={styles.categoryGrid}>
            {types.map((tp) => (
              <button
                type="button"
                key={tp.id}
                className={`${styles.typeOption} ${String(tp.id) === typeId ? styles.activeType : ''}`}
                onClick={() => {
                  handleTypeChange(tp);
                  setVisible(false);
                }}
              >
                <img
                  className={styles.typeIcon}
                  src={`/imgs${tp.icon.startsWith('/') ? tp.icon : `/${tp.icon}`}`}
                  alt={tp.name}
                />
                <span className={styles.typeName}>{t(`shopTypes.${tp.name}`, tp.name)}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className={styles.resultsPanel}>
          <div className={styles.sortBar}>
            <button
              type="button"
              className={`${styles.sortItem} ${styles.categoryToggle} ${visible ? styles.sortActive : ''}`}
              onClick={() => setVisible(!visible)}
              aria-expanded={visible}
            >
              <span>{typeName ? t(`shopTypes.${typeName}`, typeName) : t('shopList.allCategories')}</span>
              <span className={styles.sortArrow}>&#9660;</span>
            </button>
            {sortOptions.map((opt) => (
              <button
                type="button"
                key={opt.field}
                className={`${styles.sortItem} ${sortBy === opt.field ? styles.sortActive : ''}`}
                onClick={() => handleSort(opt.field)}
              >
                <span>{opt.label}</span>
                {sortBy === opt.field && (
                  <span className={styles.sortArrow}>
                    {sortOrder === 'desc' ? '▼' : '▲'}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className={styles.list} onScroll={handleScroll} ref={containerRef}>
            {!distanceOrigin ? (
              <div className={styles.loading}>{t('shopList.locating')}</div>
            ) : shops.length === 0 && !loading ? (
              <div className={styles.emptySearch}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
                <div style={{ fontSize: 15, color: '#999' }}>{t('shopList.noResults')}</div>
                <div style={{ fontSize: 13, color: '#ccc', marginTop: 4 }}>{t('shopList.tryDifferent')}</div>
              </div>
            ) : (
              shops.map((s) => (
                <ShopCard key={s.id} shop={s} />
              ))
            )}
            {loading && <div className={styles.loading}>{t('shopList.loading')}</div>}
          </div>
        </div>
      </div>

      {visible && <div className={styles.mask} onClick={() => setVisible(false)} />}
    </div>
  );
}
