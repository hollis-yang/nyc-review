import { likeBlog, getBlogById } from '../../api/blog';
import { Toast } from 'antd-mobile';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import styles from './LikeButton.module.css';

interface LikeButtonProps {
  blogId: number;
  liked: number;
  isLike: boolean;
  onLikeUpdate: (liked: number, isLike: boolean) => void;
}

export default function LikeButton({ blogId, liked, isLike, onLikeUpdate }: LikeButtonProps) {
  const { t } = useTranslation();
  const actionLockRef = useRef(false);
  const [actionPending, setActionPending] = useState(false);

  const handleLike = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (actionLockRef.current) return;
    actionLockRef.current = true;
    setActionPending(true);
    try {
      await likeBlog(blogId);
      onLikeUpdate(Math.max(0, liked + (isLike ? -1 : 1)), !isLike);
      try {
        const res = await getBlogById(blogId);
        const data = res.data ?? res;
        onLikeUpdate(data.liked, data.isLike);
      } catch {
        // The toggle succeeded; retain the local result if the refresh is unavailable.
      }
    } catch {
      Toast.show({ icon: 'fail', content: t('common.actionFailed') });
    } finally {
      actionLockRef.current = false;
      setActionPending(false);
    }
  };

  return (
    <button
      type="button"
      className={styles.liked}
      onClick={handleLike}
      disabled={actionPending}
      aria-busy={actionPending}
      aria-label={t('shopDetail.like', { n: liked })}
    >
      <svg
        viewBox="0 0 1024 1024"
        width="14"
        height="14"
        fill={isLike ? '#ff6633' : '#82848a'}
      >
        <path d="M160 944c0 8.8-7.2 16-16 16h-32c-26.5 0-48-21.5-48-48V528c0-26.5 21.5-48 48-48h32c8.8 0 16 7.2 16 16v448zM96 416c-53 0-96 43-96 96v416c0 53 43 96 96 96h96c17.7 0 32-14.3 32-32V448c0-17.7-14.3-32-32-32H96zM505.6 64c16.2 0 26.4 8.7 31 13.9 4.6 5.2 12.1 16.3 10.3 32.4l-23.5 203.4c-4.9 42.2 8.6 84.6 36.8 116.4 28.3 31.7 68.9 49.9 111.4 49.9h271.2c6.6 0 10.8 3.3 13.2 6.1s5 7.5 4 14l-48 303.4c-6.9 43.6-29.1 83.4-62.7 112C815.8 944.2 773 960 728.9 960h-317c-33.1 0-59.9-26.8-59.9-59.9v-455c0-6.1 1.7-12 5-17.1 69.5-109 106.4-234.2 107-364h41.6z m0-64h-44.9C427.2 0 400 27.2 400 60.7c0 127.1-39.1 251.2-112 355.3v484.1c0 68.4 55.5 123.9 123.9 123.9h317c122.7 0 227.2-89.3 246.3-210.5l47.9-303.4c7.8-49.4-30.4-94.1-80.4-94.1H671.6c-50.9 0-90.5-44.4-84.6-95l23.5-203.4C617.7 55 568.7 0 505.6 0z" />
      </svg>
      <span>{liked}</span>
    </button>
  );
}
