import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LeftOutline, EnvironmentOutline } from 'antd-mobile-icons';
import { Rate, Toast } from 'antd-mobile';
import { getShopById, getShopReviews, createShopReview } from '../../api/shop';
import { translateReview } from '../../api/translate';
import { getVoucherList, seckillVoucher } from '../../api/voucher';
import VoucherCard, { type VoucherData } from '../../components/VoucherCard';
import styles from './ShopDetail.module.css';

interface ShopInfo {
  id: number;
  name: string;
  images: string[];
  score: number;
  comments: number;
  address: string;
  openHours: string;
  avgPrice?: number;
  sourceType?: 'MOCK' | 'NYC_OPEN_DATA' | 'LEGACY';
  sourceName?: string;
  sourceUrl?: string;
  sourceFetchedAt?: string;
  syntheticFields?: string[];
}

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

export default function ShopDetail() {
  const { id } = useParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const navigate = useNavigate();
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [vouchers, setVouchers] = useState<VoucherData[]>([]);
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewContent, setReviewContent] = useState('');
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewTL, setReviewTL] = useState<Record<number, string>>({});
  const [reviewTLLoading, setReviewTLLoading] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getShopById(id).then((res) => {
        const data = res.data ?? res;
        data.images = data.images ? data.images.split(',') : [];
        setShop(data);
      }),
      getVoucherList(id).then((res) => {
        setVouchers((res.data ?? res) as VoucherData[]);
      }),
      getShopReviews(id).then((res) => {
        const list = res.data ?? [];
        setReviews(list);
        setReviewTotal((res as any).total ?? list.length);
      }),
    ]).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t('shopDetail.notFound'));
    });
  }, [id]);

  const handleSeckill = async (voucherId: number) => {
    try {
      const res = await seckillVoucher(voucherId);
      Toast.show({ icon: 'success', content: t('shopDetail.seckillSuccess', { id: res.data ?? res }) });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleShare = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try { await navigator.share({ title: shop?.name ?? t('shopDetail.notFound'), url }); } catch {}
    } else {
      await navigator.clipboard.writeText(url);
      Toast.show({ icon: 'success', content: t('shopDetail.linkCopied') });
    }
  };

  const handleReviewSubmit = async () => {
    if (!reviewContent.trim() || !id) return;
    setReviewSubmitting(true);
    try {
      await createShopReview({ shopId: Number(id), rating: reviewRating, content: reviewContent.trim() });
      Toast.show({ icon: 'success', content: t('shopDetail.reviewSuccess') });
      setReviewContent('');
      setReviewRating(5);
      setReviewTotal((prev) => prev + 1);
      // refresh reviews
      const res = await getShopReviews(id);
      const records = res.data?.records ?? res.data ?? res;
      setReviews(Array.isArray(records) ? records : []);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    } finally {
      setReviewSubmitting(false);
    }
  };

  const handleTranslateReview = async (reviewId: number) => {
    if (reviewTLLoading[reviewId]) return;
    if (reviewTL[reviewId]) {
      setReviewTL((previous) => {
        const next = { ...previous };
        delete next[reviewId];
        return next;
      });
      return;
    }

    setReviewTLLoading((previous) => ({ ...previous, [reviewId]: true }));
    try {
      const response = await translateReview(reviewId, 'zh-CN');
      setReviewTL((previous) => ({
        ...previous,
        [reviewId]: String(response.data ?? response),
      }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      Toast.show({
        icon: 'fail',
        content: message === 'Please sign in first'
          ? t('shopDetail.translationLoginRequired')
          : t('shopDetail.translationFailed'),
      });
    } finally {
      setReviewTLLoading((previous) => ({ ...previous, [reviewId]: false }));
    }
  };

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={18} color="white" />
          </div>
          <div className={styles.title}></div>
        </div>
        <div className={styles.loadingFull}>{error}</div>
      </div>
    );
  }

  if (!shop) {
    return <div className={styles.loadingFull}>{t('shopDetail.loading')}</div>;
  }

  const publicSourceBacked = shop.sourceType === 'NYC_OPEN_DATA';

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.title}>{shop.name}</div>
        <div className={styles.share} onClick={handleShare}>...</div>
      </div>
      <div className={styles.scroll}>
        <div className={styles.infoBox}>
          <div className={styles.shopTitle}>{shop.name}</div>
          <div className={styles.provenanceRow}>
            {publicSourceBacked && shop.sourceUrl ? (
              <a href={shop.sourceUrl} target="_blank" rel="noreferrer" className={styles.publicSourceBadge}>
                {t('shopDetail.nycOpenData')}
              </a>
            ) : (
              <span className={styles.mockSourceBadge}>{t('shopDetail.mockData')}</span>
            )}
            <span>{publicSourceBacked ? t('shopDetail.publicIdentity') : t('shopDetail.fullySynthetic')}</span>
          </div>
          <div className={styles.provenanceNote}>
            {publicSourceBacked ? t('shopDetail.hybridDataNotice') : t('shopDetail.mockDataNotice')}
          </div>
          <div className={styles.shopRate}>
            <Rate
              readOnly
              value={shop.score / 10}
              style={{ '--star-size': '14px', '--active-color': '#F63' }}
            />
            <span style={{ color: '#F63', fontSize: 12, marginLeft: 6 }}>
              {shop.score / 10}{t('shopCard.score')}
            </span>
            <span style={{ color: '#999', fontSize: 11, marginLeft: 4 }}>
              {shop.comments}{t('shopCard.comments')}
            </span>
          </div>
          <div className={styles.shopImages}>
            {shop.images.map((s: string, i: number) => (
              <div key={i}>
                <img src={s} alt="" />
              </div>
            ))}
          </div>
          <div className={styles.shopAddress}>
            <EnvironmentOutline fontSize={14} />
            <span style={{ marginLeft: 4 }}>{shop.address}</span>
            <span style={{ margin: '0 8px', color: '#e1e2e3' }}>|</span>
            <span style={{ fontSize: 12, cursor: 'pointer' }} onClick={() => {
              const addr = encodeURIComponent(shop?.address ?? '');
              window.open(`https://maps.apple.com/?q=${addr}`, '_blank');
            }}>{t('shopDetail.navigate')}</span>
          </div>
        </div>

        <div className={styles.divider} />

        <div className={styles.openTime}>
          <span>🕐</span>
          <div>{t('shopDetail.hours')}</div>
          <div style={{ flex: 1, fontSize: 12 }}>{shop.openHours}</div>
        </div>

        <div className={styles.divider} />

        {vouchers.length > 0 && (
          <>
            <div className={styles.voucherSection}>
              <div>
                <span className={styles.voucherIcon}>%</span>
                <span style={{ fontWeight: 'bold' }}>{t('shopDetail.vouchers')}</span>
              </div>
              {vouchers.map((v) => (
                <VoucherCard key={v.id} voucher={v} onSeckill={handleSeckill} />
              ))}
            </div>
            <div className={styles.divider} />
          </>
        )}

        <div className={styles.comments}>
          <div className={styles.commentsHead}>
            <div>{t('shopDetail.reviews')} <span>（{reviewTotal || shop.comments}）</span></div>
            {reviewTotal > 3 && (
              <div style={{ cursor: 'pointer' }} onClick={() => navigate(`/shop-reviews/${id}?name=${encodeURIComponent(shop.name)}`)}>&gt;</div>
            )}
          </div>
          <div className={styles.syntheticReviewNotice}>{t('shopDetail.syntheticReviewNotice')}</div>
          <div className={styles.commentList}>
            {reviews.slice(0, 3).map((review) => {
              const reviewImages = review.images ? review.images.split(',') : [];
              return (
                <div className={styles.commentBox} key={review.id}>
                  <div className={styles.commentIcon}>
                    <img src={review.icon || '/imgs/icons/default-icon.png'} alt="" />
                  </div>
                  <div className={styles.commentInfo}>
                    <div className={styles.commentUser}>{review.nickName}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Rate
                        readOnly
                        value={review.rating}
                        style={{ '--star-size': '10px', '--active-color': '#F63' }}
                      />
                    </div>
                    <div style={{ padding: '5px 0', fontSize: 13 }}>{review.content}</div>
                    {reviewTL[review.id] && (
                      <div style={{ background: '#f0f7ff', padding: '6px 8px', borderRadius: 6, margin: '4px 0', fontSize: 12, color: '#555' }}>
                        {reviewTL[review.id]}
                      </div>
                    )}
                    {isChinese && (
                      <button
                        type="button"
                        className={styles.translationButton}
                        disabled={reviewTLLoading[review.id]}
                        onClick={() => handleTranslateReview(review.id)}
                      >
                        {reviewTLLoading[review.id]
                          ? t('shopDetail.translatingDeepSeek')
                          : reviewTL[review.id]
                            ? t('shopDetail.hideTranslation')
                            : `✦ ${t('shopDetail.deepSeekTranslate')}`}
                      </button>
                    )}
                    {reviewImages.length > 0 && (
                      <div className={styles.commentImages}>
                        {reviewImages.map((img: string, idx: number) => (
                          <img key={idx} src={img} alt="" />
                        ))}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: '#999' }}>
                      {t('shopDetail.like', { n: review.liked })}
                    </div>
                  </div>
                </div>
              );
            })}
            {reviewTotal > 3 && (
              <div className={styles.viewAll} onClick={() => navigate(`/shop-reviews/${id}?name=${encodeURIComponent(shop.name)}`)}>
                <div>{t('shopDetail.viewAll', { n: reviewTotal })}</div>
                <div>&gt;</div>
              </div>
            )}
          </div>
        </div>

        {/* 写评价 */}
        <div className={styles.divider} />
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>{t('shopDetail.writeReview')}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: '#666' }}>{t('shopDetail.rating')}</span>
            <Rate
              value={reviewRating}
              onChange={setReviewRating}
              style={{ '--star-size': '20px', '--active-color': '#F63' }}
            />
          </div>
          <textarea
            placeholder={t('shopDetail.reviewPlaceholder')}
            value={reviewContent}
            onChange={(e) => setReviewContent(e.target.value)}
            rows={3}
            maxLength={500}
            style={{
              width: '100%', padding: '8px 12px', border: '1px solid #eee',
              borderRadius: 8, fontSize: 13, resize: 'vertical', boxSizing: 'border-box',
            }}
          />
          <div
            onClick={handleReviewSubmit}
            style={{
              marginTop: 8, textAlign: 'center', background: 'var(--color-primary-gradient)',
              color: '#fff', padding: '8px 0', borderRadius: 20, fontSize: 14,
              cursor: reviewContent.trim() && !reviewSubmitting ? 'pointer' : 'default',
              opacity: reviewContent.trim() && !reviewSubmitting ? 1 : 0.5,
            }}
          >
            {reviewSubmitting ? t('shopDetail.submitting') : t('shopDetail.submit')}
          </div>
        </div>

        <div className={styles.divider} />
        <div className={styles.copyright}>copyright ©2021 hmdp.com</div>
      </div>
    </div>
  );
}
