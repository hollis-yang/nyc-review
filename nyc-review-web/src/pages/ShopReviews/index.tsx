import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { useTranslation } from 'react-i18next';
import { getShopById, getShopReviews } from '../../api/shop';
import ReviewThread, { type ReviewData } from '../../components/ReviewThread';
import styles from './ShopReviews.module.css';

interface ApiEnvelope<T> {
  data?: T;
  total?: number;
}

function unwrapReviews(response: unknown): { records: ReviewData[]; total: number } {
  const envelope = response as ApiEnvelope<unknown>;
  const records = Array.isArray(envelope?.data) ? envelope.data as ReviewData[] : [];
  return {
    records,
    total: typeof envelope?.total === 'number' ? envelope.total : records.length,
  };
}

export default function ShopReviews() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [shopName, setShopName] = useState(searchParams.get('name') || t('shopReviews.allReviews'));
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [current, setCurrent] = useState(2);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;
    Promise.all([getShopById(id), getShopReviews(id, 1)])
      .then(([shopResponse, reviewResponse]) => {
        if (!active) return;
        const shopEnvelope = shopResponse as unknown as ApiEnvelope<{ name?: string }>;
        const shop = shopEnvelope.data ?? shopResponse as unknown as { name?: string };
        if (shop?.name) setShopName(shop.name);
        const page = unwrapReviews(reviewResponse);
        setReviews(page.records);
        setCurrent(2);
        setHasMore(page.records.length > 0 && page.records.length < page.total);
      })
      .catch(() => {
        if (active) setHasMore(false);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);

  const loadReviews = useCallback(async () => {
    if (loading || !hasMore || !id) return;
    setLoading(true);
    try {
      const res = await getShopReviews(id, current);
      const page = unwrapReviews(res);
      if (page.records.length === 0) {
        setHasMore(false);
      } else {
        const nextCount = reviews.length + page.records.length;
        setReviews((prev) => [...prev, ...page.records]);
        setHasMore(nextCount < page.total);
        setCurrent((prev) => prev + 1);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [id, current, loading, hasMore, reviews.length]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop + offsetHeight + 1 > scrollHeight && !loading && hasMore) {
      loadReviews();
    }
  }, [loadReviews, loading, hasMore]);

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
        <div className={styles.title}>{t('shopReviews.title', { name: shopName })}</div>
        <div className={styles.placeholder} />
      </div>

      <div className={styles.scroll} onScroll={handleScroll} ref={containerRef}>
        {reviews.map((review) => (
          <div className={styles.reviewBox} key={review.id}>
            <ReviewThread review={review} />
          </div>
        ))}
        {loading && <div className={styles.loading}>{t('shopReviews.loading')}</div>}
        {!hasMore && reviews.length > 0 && (
          <div className={styles.loading}>{t('shopReviews.end', { n: reviews.length })}</div>
        )}
      </div>
    </div>
  );
}
