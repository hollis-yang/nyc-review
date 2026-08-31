import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LeftOutline, EnvironmentOutline } from 'antd-mobile-icons';
import { Rate, Toast } from 'antd-mobile';
import { getShopById, getShopReviews, createShopReview } from '../../api/shop';
import { getVoucherList, seckillVoucher } from '../../api/voucher';
import VoucherCard, { type VoucherData } from '../../components/VoucherCard';
import ReviewThread, { type ReviewData } from '../../components/ReviewThread';
import MerchantVisual from '../../components/MerchantVisual';
import styles from './ShopDetail.module.css';

interface ShopImageAsset {
  id?: number;
  displayUrl: string;
  sourcePageUrl?: string;
  sourceName?: string;
  authorName?: string;
  licenseName?: string;
  licenseUrl?: string;
  imageType?: string;
  matchType?: string;
  isPrimary?: boolean;
  displayOrder?: number;
  cachedUrl?: string;
  sortOrder?: number;
}

interface ShopInfo {
  id: number;
  name: string;
  images: string[];
  score?: number | null;
  comments: number;
  localReviewCount?: number | null;
  ratingCount?: number | null;
  externalRatingCount?: number | null;
  address: string;
  openHours?: string;
  avgPrice?: number;
  priceLevel?: number;
  priceRangeText?: string;
  phone?: string;
  website?: string;
  reservationUrl?: string;
  businessStatus?: string;
  healthGrade?: string;
  sourceType?: string;
  sourceName?: string;
  sourceUrl?: string;
  sourceFetchedAt?: string;
  syntheticFields?: string[];
  sourceLicense?: string;
  sourceAttribution?: string;
  derivedFields?: string[];
  imageAssets?: ShopImageAsset[];
  typeId?: number;
  subcategoryId?: number;
}

interface ApiEnvelope<T> {
  data?: T;
  total?: number;
}

type ShopApiData = Omit<ShopInfo, 'images'> & { images?: string | string[] };

function unwrapData<T>(response: unknown): T {
  const envelope = response as ApiEnvelope<T>;
  return (envelope?.data ?? response) as T;
}

function unwrapReviews(response: unknown): { records: ReviewData[]; total: number } {
  const envelope = response as ApiEnvelope<unknown>;
  const records = Array.isArray(envelope?.data) ? envelope.data as ReviewData[] : [];
  return {
    records,
    total: typeof envelope?.total === 'number' ? envelope.total : records.length,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function localizedSeckillError(error: unknown, translate: (key: string) => string): string {
  const message = errorMessage(error);
  const normalized = message.toLowerCase();
  if (message.includes('库存不足') || normalized.includes('out of stock')) {
    return translate('voucher.outOfStock');
  }
  if (message.includes('不能重复购买') || normalized.includes('already purchased')) {
    return translate('voucher.alreadyPurchased');
  }
  if (normalized.includes('not found')) {
    return translate('voucher.notFound');
  }
  if (normalized.includes('temporarily unavailable')) {
    return translate('voucher.temporarilyUnavailable');
  }
  return message;
}

export default function ShopDetail() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [vouchers, setVouchers] = useState<VoucherData[]>([]);
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewContent, setReviewContent] = useState('');
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getShopById(id).then((res) => {
        const data = unwrapData<ShopApiData>(res);
        const images = Array.isArray(data.images)
          ? data.images
          : data.images?.split(',').filter(Boolean) ?? [];
        setShop({ ...data, images });
      }),
      getVoucherList(id).then((res) => {
        setVouchers((res.data ?? res) as VoucherData[]);
      }),
      getShopReviews(id).then((res) => {
        const page = unwrapReviews(res);
        setReviews(page.records);
        setReviewTotal(page.total);
      }),
    ]).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t('shopDetail.notFound'));
    });
  }, [id, t]);

  const handleSeckill = async (voucherId: number) => {
    try {
      const res = await seckillVoucher(voucherId);
      Toast.show({ icon: 'success', content: t('shopDetail.seckillSuccess', { id: res.data ?? res }) });
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: localizedSeckillError(err, t) });
    }
  };

  const refreshReviews = async () => {
    if (!id) return;
    const response = await getShopReviews(id);
    const page = unwrapReviews(response);
    setReviews(page.records);
    setReviewTotal(page.total);
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleShare = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: shop?.name ?? t('shopDetail.notFound'), url });
      } catch {
        // Closing the native share sheet is not an application error.
      }
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
      await refreshReviews();
      const shopResponse = await getShopById(id);
      const shopData = unwrapData<ShopApiData>(shopResponse);
      setShop({
        ...shopData,
        images: Array.isArray(shopData.images)
          ? shopData.images
          : shopData.images?.split(',').filter(Boolean) ?? [],
      });
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: errorMessage(err) });
    } finally {
      setReviewSubmitting(false);
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

  const imageAssets: ShopImageAsset[] = shop.imageAssets?.length
    ? [...shop.imageAssets].sort((first, second) => (first.displayOrder ?? first.sortOrder ?? 0) - (second.displayOrder ?? second.sortOrder ?? 0))
    : shop.images.map((displayUrl, index) => ({ displayUrl, sortOrder: index, imageType: 'LEGACY' }));
  if (imageAssets.length === 0) imageAssets.push({ displayUrl: '', sortOrder: 0 });
  const displayReviewCount = shop.localReviewCount ?? shop.comments;
  const operational = !shop.businessStatus || shop.businessStatus === 'OPERATIONAL';

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
          <div className={styles.shopRate}>
            {shop.score != null ? (
              <>
                <Rate
                  readOnly
                  value={shop.score / 10}
                  style={{ '--star-size': '14px', '--active-color': '#F63' }}
                />
                <span style={{ color: '#F63', fontSize: 12, marginLeft: 6 }}>
                  {shop.score / 10}{t('shopCard.score')}
                </span>
              </>
            ) : (
              <span style={{ color: '#999', fontSize: 12 }}>{t('shopCard.ratingUnavailable')}</span>
            )}
            <span style={{ color: '#999', fontSize: 11, marginLeft: 4 }}>
              {displayReviewCount}{t('shopCard.comments')}
            </span>
            {shop.avgPrice != null && (
              <span style={{ color: '#666', fontSize: 11, marginLeft: 6 }}>
                ${shop.avgPrice}{t('shopCard.perPerson')}
              </span>
            )}
          </div>
          <div className={styles.shopImages}>
            {imageAssets.map((asset, index) => (
              <div key={`${asset.displayUrl}-${index}`} className={styles.shopImageAsset}>
                <MerchantVisual
                  shopId={shop.id}
                  name={shop.name}
                  typeId={shop.typeId}
                  images={asset.cachedUrl || asset.displayUrl}
                  alt={`${shop.name} ${index + 1}`}
                  loading="lazy"
                />
              </div>
            ))}
          </div>
          <div className={styles.quickFacts}>
            <span className={operational ? styles.openBadge : styles.closedBadge}>
              {operational ? t('shopDetail.operational') : t('shopDetail.notOperational')}
            </span>
            {shop.priceRangeText && <span>{shop.priceRangeText}</span>}
            {shop.healthGrade && <span>{t('shopDetail.healthGrade', { grade: shop.healthGrade })}</span>}
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
          {(shop.phone || shop.website || shop.reservationUrl) && (
            <div className={styles.contactDetails}>
              {shop.phone && (
                <div className={styles.contactRow}>
                  <span className={styles.contactLabel}>{t('shopDetail.phone')}</span>
                  <a className={styles.contactValue} href={`tel:${shop.phone}`}>{shop.phone}</a>
                </div>
              )}
              {shop.website && (
                <div className={styles.contactRow}>
                  <span className={styles.contactLabel}>{t('shopDetail.website')}</span>
                  <a
                    className={styles.contactValue}
                    href={shop.website}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {shop.website}
                  </a>
                </div>
              )}
              {shop.reservationUrl && (
                <a
                  className={styles.reserveAction}
                  href={shop.reservationUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t('shopDetail.reserve')}
                </a>
              )}
            </div>
          )}
        </div>

        <div className={styles.divider} />

        <div className={styles.openTime}>
          <span>🕐</span>
          <div>{t('shopDetail.hours')}</div>
          <div style={{ flex: 1, fontSize: 12 }}>{shop.openHours || t('shopDetail.hoursUnavailable')}</div>
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
            <div>{t('shopDetail.reviews')} <span>（{reviewTotal}）</span></div>
            <div className={styles.reviewHeadActions}>
              <button type="button" onClick={() => document.getElementById('write-shop-review')?.scrollIntoView({ behavior: 'smooth' })}>
                {t('shopDetail.writeReview')}
              </button>
              {reviewTotal > 3 && (
                <button type="button" onClick={() => navigate(`/shop-reviews/${id}?name=${encodeURIComponent(shop.name)}`)}>&gt;</button>
              )}
            </div>
          </div>
          <div className={styles.commentList}>
            {reviews.slice(0, 3).map((review) => (
              <div className={styles.commentBox} key={review.id}>
                <ReviewThread
                  review={review}
                  compact
                  shopId={shop.id}
                  onReplyCreated={refreshReviews}
                />
              </div>
            ))}
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
        <div id="write-shop-review" style={{ padding: '12px 14px', scrollMarginTop: 56 }}>
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
        <div className={styles.copyright}>copyright ©2021 nyc-review.com</div>
      </div>
    </div>
  );
}
