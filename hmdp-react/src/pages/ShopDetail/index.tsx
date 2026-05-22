import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LeftOutline, EnvironmentOutline } from 'antd-mobile-icons';
import { Rate, Toast } from 'antd-mobile';
import { getShopById, getShopReviews } from '../../api/shop';
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
  const navigate = useNavigate();
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [vouchers, setVouchers] = useState<VoucherData[]>([]);
  const [reviews, setReviews] = useState<ReviewData[]>([]);
  const [reviewTotal, setReviewTotal] = useState(0);
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
        setReviewTotal(res.total ?? list.length);
      }),
    ]).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || '店铺不存在');
    });
  }, [id]);

  const handleSeckill = async (voucherId: number) => {
    try {
      const res = await seckillVoucher(voucherId);
      Toast.show({ icon: 'success', content: '抢购成功，订单id：' + (res.data ?? res) });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
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
    return <div className={styles.loadingFull}>加载中...</div>;
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.title}>{shop.name}</div>
        <div className={styles.share}>...</div>
      </div>
      <div className={styles.scroll}>
        <div className={styles.infoBox}>
          <div className={styles.shopTitle}>{shop.name}</div>
          <div className={styles.shopRate}>
            <Rate
              readOnly
              value={shop.score / 10}
              style={{ '--star-size': '14px', '--active-color': '#F63' }}
            />
            <span style={{ color: '#F63', fontSize: 12, marginLeft: 6 }}>
              {shop.score / 10}分
            </span>
            <span style={{ color: '#999', fontSize: 11, marginLeft: 4 }}>
              {shop.comments}条
            </span>
          </div>
          <div className={styles.rateInfo}>口味:4.9  环境:4.8  服务:4.7</div>
          <div className={styles.shopRank}>
            <img src="/imgs/bd.png" width="63" height="20" alt="" />
            <span>拱墅区好评榜第3名</span>
            <div>&gt;</div>
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
            <span style={{ fontSize: 12 }}>导航</span>
          </div>
        </div>

        <div className={styles.divider} />

        <div className={styles.openTime}>
          <span>🕐</span>
          <div>营业时间</div>
          <div style={{ flex: 1, fontSize: 12 }}>{shop.openHours}</div>
          <span className={styles.lineRight}>查看详情 &gt;</span>
        </div>

        <div className={styles.divider} />

        <div className={styles.voucherSection}>
          <div>
            <span className={styles.voucherIcon}>券</span>
            <span style={{ fontWeight: 'bold' }}>代金券</span>
          </div>
          {vouchers.map((v) => (
            <VoucherCard key={v.id} voucher={v} onSeckill={handleSeckill} />
          ))}
        </div>

        <div className={styles.divider} />

        <div className={styles.comments}>
          <div className={styles.commentsHead}>
            <div>网友评价 <span>（{reviewTotal || shop.comments}）</span></div>
            {reviewTotal > 3 && (
              <div style={{ cursor: 'pointer' }} onClick={() => navigate(`/shop-reviews/${id}?name=${encodeURIComponent(shop.name)}`)}>&gt;</div>
            )}
          </div>
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
                    {reviewImages.length > 0 && (
                      <div className={styles.commentImages}>
                        {reviewImages.map((img: string, idx: number) => (
                          <img key={idx} src={img} alt="" />
                        ))}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: '#999' }}>
                      点赞{review.liked}
                    </div>
                  </div>
                </div>
              );
            })}
            {reviewTotal > 3 && (
              <div className={styles.viewAll} onClick={() => navigate(`/shop-reviews/${id}?name=${encodeURIComponent(shop.name)}`)}>
                <div>查看全部{reviewTotal}条评价</div>
                <div>&gt;</div>
              </div>
            )}
          </div>
        </div>

        <div className={styles.divider} />
        <div className={styles.copyright}>copyright ©2021 hmdp.com</div>
      </div>
    </div>
  );
}
