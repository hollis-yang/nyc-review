import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { getShopTypes, getShopsByType, getShopsByName } from '../../api/shop';
import ShopCard, { type ShopData } from '../../components/ShopCard';
import styles from './ShopList.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

const SORT_OPTIONS = [
  { label: '距离', field: '' },
  { label: '人气', field: 'comments' },
  { label: '评分', field: 'score' },
] as const;

export default function ShopList() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const typeId = searchParams.get('type') || '0';
  const typeName = searchParams.get('name') || '';
  const searchQuery = searchParams.get('query') || '';

  const [types, setTypes] = useState<ShopType[]>([]);
  const [shops, setShops] = useState<ShopData[]>([]);
  const [visible, setVisible] = useState(false);
  const [sortBy, setSortBy] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [current, setCurrent] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getShopTypes()
      .then((res) => setTypes(res.data ?? res))
      .catch(() => {});
  }, []);

  const loadShops = useCallback(async () => {
    if (loading || !hasMore) return;
    setLoading(true);
    try {
      const res = searchQuery
        ? await getShopsByName(searchQuery, current)
        : await getShopsByType({
            typeId,
            current,
            sortBy,
            sortOrder,
            x: 120.149993,
            y: 30.334229,
          });
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
      setLoading(false);
    }
  }, [typeId, current, sortBy, sortOrder, searchQuery, loading, hasMore]);

  useEffect(() => {
    setShops([]);
    setCurrent(1);
    setHasMore(true);
  }, [typeId, sortBy, sortOrder, searchQuery]);

  useEffect(() => {
    if (shops.length === 0 && hasMore) {
      loadShops();
    }
  }, [shops.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop + offsetHeight + 1 > scrollHeight && !loading && hasMore) {
      loadShops();
    }
  }, [loadShops, loading, hasMore]);

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

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.title}>
          {searchQuery ? `"${searchQuery}" 搜索结果` : typeName}
        </div>
      </div>

      <div className={styles.sortBar}>
        <div className={`${styles.sortItem} ${visible ? styles.sortActive : ''}`} onClick={() => setVisible(!visible)}>
          <span>{typeName || '全部分类'}</span>
          <span className={styles.sortArrow}>&#9660;</span>
        </div>
        {SORT_OPTIONS.map((opt) => (
          <div
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
          </div>
        ))}

        {visible && (
          <div className={styles.selectType}>
            {types.map((t) => (
              <div
                key={t.id}
                className={`${styles.typeOption} ${String(t.id) === typeId ? styles.activeType : ''}`}
                onClick={() => {
                  handleTypeChange(t);
                  setVisible(false);
                }}
              >
                <img
                  className={styles.typeIcon}
                  src={`/imgs/${t.icon}`}
                  alt={t.name}
                />
                <span className={styles.typeName}>{t.name}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {visible && (
        <div className={styles.mask} onClick={() => setVisible(false)} />
      )}

      <div className={styles.list} onScroll={handleScroll} ref={containerRef}>
        {shops.length === 0 && !loading ? (
          <div className={styles.emptySearch}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 15, color: '#999' }}>没有找到相关商户</div>
            <div style={{ fontSize: 13, color: '#ccc', marginTop: 4 }}>换个关键词试试吧</div>
          </div>
        ) : (
          shops.map((s) => (
            <ShopCard key={s.id} shop={s} />
          ))
        )}
        {loading && <div className={styles.loading}>加载中...</div>}
      </div>
    </div>
  );
}
