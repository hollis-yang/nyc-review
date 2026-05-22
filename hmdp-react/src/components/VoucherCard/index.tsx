import { Toast } from 'antd-mobile';
import { formatPrice } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import styles from './VoucherCard.module.css';

export interface VoucherData {
  id: number;
  title: string;
  subTitle: string;
  payValue: number;
  actualValue: number;
  type: number;
  stock: number;
  beginTime: string;
  endTime: string;
}

interface VoucherCardProps {
  voucher: VoucherData;
  onSeckill: (id: number) => void;
}

function formatTime(v: VoucherData): string {
  const b = new Date(v.beginTime);
  const e = new Date(v.endTime);
  const pad = (m: number) => (m < 10 ? '0' + m : String(m));
  return `${b.getMonth() + 1}月${b.getDate()}日 ${b.getHours()}:${pad(b.getMinutes())} ~ ${e.getHours()}:${pad(e.getMinutes())}`;
}

function isNotBegin(v: VoucherData): boolean {
  return new Date(v.beginTime).getTime() > Date.now();
}

function isEnd(v: VoucherData): boolean {
  return new Date(v.endTime).getTime() < Date.now();
}

export default function VoucherCard({ voucher, onSeckill }: VoucherCardProps) {
  const { isAuthenticated } = useAuth();
  const v = voucher;

  if (isEnd(v)) return null;

  const discount = ((v.payValue * 10) / v.actualValue).toFixed(1);
  const price = formatPrice(v.payValue);
  const disabled = isNotBegin(v) || v.stock < 1;

  const handleSeckill = () => {
    if (!isAuthenticated) {
      Toast.show({ icon: 'fail', content: '请先登录' });
      setTimeout(() => {
        window.location.href = '/login';
      }, 200);
      return;
    }
    if (isNotBegin(v)) {
      Toast.show({ icon: 'fail', content: '优惠券抢购尚未开始！' });
      return;
    }
    if (isEnd(v)) {
      Toast.show({ icon: 'fail', content: '优惠券抢购已经结束！' });
      return;
    }
    if (v.stock < 1) {
      Toast.show({ icon: 'fail', content: '库存不足，请刷新再试试！' });
      return;
    }
    onSeckill(v.id);
  };

  return (
    <div className={styles.box}>
      <div className={styles.left}>
        <div className={styles.title}>{v.title}</div>
        <div className={styles.subtitle}>{v.subTitle}</div>
        <div className={styles.price}>
          <div>￥ {price}</div>
          <span>{discount}折</span>
        </div>
      </div>
      <div className={styles.right}>
        {v.type ? (
          <div className={styles.seckillBox}>
            <div
              className={`${styles.btn} ${disabled ? styles.disableBtn : ''}`}
              onClick={handleSeckill}
            >
              限时抢购
            </div>
            <div className={styles.stock}>
              剩余 <span>{v.stock}</span> 张
            </div>
            <div className={styles.time}>{formatTime(v)}</div>
          </div>
        ) : (
          <div className={styles.btn}>抢购</div>
        )}
      </div>
    </div>
  );
}
