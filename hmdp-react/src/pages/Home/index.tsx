import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { SearchOutline } from 'antd-mobile-icons';
import { getShopTypes } from '../../api/shop';
import { getHotBlogs } from '../../api/blog';
import BlogCard, { type BlogData } from '../../components/BlogCard';
import FootBar from '../../components/FootBar';
import styles from './Home.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

export default function Home() {
  const navigate = useNavigate();
  const [types, setTypes] = useState<ShopType[]>([]);
  const [blogs, setBlogs] = useState<BlogData[]>([]);
  const [current, setCurrent] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const loadingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [searchText, setSearchText] = useState('');

  useEffect(() => {
    getShopTypes()
      .then((res) => {
        setTypes(res.data ?? res);
      })
      .catch(() => {});
  }, []);

  const loadBlogs = useCallback(async () => {
    if (loadingRef.current || !hasMore) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = await getHotBlogs(current);
      const data: BlogData[] = res.data ?? res;
      const enriched = data.map((b) => ({
        ...b,
        img: b.img || (b.images ? b.images.split(',')[0] : ''),
      }));
      if (enriched.length === 0) {
        setHasMore(false);
      } else {
        setBlogs((prev) => [...prev, ...enriched]);
        setCurrent((prev) => prev + 1);
      }
    } catch {
      // ignore
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [current, hasMore]);

  useEffect(() => {
    loadBlogs();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop + offsetHeight >= scrollHeight - 50 && !loadingRef.current && hasMore) {
      loadBlogs();
    }
  }, [loadBlogs, hasMore]);

  const handleLikeUpdate = (blogId: number, liked: number, isLike: boolean) => {
    setBlogs((prev) =>
      prev.map((b) => (b.id === blogId ? { ...b, liked, isLike } : b))
    );
  };

  return (
    <div className={styles.container}>
      <div className={styles.searchBar}>
        <div className={styles.cityBtn}>杭州</div>
        <div className={styles.searchInput}>
          <div className={styles.inputWrapper}>
            <SearchOutline fontSize={14} style={{ margin: '0 4px' }} />
            <input
              type="text"
              placeholder="请输入商户名、地点"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && searchText.trim()) {
                  navigate(`/shop-list?query=${encodeURIComponent(searchText.trim())}`);
                }
              }}
              style={{ border: 'none', outline: 'none', background: 'transparent', fontSize: 13, color: '#333', width: '100%' }}
            />
          </div>
        </div>
        <div className={styles.headerIcon} onClick={() => navigate('/profile')}>
          <svg viewBox="0 0 1024 1024" width="18" height="18" fill="white">
            <path d="M512 512c141.4 0 256-114.6 256-256S653.4 0 512 0 256 114.6 256 256s114.6 256 256 256zm0 128c-170.7 0-512 85.3-512 256v128h1024V896c0-170.7-341.3-256-512-256z" />
          </svg>
        </div>
      </div>

      <div className={styles.typeList}>
        {types.map((t) => (
          <div
            key={t.id}
            className={styles.typeBox}
            onClick={() =>
              navigate(`/shop-list?type=${t.id}&name=${encodeURIComponent(t.name)}`)
            }
          >
            <div className={styles.typeView}>
              <img src={`/imgs/${t.icon}`} alt="" />
            </div>
            <div className={styles.typeText}>{t.name}</div>
          </div>
        ))}
      </div>

      <div className={styles.blogList} onScroll={handleScroll} ref={containerRef}>
        {blogs.map((b) => (
          <BlogCard key={b.id} blog={b} onLikeUpdate={handleLikeUpdate} />
        ))}
        {loading && <div className={styles.loading}>加载中...</div>}
      </div>

      <FootBar activeBtn={1} />
    </div>
  );
}
