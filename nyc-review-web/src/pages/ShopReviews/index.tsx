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

type ReviewLoadError = 'initial' | 'pagination' | null;

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
  const requestedShopName = searchParams.get('name') || t('shopReviews.allReviews');
  const [resolvedShopName, setResolvedShopName] = useState<{ shopId: string; name: string } | null>(null);
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [current, setCurrent] = useState(2);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const [loadError, setLoadError] = useState<ReviewLoadError>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(true);
  const requestSequence = useRef(0);
  const underfillAttemptLength = useRef<number | null>(null);

  const loadInitialReviews = useCallback(async () => {
    if (!id) return;
    const sequence = ++requestSequence.current;
    loadingRef.current = true;
    underfillAttemptLength.current = null;
    // Clear the previous route's rows before its replacement request resolves.
    setReviews([]);
    setResolvedShopName(null);
    setCurrent(2);
    setHasMore(true);
    setLoadError(null);
    setLoading(true);
    try {
      const [shopResult, reviewResult] = await Promise.allSettled([
        getShopById(id),
        getShopReviews(id, 1),
      ]);
      if (sequence !== requestSequence.current) return;
      if (shopResult.status === 'fulfilled') {
        const shopResponse = shopResult.value;
        const shopEnvelope = shopResponse as unknown as ApiEnvelope<{ name?: string }>;
        const shop = shopEnvelope.data ?? shopResponse as unknown as { name?: string };
        if (shop?.name) setResolvedShopName({ shopId: id, name: shop.name });
      }
      if (reviewResult.status === 'rejected') throw reviewResult.reason;
      const page = unwrapReviews(reviewResult.value);
      setReviews(page.records);
      setCurrent(2);
      setHasMore(page.records.length > 0 && page.records.length < page.total);
    } catch {
      if (sequence !== requestSequence.current) return;
      setHasMore(false);
      setLoadError('initial');
    } finally {
      if (sequence === requestSequence.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [id]);

  useEffect(() => {
    // Route changes intentionally reset the visible collection before fetching its replacement.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadInitialReviews();
    return () => {
      requestSequence.current += 1;
    };
  }, [loadInitialReviews]);

  const loadReviews = useCallback(async () => {
    if (loadingRef.current || !hasMore || !id) return;
    const sequence = ++requestSequence.current;
    loadingRef.current = true;
    setLoadError(null);
    setLoading(true);
    try {
      const res = await getShopReviews(id, current);
      if (sequence !== requestSequence.current) return;
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
      if (sequence === requestSequence.current) {
        underfillAttemptLength.current = null;
        setLoadError('pagination');
      }
    } finally {
      if (sequence === requestSequence.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [id, current, hasMore, reviews.length]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const fillUnderfilledViewport = () => {
      if (
        !window.matchMedia('(min-width: 1024px)').matches ||
        reviews.length === 0 ||
        !hasMore ||
        loadingRef.current ||
        el.scrollHeight > el.clientHeight + 1 ||
        underfillAttemptLength.current === reviews.length
      ) return;

      underfillAttemptLength.current = reviews.length;
      void loadReviews();
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
  }, [hasMore, loadReviews, reviews.length]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop + offsetHeight + 1 > scrollHeight && !loadingRef.current && hasMore) {
      loadReviews();
    }
  }, [loadReviews, hasMore]);

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const refreshVisibleReviews = useCallback(async () => {
    if (!id) return;
    const sequence = ++requestSequence.current;
    loadingRef.current = true;
    setLoadError(null);
    setLoading(true);
    const loadedPages = Math.max(1, current - 1);
    try {
      const responses = await Promise.all(
        Array.from({ length: loadedPages }, (_, index) => getShopReviews(id, index + 1))
      );
      if (sequence !== requestSequence.current) return;
      const pages = responses.map(unwrapReviews);
      const records = pages.flatMap((page) => page.records);
      const total = pages[0]?.total ?? records.length;
      setReviews(records);
      setHasMore(records.length < total);
    } catch (error) {
      if (sequence === requestSequence.current) setLoadError('pagination');
      throw error;
    } finally {
      if (sequence === requestSequence.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [current, id]);

  const shopName = resolvedShopName && resolvedShopName.shopId === id
    ? resolvedShopName.name
    : requestedShopName;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <button type="button" className={styles.backBtn} onClick={handleBack} aria-label={t('auth.back')}>
          <LeftOutline fontSize={18} color="white" />
        </button>
        <div className={styles.title}>{t('shopReviews.title', { name: shopName })}</div>
        <div className={styles.placeholder} />
      </div>

      <div className={styles.scroll} onScroll={handleScroll} ref={containerRef}>
        {loadError === 'initial' && (
          <div className={styles.statePanel} role="alert">
            <div className={styles.stateIcon} aria-hidden="true">!</div>
            <strong>{t('shopReviews.loadFailed')}</strong>
            <button type="button" className={styles.retryButton} onClick={loadInitialReviews}>
              {t('shopReviews.retry')}
            </button>
          </div>
        )}
        {!loading && loadError === null && reviews.length === 0 && (
          <div className={styles.statePanel} role="status">
            <div className={styles.emptyIcon} aria-hidden="true">☆</div>
            <strong>{t('shopReviews.empty')}</strong>
            <span>{t('shopReviews.emptyHint')}</span>
          </div>
        )}
        {reviews.map((review) => (
          <div className={styles.reviewBox} key={review.id}>
            <ReviewThread
              review={review}
              shopId={Number(id)}
              onReplyCreated={refreshVisibleReviews}
            />
          </div>
        ))}
        {loading && <div className={styles.loading}>{t('shopReviews.loading')}</div>}
        {loadError === 'pagination' && reviews.length > 0 && (
          <div className={styles.paginationError} role="alert">
            <span>{t('shopReviews.moreFailed')}</span>
            <button type="button" className={styles.retryButton} onClick={loadReviews}>
              {t('shopReviews.retry')}
            </button>
          </div>
        )}
        {!hasMore && loadError === null && reviews.length > 0 && (
          <div className={styles.loading}>{t('shopReviews.end', { n: reviews.length })}</div>
        )}
      </div>
    </div>
  );
}
