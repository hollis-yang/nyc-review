import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Rate } from 'antd-mobile';
import { EnvironmentOutline } from 'antd-mobile-icons';
import MerchantVisual from '../MerchantVisual';
import styles from './ShopCard.module.css';

export interface ShopData {
  id: number;
  name: string;
  images: string;
  score?: number | null;
  comments: number;
  localReviewCount?: number | null;
  ratingCount?: number | null;
  externalRatingCount?: number | null;
  area: string;
  distance?: number;
  avgPrice?: number | null;
  priceRangeText?: string | null;
  businessStatus?: string;
  address: string;
  sourceType?: string;
  syntheticFields?: string[];
  typeId?: number;
  subcategoryId?: number;
}

interface ShopCardProps {
  shop: ShopData;
}

export default function ShopCard({ shop }: ShopCardProps) {
  const { t } = useTranslation();
  const displayReviewCount = shop.localReviewCount ?? shop.comments;

  const formatDistance = (d: number) => {
    if (d < 1000) return d.toFixed(1) + 'm';
    return (d / 1000).toFixed(1) + 'km';
  };

  return (
    <Link
      to={`/shop-detail/${shop.id}`}
      className={styles.box}
    >
      <div className={styles.img}>
        <MerchantVisual
          shopId={shop.id}
          name={shop.name}
          typeId={shop.typeId}
          images={shop.images}
          alt={shop.name}
          loading="lazy"
        />
      </div>
      <div className={styles.info}>
        <div className={styles.title}>{shop.name}</div>
        <div className={styles.rate}>
          {shop.score != null ? (
            <>
              <Rate
                readOnly
                value={shop.score / 10}
                style={{ '--star-size': '12px', '--active-color': '#F63' }}
              />
              <span className={styles.score}>
                {shop.score / 10}{t('shopCard.score')}
              </span>
            </>
          ) : (
            <span className={styles.ratingUnavailable}>{t('shopCard.ratingUnavailable')}</span>
          )}
          <span className={styles.reviewCount}>
            {displayReviewCount}{t('shopCard.comments')}
          </span>
        </div>
        <div className={styles.area}>
          <span>{shop.area}</span>
          {shop.distance != null && (
            <span className={styles.distance}>{formatDistance(shop.distance)}</span>
          )}
        </div>
        <div className={styles.avgPrice}>
          {shop.avgPrice != null
            ? `$${shop.avgPrice}${t('shopCard.perPerson')}`
            : t('shopCard.priceUnavailable')}
        </div>
        <div className={styles.address}>
          <EnvironmentOutline fontSize={12} />
          <span>{shop.address}</span>
        </div>
      </div>
    </Link>
  );
}
