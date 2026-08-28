import { useState } from 'react';
import { Rate, Toast } from 'antd-mobile';
import { useTranslation } from 'react-i18next';
import { translateReview } from '../../api/translate';
import { cleanDisplayContent } from '../../utils/displayContent';
import styles from './ReviewThread.module.css';

export interface ReviewData {
  id: number;
  userId: number;
  rating?: number | null;
  content: string;
  images?: string;
  liked: number;
  nickName: string;
  icon: string;
  createTime: string;
  rootId?: number;
  parentId?: number;
  replyToUserId?: number;
  replyToNickName?: string;
  depth?: number;
  sourceType?: 'SYNTHETIC' | 'USER_SUBMITTED' | 'LEGACY';
  authorRole?: 'USER' | 'MERCHANT';
  children?: ReviewData[];
}

interface ReviewThreadProps {
  review: ReviewData;
  compact?: boolean;
}

export default function ReviewThread({ review, compact = false }: ReviewThreadProps) {
  const { t, i18n } = useTranslation();
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const [translation, setTranslation] = useState('');
  const [translating, setTranslating] = useState(false);
  const reviewImages = review.images ? review.images.split(',').filter(Boolean) : [];
  const depth = Math.min(2, Math.max(0, review.depth ?? 0));

  const toggleTranslation = async () => {
    if (translation) {
      setTranslation('');
      return;
    }
    if (translating) return;
    setTranslating(true);
    try {
      const response = await translateReview(review.id, 'zh-CN');
      setTranslation(String(response.data ?? response));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      Toast.show({
        icon: 'fail',
        content: message === 'Please sign in first'
          ? t('shopDetail.translationLoginRequired')
          : t('shopDetail.translationFailed'),
      });
    } finally {
      setTranslating(false);
    }
  };

  return (
    <div className={`${styles.thread} ${compact ? styles.compact : ''}`} data-depth={depth}>
      <article className={styles.review}>
        <div className={styles.avatar}>
          <img src={review.icon || '/imgs/icons/default-icon.png'} alt="" loading="lazy" />
        </div>
        <div className={styles.body}>
          <div className={styles.heading}>
            <strong>{review.nickName || t('shopReviews.anonymous')}</strong>
          </div>
          {review.replyToNickName && (
            <div className={styles.replyTo}>
              {t('shopReviews.replyingTo', { name: review.replyToNickName })}
            </div>
          )}
          {review.rating != null && (
            <Rate
              readOnly
              value={review.rating}
              style={{ '--star-size': compact ? '10px' : '11px', '--active-color': '#F63' }}
            />
          )}
          <div className={styles.content}>{cleanDisplayContent(review.content)}</div>
          {translation && <div className={styles.translation}>{translation}</div>}
          {isChinese && (
            <button
              type="button"
              className={styles.translateButton}
              disabled={translating}
              onClick={toggleTranslation}
            >
              {translating
                ? t('shopDetail.translatingDeepSeek')
                : translation
                  ? t('shopDetail.hideTranslation')
                  : `✦ ${t('shopDetail.deepSeekTranslate')}`}
            </button>
          )}
          {reviewImages.length > 0 && (
            <div className={styles.images}>
              {reviewImages.map((image, index) => (
                <img key={`${review.id}-${index}`} src={image} alt="" loading="lazy" />
              ))}
            </div>
          )}
          <div className={styles.footer}>
            <span>{t('shopDetail.like', { n: review.liked ?? 0 })}</span>
            {review.createTime && <time>{new Date(review.createTime).toLocaleDateString()}</time>}
          </div>
        </div>
      </article>
      {(review.children ?? []).map((child) => (
        <div className={styles.children} key={child.id}>
          <ReviewThread review={child} compact />
        </div>
      ))}
    </div>
  );
}
