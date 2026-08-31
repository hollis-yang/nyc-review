import { useState } from 'react';
import { Rate, Toast } from 'antd-mobile';
import { useTranslation } from 'react-i18next';
import { translateReview } from '../../api/translate';
import { createShopReview, toggleShopReviewLike } from '../../api/shop';
import { cleanDisplayContent } from '../../utils/displayContent';
import styles from './ReviewThread.module.css';

export interface ReviewData {
  id: number;
  userId: number;
  rating?: number | null;
  content: string;
  images?: string;
  liked: number;
  isLike?: boolean;
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
  shopId?: number;
  onReplyCreated?: () => void | Promise<void>;
  nestingDepth?: number;
}

export default function ReviewThread({
  review,
  compact = false,
  shopId,
  onReplyCreated,
  nestingDepth = 0,
}: ReviewThreadProps) {
  const { t, i18n } = useTranslation();
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const [translation, setTranslation] = useState('');
  const [translating, setTranslating] = useState(false);
  const [liked, setLiked] = useState(review.liked ?? 0);
  const [isLike, setIsLike] = useState(Boolean(review.isLike));
  const [likeBusy, setLikeBusy] = useState(false);
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyContent, setReplyContent] = useState('');
  const [replySubmitting, setReplySubmitting] = useState(false);
  const reviewImages = review.images ? review.images.split(',').filter(Boolean) : [];
  const depth = Math.min(2, Math.max(0, review.depth ?? 0));
  const visualDepth = Math.min(2, Math.max(nestingDepth, review.depth ?? 0));

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

  const toggleLike = async () => {
    if (likeBusy) return;
    setLikeBusy(true);
    try {
      const response = await toggleShopReviewLike(review.id);
      const result = (response.data ?? response) as { liked: number; isLike: boolean };
      setLiked(result.liked);
      setIsLike(result.isLike);
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: error instanceof Error ? error.message : String(error) });
    } finally {
      setLikeBusy(false);
    }
  };

  const submitReply = async () => {
    if (!shopId || !replyContent.trim() || replySubmitting) return;
    setReplySubmitting(true);
    try {
      await createShopReview({
        shopId,
        parentId: review.id,
        content: replyContent.trim(),
      });
      setReplyContent('');
      setReplyOpen(false);
      await onReplyCreated?.();
      Toast.show({ icon: 'success', content: t('shopReviews.replySuccess') });
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: error instanceof Error ? error.message : String(error) });
    } finally {
      setReplySubmitting(false);
    }
  };

  return (
    <div className={`${styles.thread} ${compact ? styles.compact : ''}`} data-depth={visualDepth}>
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
                ? t('shopDetail.translatingAI')
                : translation
                  ? t('shopDetail.hideTranslation')
                  : `✦ ${t('shopDetail.aiTranslate')}`}
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
            <button
              type="button"
              className={`${styles.likeButton} ${isLike ? styles.likeButtonActive : ''}`}
              disabled={likeBusy}
              onClick={toggleLike}
            >
              ♡ {t('shopDetail.like', { n: liked })}
            </button>
            {shopId && depth < 2 && (
              <button type="button" className={styles.replyButton} onClick={() => setReplyOpen((value) => !value)}>
                {t('shopReviews.reply')}
              </button>
            )}
            {review.createTime && <time>{new Date(review.createTime).toLocaleDateString()}</time>}
          </div>
          {replyOpen && (
            <div className={styles.replyComposer}>
              <div>{t('shopReviews.replyingTo', { name: review.nickName || t('shopReviews.anonymous') })}</div>
              <textarea
                rows={2}
                maxLength={2000}
                value={replyContent}
                placeholder={t('shopReviews.replyPlaceholder')}
                onChange={(event) => setReplyContent(event.target.value)}
              />
              <div className={styles.replyActions}>
                <button type="button" onClick={() => { setReplyOpen(false); setReplyContent(''); }}>
                  {t('common.cancel')}
                </button>
                <button
                  type="button"
                  className={styles.replySubmit}
                  disabled={!replyContent.trim() || replySubmitting}
                  onClick={submitReply}
                >
                  {replySubmitting ? t('shopDetail.submitting') : t('blogDetail.send')}
                </button>
              </div>
            </div>
          )}
        </div>
      </article>
      {(review.children ?? []).map((child) => (
        <div className={styles.children} key={child.id}>
          <ReviewThread
            review={child}
            compact={compact}
            shopId={shopId}
            onReplyCreated={onReplyCreated}
            nestingDepth={visualDepth + 1}
          />
        </div>
      ))}
    </div>
  );
}
