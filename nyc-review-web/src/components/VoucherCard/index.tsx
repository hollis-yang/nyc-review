import { Toast } from 'antd-mobile';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatPrice } from '../../utils';
import { purchaseVoucher } from '../../api/voucher';
import { useAuth } from '../../hooks/useAuth';
import { buildAuthEntryUrl, currentRouteTarget } from '../../utils/authRedirect';
import type { TFunction } from 'i18next';
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
  validDays?: number;
  sourceType?: string;
}

interface VoucherCardProps {
  voucher: VoucherData;
  onSeckill: (id: number) => Promise<void> | void;
}

function formatTime(v: VoucherData, t: TFunction): string {
  const b = new Date(v.beginTime);
  const e = new Date(v.endTime);
  const pad = (m: number) => (m < 10 ? '0' + m : String(m));
  return t('voucherCard.timeFormat', {
    m: b.getMonth() + 1, d: b.getDate(),
    h: b.getHours(), min: pad(b.getMinutes()),
    eh: e.getHours(), emin: pad(e.getMinutes()),
  }).replace(/\{(\w+)\}/g, (_: string, k: string) => String({m: b.getMonth()+1, d: b.getDate(), h: b.getHours(), min: pad(b.getMinutes()), eh: e.getHours(), emin: pad(e.getMinutes())}[k] ?? ''));
}

function isNotBegin(v: VoucherData): boolean {
  return new Date(v.beginTime).getTime() > Date.now();
}

function isEnd(v: VoucherData): boolean {
  return new Date(v.endTime).getTime() < Date.now();
}

export default function VoucherCard({ voucher, onSeckill }: VoucherCardProps) {
  const { t, i18n } = useTranslation();
  const { isAuthenticated } = useAuth();
  const actionLockRef = useRef(false);
  const [actionPending, setActionPending] = useState(false);
  const v = voucher;

  if (isEnd(v)) return null;

  const hasValidPrice = v.actualValue > 0 && v.payValue >= 0;
  const discount = hasValidPrice
    ? i18n.resolvedLanguage === 'zh-CN'
      // Chinese commerce convention: 50% of the original price is 5 折.
      ? Number(((v.payValue * 10) / v.actualValue).toFixed(1))
      // English convention: show the percentage saved, e.g. 50% off.
      : Number((((v.actualValue - v.payValue) * 100) / v.actualValue).toFixed(1))
    : 0;
  const price = formatPrice(v.payValue);
  const disabled = actionPending || isNotBegin(v) || (v.type === 1 && v.stock < 1);

  const handleSeckill = async () => {
    if (actionLockRef.current) return;
    if (!isAuthenticated) {
      Toast.show({ icon: 'fail', content: t('voucher.loginRequired') });
      setTimeout(() => {
        window.location.href = buildAuthEntryUrl('/login', currentRouteTarget(window.location));
      }, 200);
      return;
    }
    if (isNotBegin(v)) {
      Toast.show({ icon: 'fail', content: t('voucher.notStarted') });
      return;
    }
    if (isEnd(v)) {
      Toast.show({ icon: 'fail', content: t('voucher.ended') });
      return;
    }
    if (v.type === 1 && v.stock < 1) {
      Toast.show({ icon: 'fail', content: t('voucher.outOfStock') });
      return;
    }
    actionLockRef.current = true;
    setActionPending(true);
    try {
      if (v.type === 1) {
        await onSeckill(v.id);
      } else {
        const res = await purchaseVoucher(v.id);
        Toast.show({ icon: 'success', content: t('voucher.purchaseSuccess', { id: res.data ?? res }) });
      }
    } catch {
      Toast.show({ icon: 'fail', content: t('common.actionFailed') });
    } finally {
      actionLockRef.current = false;
      setActionPending(false);
    }
  };

  return (
    <div className={styles.box}>
      <div className={styles.left}>
        <div className={styles.title}>{v.title}</div>
        <div className={styles.subtitle}>{v.subTitle}</div>
        <div className={styles.validity}>
          {t('voucherCard.validityDays', { n: v.validDays ?? 30 })}
        </div>
        <div className={styles.price}>
          <div>$ {price}</div>
          <span>{discount}{t("voucherCard.off")}</span>
        </div>
      </div>
      <div className={styles.right}>
        {v.type ? (
          <div className={styles.seckillBox}>
            <button
              type="button"
              className={`${styles.btn} ${disabled ? styles.disableBtn : ''}`}
              onClick={handleSeckill}
              disabled={disabled}
              aria-busy={actionPending}
            >
              {t('voucher.flashSale')}
            </button>
            <div className={styles.stock}>
              {t('voucher.remaining', { n: v.stock })}
            </div>
            <div className={styles.time}>{formatTime(v, t)}</div>
          </div>
        ) : (
          <button
            type="button"
            className={styles.btn}
            onClick={handleSeckill}
            disabled={disabled}
            aria-busy={actionPending}
          >
            {t('voucher.buy')}
          </button>
        )}
      </div>
    </div>
  );
}
