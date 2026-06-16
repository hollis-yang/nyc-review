import { useNavigate } from 'react-router-dom';
import LikeButton from '../LikeButton';
import type { BlogData } from '../BlogCard';
import styles from './FeedCard.module.css';

interface FeedCardProps {
  blog: BlogData;
  onLikeUpdate?: (blogId: number) => void;
}

export default function FeedCard({ blog, onLikeUpdate }: FeedCardProps) {
  const navigate = useNavigate();
  const imgSrc = blog.img || (blog.images ? blog.images.split(',')[0] : '');

  return (
    <div className={styles.card} onClick={() => navigate(`/blog-detail/${blog.id}`)}>
      {imgSrc && (
        <div className={styles.cover}>
          <img src={imgSrc} alt="" />
        </div>
      )}
      <div className={styles.body}>
        <div className={styles.title}>{blog.title}</div>
        <div className={styles.meta}>
          <div className={styles.author}>
            <div className={styles.authorIcon}>
              <img src={blog.icon || '/imgs/icons/default-icon.png'} alt="" />
            </div>
            <span className={styles.authorName}>{blog.name || ''}</span>
          </div>
          <LikeButton
            blogId={blog.id}
            liked={blog.liked}
            isLike={blog.isLike}
            onLikeUpdate={() => onLikeUpdate?.(blog.id)}
          />
        </div>
      </div>
    </div>
  );
}
