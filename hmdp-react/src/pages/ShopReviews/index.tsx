import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Rate } from 'antd-mobile';
import { getShopById, getShopReviews } from '../../api/shop';
import styles from './ShopReviews.module.css';

interface ReviewData {
  id: number;
  userId: number;
  rating: number;
  content: string;
  images?: string;
  liked: number;
  nickName: string;
  icon: string;
  createTime: string;
}

export default function ShopReviews() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [shopName, setShopName] = useState(searchParams.get('name') || '全部评价');
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [current, setCurrent] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    getShopById(id).then((res) => {
      const data = res.data ?? res;
      if (data?.name) setShopName(data.name);
    }).catch(() => {});
  }, [id]);

  const loadReviews = useCallback(async () => {
    if (loading || !hasMore || !id) return;
    setLoading(true);
    try {
      const res = await getShopReviews(id, current);
      const list = res.data ?? [];
      if (!list || list.length === 0) {
        setHasMore(false);
      } else {
        setReviews((prev) => [...prev, ...list]);
        setCurrent((prev) => prev + 1);
      }
      if ((res as any).total && reviews.length + list.length >= (res as any).total) {
        setHasMore(false);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [id, current, loading, hasMore, reviews.length]);

  useEffect(() => {
    if (reviews.length === 0 && hasMore) {
      loadReviews();
    }
  }, [reviews.length]); // eslint-disable-line react-hooks/exhaustive-deps

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
        <div className={styles.title}>{shopName} - 评价</div>
        <div className={styles.placeholder} />
      </div>

      <div className={styles.scroll} onScroll={handleScroll} ref={containerRef}>
        {reviews.map((review) => {
          const reviewImages = review.images ? review.images.split(',') : [];
          return (
            <div className={styles.reviewBox} key={review.id}>
              <div className={styles.userIcon}>
                <img src={review.icon || '/imgs/icons/default-icon.png'} alt="" />
              </div>
              <div className={styles.reviewBody}>
                <div className={styles.userName}>{review.nickName}</div>
                <div className={styles.ratingRow}>
                  <Rate
                    readOnly
                    value={review.rating}
                    style={{ '--star-size': '10px', '--active-color': '#F63' }}
                  />
                </div>
                <div className={styles.content}>{review.content}</div>
                {reviewImages.length > 0 && (
                  <div className={styles.images}>
                    {reviewImages.map((img: string, idx: number) => (
                      <img key={idx} src={img} alt="" />
                    ))}
                  </div>
                )}
                <div className={styles.footer}>点赞{review.liked}</div>
              </div>
            </div>
          );
        })}
        {loading && <div className={styles.loading}>加载中...</div>}
        {!hasMore && reviews.length > 0 && (
          <div className={styles.loading}>— 已显示全部{reviews.length}条评价 —</div>
        )}
      </div>
    </div>
  );
}
