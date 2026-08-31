import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { SearchOutline } from 'antd-mobile-icons';
import { getShopTypes, getShopsByName } from '../../api/shop';
import { useTranslation } from 'react-i18next';
import { getHotBlogs } from '../../api/blog';
import BlogCard, { type BlogData } from '../../components/BlogCard';
import FootBar from '../../components/FootBar';
import styles from './Home.module.css';

interface ShopType {
  id: number;
  name: string;
  icon: string;
}

const shopTypeIconUrl = (icon?: string) => {
  if (!icon) return '/imgs/types/nyc-dining.svg';
  return `/imgs${icon.startsWith('/') ? icon : `/${icon}`}`;
};

export default function Home() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [types, setTypes] = useState<ShopType[]>([]);
  const [blogs, setBlogs] = useState<BlogData[]>([]);
  const [current, setCurrent] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const loadingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<{ id: number; name: string; typeId?: number }[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const getTypeInfo = (typeId: number) => types.find(t => t.id === typeId);

  const handleSearchInput = (value: string) => {
    setSearchText(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!value.trim()) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const res = await getShopsByName(value.trim());
        const data = res.data ?? res;
        const list = Array.isArray(data) ? data.slice(0, 5) : [];
        setSuggestions(list);
        setShowSuggestions(true);
      } catch { setSuggestions([]); }
    }, 300);
  };

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
    const timer = window.setTimeout(() => void loadBlogs(), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(() => {
      if (
        el.scrollHeight <= el.clientHeight + 1 &&
        !loadingRef.current &&
        hasMore
      ) {
        void loadBlogs();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loadBlogs]);

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
        <div className={styles.searchControls}>
          <div className={styles.cityBtn}>NYC</div>
          <div className={styles.searchInput}>
            <div className={styles.inputWrapper}>
              <SearchOutline fontSize={14} style={{ margin: '0 4px' }} />
              <input
                className={styles.searchField}
                type="text"
                placeholder={t('home.searchPlaceholder')}
                value={searchText}
                onChange={(e) => handleSearchInput(e.target.value)}
                onFocus={() => { if (suggestions.length > 0) setShowSuggestions(true); }}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && searchText.trim()) {
                    setShowSuggestions(false);
                    navigate(`/shop-list?query=${encodeURIComponent(searchText.trim())}`);
                  }
                }}
              />
            </div>
            {showSuggestions && suggestions.length > 0 && (
              <div className={styles.suggestions}>
                <div className={styles.suggestTitle}>{t('home.searchResults')}</div>
                {suggestions.map((s) => (
                  <div
                    key={s.id}
                    className={styles.suggestionItem}
                    onMouseDown={() => {
                      setSearchText(s.name);
                      setShowSuggestions(false);
                      navigate(`/shop-detail/${s.id}`);
                    }}
                  >
                    <img
                      className={styles.suggestIcon}
                      src={shopTypeIconUrl(s.typeId ? getTypeInfo(s.typeId)?.icon : undefined)}
                      alt=""
                    />
                    <div className={styles.suggestInfo}>
                      <div className={styles.suggestName}>{s.name}</div>
                      <div className={styles.suggestHint}>
                        {s.typeId && getTypeInfo(s.typeId)
                          ? t(`shopTypes.${getTypeInfo(s.typeId)!.name}`, getTypeInfo(s.typeId)!.name)
                          : t('home.viewDetails')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            className={styles.headerIcon}
            onClick={() => navigate('/profile')}
            aria-label={t('nav.profile')}
          >
            <svg viewBox="0 0 1024 1024" width="18" height="18" fill="white">
              <path d="M512 512c141.4 0 256-114.6 256-256S653.4 0 512 0 256 114.6 256 256s114.6 256 256 256zm0 128c-170.7 0-512 85.3-512 256v128h1024V896c0-170.7-341.3-256-512-256z" />
            </svg>
          </button>
        </div>
      </div>

      <div className={styles.typeList}>
        {types.map((tp) => (
          <button
            type="button"
            key={tp.id}
            className={styles.typeBox}
            onClick={() =>
              navigate(`/shop-list?type=${tp.id}&name=${encodeURIComponent(tp.name)}`)
            }
          >
            <div className={styles.typeView}>
              <img src={shopTypeIconUrl(tp.icon)} alt="" />
            </div>
            <div className={styles.typeText}>{t(`shopTypes.${tp.name}`, tp.name)}</div>
          </button>
        ))}
      </div>

      <div className={styles.blogList} onScroll={handleScroll} ref={containerRef}>
        {blogs.map((b) => (
          <BlogCard key={b.id} blog={b} onLikeUpdate={handleLikeUpdate} />
        ))}
        {loading && <div className={styles.loading}>{t('home.loading')}</div>}
      </div>

      <FootBar activeBtn={1} />
    </div>
  );
}
