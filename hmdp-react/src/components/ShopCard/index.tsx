import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Rate } from 'antd-mobile';
import { EnvironmentOutline } from 'antd-mobile-icons';
import styles from './ShopCard.module.css';

export interface ShopData {
  id: number;
  name: string;
  images: string;
  score?: number | null;
  comments: number;
  area: string;
  distance?: number;
  avgPrice?: number | null;
  address: string;
  sourceType?: string;
  syntheticFields?: string[];
}

interface ShopCardProps {
  shop: ShopData;
}

export default function ShopCard({ shop }: ShopCardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const imgSrc = shop.images ? shop.images.split(',')[0] : '';

  const formatDistance = (d: number) => {
    if (d < 1000) return d.toFixed(1) + 'm';
    return (d / 1000).toFixed(1) + 'km';
  };

  return (
    <div className={styles.box} onClick={() => navigate(`/shop-detail/${shop.id}`)}>
      <div className={styles.img}>
        <img src={imgSrc} alt="" />
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
              <span style={{ color: '#F63', fontSize: 11, marginLeft: 4 }}>
                {shop.score / 10}{t('shopCard.score')}
              </span>
            </>
          ) : (
            <span style={{ color: '#999', fontSize: 11 }}>{t('shopCard.ratingUnavailable')}</span>
          )}
          <span style={{ color: '#999', fontSize: 10, marginLeft: 4 }}>
            {shop.comments}{t('shopCard.comments')}
          </span>
        </div>
        <div className={styles.area}>
          <span>{shop.area}</span>
          {shop.distance != null && (
            <span style={{ marginLeft: 8 }}>{formatDistance(shop.distance)}</span>
          )}
        </div>
        <div className={styles.avgPrice}>
          {shop.avgPrice != null
            ? `$${shop.avgPrice}${t('shopCard.perPerson')}`
            : t('shopCard.priceUnavailable')}
        </div>
        <div className={styles.address}>
          <EnvironmentOutline fontSize={12} />
          <span style={{ marginLeft: 2 }}>{shop.address}</span>
        </div>
      </div>
    </div>
  );
}
