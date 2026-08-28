import { useNavigate } from 'react-router-dom';
import LikeButton from '../LikeButton';
import { NoteVisual } from '../MerchantVisual';
import type { BlogData } from '../BlogCard';
import styles from './FeedCard.module.css';

interface FeedCardProps {
  blog: BlogData;
  onLikeUpdate?: (blogId: number) => void;
}

export default function FeedCard({ blog, onLikeUpdate }: FeedCardProps) {
  const navigate = useNavigate();
  return (
    <div className={styles.card} onClick={() => navigate(`/blog-detail/${blog.id}`)}>
      <div className={styles.cover}>
        <NoteVisual
          blogId={blog.id}
          shopId={blog.shopId}
          shopName={blog.shopName}
          typeId={blog.typeId}
          images={blog.img || blog.images}
          sourceType={blog.sourceType}
          alt={blog.title}
          loading="lazy"
        />
      </div>
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
