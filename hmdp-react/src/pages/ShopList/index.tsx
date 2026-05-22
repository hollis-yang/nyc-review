import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LeftOutline, SearchOutline } from 'antd-mobile-icons';
import { getShopTypes, getShopsByType } from '../../api/shop';
import ShopCard, { type ShopData } from '../../components/ShopCard';
import styles from './ShopList.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

export default function ShopList() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const typeId = searchParams.get('type') || '0';
  const typeName = searchParams.get('name') || '';

  const [types, setTypes] = useState<ShopType[]>([]);
  const [shops, setShops] = useState<ShopData[]>([]);
  const [visible, setVisible] = useState(false);
  const [sortBy, setSortBy] = useState('');
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
      const res = await getShopsByType({
        typeId,
        current,
        sortBy,
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
  }, [typeId, current, sortBy, loading, hasMore]);

  useEffect(() => {
    setShops([]);
    setCurrent(1);
    setHasMore(true);
  }, [typeId, sortBy]);

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
    setSortBy(field);
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
        <div className={styles.title}>{typeName}</div>
        <div className={styles.search}>
          <SearchOutline fontSize={16} />
        </div>
      </div>

      <div className={styles.sortBar}>
        <div className={styles.sortItem} onClick={() => setVisible(!visible)}>
          <span>{typeName}</span>
          <span style={{ fontSize: 10, marginLeft: 2 }}>&#9660;</span>
        </div>
        <div className={styles.sortItem} onClick={() => handleSort('')}>
          距离
        </div>
        <div className={styles.sortItem} onClick={() => handleSort('comments')}>
          人气
        </div>
        <div className={styles.sortItem} onClick={() => handleSort('score')}>
          评分
        </div>
      </div>

      <div className={styles.selectType} style={{ display: visible ? 'block' : 'none' }}>
        {types.map((t) => (
          <div
            key={t.id}
            className={`${styles.typeOption} ${String(t.id) === typeId ? styles.activeType : ''}`}
            onClick={() => {
              handleTypeChange(t);
              setVisible(false);
            }}
          >
            {t.name}
          </div>
        ))}
      </div>

      <div className={styles.list} onScroll={handleScroll} ref={containerRef}>
        {shops.map((s) => (
          <ShopCard key={s.id} shop={s} />
        ))}
        {loading && <div className={styles.loading}>加载中...</div>}
      </div>
    </div>
  );
}
