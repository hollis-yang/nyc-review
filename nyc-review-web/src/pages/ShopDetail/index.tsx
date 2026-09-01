import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LeftOutline, EnvironmentOutline, HeartFill, HeartOutline } from 'antd-mobile-icons';
import { Rate, Toast } from 'antd-mobile';
import { getShopById, getShopReviews, createShopReview } from '../../api/shop';
import { getVoucherList, seckillVoucher } from '../../api/voucher';
import { favoriteShop, getShopFavoriteStatus, unfavoriteShop } from '../../api/profile';
import VoucherCard, { type VoucherData } from '../../components/VoucherCard';
import ReviewThread, { type ReviewData } from '../../components/ReviewThread';
import MerchantVisual from '../../components/MerchantVisual';
import { useAuth } from '../../hooks/useAuth';
import { buildAuthEntryUrl } from '../../utils/authRedirect';
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
  return translate('voucher.temporarilyUnavailable');
}

export default function ShopDetail() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const seckillRequestsRef = useRef(new Set<number>());
  const shopRequestRef = useRef(0);
  const voucherRequestRef = useRef(0);
  const reviewRequestRef = useRef(0);
  const routeGenerationRef = useRef(0);
  const activeShopIdRef = useRef<string | null>(id ?? null);
  const reviewSubmittingRef = useRef<number | null>(null);
  const favoriteStatusRequestRef = useRef(0);
  const favoriteMutationRef = useRef<number | null>(null);
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [shopLoading, setShopLoading] = useState(true);
  const [shopLoadFailed, setShopLoadFailed] = useState(false);
  const [vouchers, setVouchers] = useState<VoucherData[]>([]);
  const [vouchersLoading, setVouchersLoading] = useState(true);
  const [vouchersLoadFailed, setVouchersLoadFailed] = useState(false);
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewsLoadFailed, setReviewsLoadFailed] = useState(false);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewContent, setReviewContent] = useState('');
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [favoriteStatus, setFavoriteStatus] = useState<{ shopId: string; value: boolean }>({
    shopId: '',
    value: false,
  });
  const [favoriteLoading, setFavoriteLoading] = useState(false);
  const [favoriteStatusLoading, setFavoriteStatusLoading] = useState(true);

  const loadShop = useCallback(async () => {
    const requestId = ++shopRequestRef.current;
    setShopLoading(true);
    setShopLoadFailed(false);
    if (!id) {
      setShop(null);
      setShopLoadFailed(true);
      setShopLoading(false);
      return;
    }
    try {
      const res = await getShopById(id);
      if (requestId !== shopRequestRef.current) return;
      const data = unwrapData<ShopApiData>(res);
      const images = Array.isArray(data.images)
        ? data.images
        : data.images?.split(',').filter(Boolean) ?? [];
      setShop({ ...data, images });
    } catch {
      if (requestId === shopRequestRef.current) {
        setShop(null);
        setShopLoadFailed(true);
      }
    } finally {
      if (requestId === shopRequestRef.current) setShopLoading(false);
    }
  }, [id]);

  const loadVouchers = useCallback(async () => {
    const requestId = ++voucherRequestRef.current;
    setVouchersLoading(true);
    setVouchersLoadFailed(false);
    if (!id) {
      setVouchers([]);
      setVouchersLoading(false);
      return;
    }
    try {
      const res = await getVoucherList(id);
      if (requestId === voucherRequestRef.current) {
        setVouchers((res.data ?? res) as VoucherData[]);
      }
    } catch {
      if (requestId === voucherRequestRef.current) setVouchersLoadFailed(true);
    } finally {
      if (requestId === voucherRequestRef.current) setVouchersLoading(false);
    }
  }, [id]);

  const loadReviews = useCallback(async () => {
    const requestId = ++reviewRequestRef.current;
    setReviewsLoading(true);
    setReviewsLoadFailed(false);
    if (!id) {
      setReviews([]);
      setReviewTotal(0);
      setReviewsLoading(false);
      return;
    }
    try {
      const res = await getShopReviews(id);
      if (requestId !== reviewRequestRef.current) return;
      const page = unwrapReviews(res);
      setReviews(page.records);
      setReviewTotal(page.total);
    } catch {
      if (requestId === reviewRequestRef.current) setReviewsLoadFailed(true);
    } finally {
      if (requestId === reviewRequestRef.current) setReviewsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const routeId = id;
    const generation = ++routeGenerationRef.current;
    activeShopIdRef.current = routeId ?? null;
    reviewSubmittingRef.current = null;
    favoriteMutationRef.current = null;
    seckillRequestsRef.current.clear();
    const timer = window.setTimeout(() => {
      setReviewContent('');
      setReviewRating(5);
      setReviewSubmitting(false);
      setFavoriteLoading(false);
      setFavoriteStatusLoading(true);
      void loadShop();
      void loadVouchers();
      void loadReviews();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      shopRequestRef.current += 1;
      voucherRequestRef.current += 1;
      reviewRequestRef.current += 1;
      if (routeGenerationRef.current === generation) routeGenerationRef.current += 1;
    };
  }, [id, loadReviews, loadShop, loadVouchers]);

  useEffect(() => {
    const routeId = id;
    const generation = routeGenerationRef.current;
    const requestId = ++favoriteStatusRequestRef.current;
    const timer = window.setTimeout(() => {
      if (activeShopIdRef.current !== routeId || routeGenerationRef.current !== generation) return;
      setFavoriteStatus({ shopId: routeId ?? '', value: false });
      if (!routeId || !isAuthenticated) {
        setFavoriteStatusLoading(false);
        return;
      }

      setFavoriteStatusLoading(true);
      void getShopFavoriteStatus(routeId)
        .then((response) => {
          if (
            favoriteStatusRequestRef.current === requestId
            && activeShopIdRef.current === routeId
            && routeGenerationRef.current === generation
          ) {
            setFavoriteStatus({ shopId: routeId, value: Boolean(response.data ?? response) });
          }
        })
        .catch(() => {
          if (
            favoriteStatusRequestRef.current === requestId
            && activeShopIdRef.current === routeId
            && routeGenerationRef.current === generation
          ) {
            Toast.show({ icon: 'fail', content: t('shopDetail.favoriteLoadFailed') });
          }
        })
        .finally(() => {
          if (
            favoriteStatusRequestRef.current === requestId
            && activeShopIdRef.current === routeId
            && routeGenerationRef.current === generation
          ) {
            setFavoriteStatusLoading(false);
          }
        });
    }, 0);

    return () => {
      window.clearTimeout(timer);
      if (favoriteStatusRequestRef.current === requestId) favoriteStatusRequestRef.current += 1;
    };
  }, [id, isAuthenticated, t]);

  const handleSeckill = async (voucherId: number) => {
    if (seckillRequestsRef.current.has(voucherId)) return;
    seckillRequestsRef.current.add(voucherId);
    try {
      const res = await seckillVoucher(voucherId);
      Toast.show({ icon: 'success', content: t('shopDetail.seckillSuccess', { id: res.data ?? res }) });
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: localizedSeckillError(err, t) });
    } finally {
      seckillRequestsRef.current.delete(voucherId);
    }
  };

  const refreshReviews = async (routeId: string, generation: number): Promise<boolean> => {
    const requestId = ++reviewRequestRef.current;
    const response = await getShopReviews(routeId);
    if (
      requestId !== reviewRequestRef.current
      || routeGenerationRef.current !== generation
      || activeShopIdRef.current !== routeId
    ) return false;
    const page = unwrapReviews(response);
    setReviews(page.records);
    setReviewTotal(page.total);
    setReviewsLoadFailed(false);
    return true;
  };

  const refreshShop = async (routeId: string, generation: number): Promise<boolean> => {
    const requestId = ++shopRequestRef.current;
    const shopResponse = await getShopById(routeId);
    if (
      requestId !== shopRequestRef.current
      || routeGenerationRef.current !== generation
      || activeShopIdRef.current !== routeId
    ) return false;
    const shopData = unwrapData<ShopApiData>(shopResponse);
    setShop({
      ...shopData,
      images: Array.isArray(shopData.images)
        ? shopData.images
        : shopData.images?.split(',').filter(Boolean) ?? [],
    });
    setShopLoadFailed(false);
    return true;
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
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (reviewSubmittingRef.current === generation) return;
    reviewSubmittingRef.current = generation;
    setReviewSubmitting(true);
    try {
      try {
        await createShopReview({ shopId: Number(routeId), rating: reviewRating, content: reviewContent.trim() });
      } catch {
        if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
          Toast.show({ icon: 'fail', content: t('shopDetail.reviewSubmitFailed') });
        }
        return;
      }
      if (routeGenerationRef.current !== generation || activeShopIdRef.current !== routeId) return;
      Toast.show({ icon: 'success', content: t('shopDetail.reviewSuccess') });
      setReviewContent('');
      setReviewRating(5);
      setReviewTotal((prev) => prev + 1);
      const refreshResults = await Promise.allSettled([
        refreshReviews(routeId, generation),
        refreshShop(routeId, generation),
      ]);
      if (
        routeGenerationRef.current === generation
        && activeShopIdRef.current === routeId
        && refreshResults.some((result) => result.status === 'rejected')
      ) {
        Toast.show({ icon: 'fail', content: t('shopDetail.reviewRefreshFailed') });
      }
    } finally {
      if (reviewSubmittingRef.current === generation) reviewSubmittingRef.current = null;
      if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
        setReviewSubmitting(false);
      }
    }
  };

  const handleFavorite = async () => {
    if (!id) return;
    if (!isAuthenticated) {
      Toast.show({ icon: 'fail', content: t('shopDetail.favoriteLoginRequired') });
      setTimeout(() => {
        navigate(buildAuthEntryUrl('/login', `/shop-detail/${id}`));
      }, 200);
      return;
    }
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (favoriteStatusLoading || favoriteMutationRef.current === generation) return;

    favoriteMutationRef.current = generation;
    favoriteStatusRequestRef.current += 1;
    setFavoriteLoading(true);
    try {
      const isFavorite = favoriteStatus.shopId === routeId && favoriteStatus.value;
      if (isFavorite) {
        await unfavoriteShop(routeId);
        if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
          setFavoriteStatus({ shopId: routeId, value: false });
          Toast.show({ icon: 'success', content: t('shopDetail.unfavoriteSuccess') });
        }
      } else {
        await favoriteShop(routeId);
        if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
          setFavoriteStatus({ shopId: routeId, value: true });
          Toast.show({ icon: 'success', content: t('shopDetail.favoriteSuccess') });
        }
      }
    } catch {
      if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('shopDetail.favoriteFailed') });
      }
    } finally {
      if (favoriteMutationRef.current === generation) favoriteMutationRef.current = null;
      if (routeGenerationRef.current === generation && activeShopIdRef.current === routeId) {
        setFavoriteLoading(false);
      }
    }
  };

  if (shopLoading || shopLoadFailed || !shop || String(shop.id) !== id) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <button type="button" className={styles.backBtn} onClick={handleBack} aria-label={t('auth.back')}>
            <LeftOutline fontSize={18} color="white" />
          </button>
          <div className={styles.title}>{t('shopDetail.title')}</div>
          <div className={styles.share} aria-hidden="true" />
        </div>
        <div className={styles.loadingFull} role={shopLoadFailed ? 'alert' : 'status'}>
          <span>{shopLoadFailed ? t('shopDetail.loadFailed') : t('shopDetail.loading')}</span>
          {shopLoadFailed && (
            <button type="button" onClick={() => void loadShop()}>{t('shopDetail.retry')}</button>
          )}
        </div>
      </div>
    );
  }

  const imageAssets: ShopImageAsset[] = shop.imageAssets?.length
    ? [...shop.imageAssets].sort((first, second) => (first.displayOrder ?? first.sortOrder ?? 0) - (second.displayOrder ?? second.sortOrder ?? 0))
    : shop.images.map((displayUrl, index) => ({ displayUrl, sortOrder: index, imageType: 'LEGACY' }));
  if (imageAssets.length === 0) imageAssets.push({ displayUrl: '', sortOrder: 0 });
  const displayReviewCount = shop.localReviewCount ?? shop.comments;
  const operational = !shop.businessStatus || shop.businessStatus === 'OPERATIONAL';
  const favorite = isAuthenticated && favoriteStatus.shopId === id && favoriteStatus.value;

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
          <div className={styles.shopTitleRow}>
            <div className={styles.shopTitle}>{shop.name}</div>
            <button
              type="button"
              className={`${styles.favoriteButton} ${favorite ? styles.favoriteButtonActive : ''}`}
              aria-pressed={favorite}
              disabled={favoriteLoading || favoriteStatusLoading}
              onClick={handleFavorite}
            >
              {favorite ? <HeartFill fontSize={17} /> : <HeartOutline fontSize={17} />}
              <span>{favorite ? t('shopDetail.favorited') : t('shopDetail.favorite')}</span>
            </button>
          </div>
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

        <div className={styles.lowerGrid}>
          <aside className={styles.supportColumn}>
            <div className={styles.divider} />

            <div className={styles.openTime}>
              <span>🕐</span>
              <div>{t('shopDetail.hours')}</div>
              <div style={{ flex: 1, fontSize: 12 }}>{shop.openHours || t('shopDetail.hoursUnavailable')}</div>
            </div>

            <div className={styles.divider} />

            {vouchersLoading && (
              <div className={styles.localStatus} role="status">{t('shopDetail.vouchersLoading')}</div>
            )}
            {!vouchersLoading && vouchersLoadFailed && (
              <div className={styles.localStatus} role="alert">
                <span>{t('shopDetail.vouchersLoadFailed')}</span>
                <button type="button" onClick={() => void loadVouchers()}>{t('shopDetail.retry')}</button>
              </div>
            )}
            {!vouchersLoading && !vouchersLoadFailed && vouchers.length > 0 && (
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
          </aside>

          <main className={styles.conversationColumn}>
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
              {reviewsLoading ? (
                <div className={styles.localStatus} role="status">{t('shopDetail.reviewsLoading')}</div>
              ) : reviewsLoadFailed ? (
                <div className={styles.localStatus} role="alert">
                  <span>{t('shopDetail.reviewsLoadFailed')}</span>
                  <button type="button" onClick={() => void loadReviews()}>{t('shopDetail.retry')}</button>
                </div>
              ) : (
                <div className={styles.commentList}>
                  {reviews.slice(0, 3).map((review) => (
                    <div className={styles.commentBox} key={review.id}>
                      <ReviewThread
                        review={review}
                        compact
                        shopId={shop.id}
                        onReplyCreated={async () => {
                          await refreshReviews(id, routeGenerationRef.current);
                        }}
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
              )}
            </div>

            {/* 写评价 */}
            <div className={styles.divider} />
            <div id="write-shop-review" className={styles.reviewComposer}>
              <div className={styles.reviewComposerTitle}>{t('shopDetail.writeReview')}</div>
              <div className={styles.reviewRatingRow}>
                <span>{t('shopDetail.rating')}</span>
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
              />
              <button
                type="button"
                className={styles.reviewSubmit}
                onClick={handleReviewSubmit}
                disabled={reviewSubmitting || !reviewContent.trim()}
                aria-busy={reviewSubmitting}
              >
                {reviewSubmitting ? t('shopDetail.submitting') : t('shopDetail.submit')}
              </button>
            </div>

            <div className={styles.divider} />
          </main>
        </div>
        <div className={styles.copyright}>copyright ©2021 nyc-review.com</div>
      </div>
    </div>
  );
}
