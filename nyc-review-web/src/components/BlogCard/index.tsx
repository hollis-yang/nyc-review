import { useNavigate } from 'react-router-dom';
import LikeButton from '../LikeButton';
import { NoteVisual } from '../MerchantVisual';
import styles from './BlogCard.module.css';

export interface BlogData {
  id: number;
  title: string;
  images: string;
  icon?: string;
  name?: string;
  liked: number;
  isLike: boolean;
  comments?: number;
  img?: string;
  sourceType?: string;
  shopId?: number;
  typeId?: number;
  shopName?: string;
}

interface BlogCardProps {
  blog: BlogData;
  onLikeUpdate?: (blogId: number, liked: number, isLike: boolean) => void;
}

export default function BlogCard({ blog, onLikeUpdate }: BlogCardProps) {
  const navigate = useNavigate();
  const handleLikeUpdate = (liked: number, isLike: boolean) => {
    if (onLikeUpdate) {
      onLikeUpdate(blog.id, liked, isLike);
    }
  };

  return (
    <div className={styles.box} onClick={() => navigate(`/blog-detail/${blog.id}`)}>
      <div className={styles.img}>
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
      <div className={styles.title}>
        <div className={styles.titleText}>{blog.title}</div>
      </div>
      <div className={styles.foot}>
        <div className={styles.userIcon}>
          <img src={blog.icon || '/imgs/icons/default-icon.png'} alt="" />
        </div>
        <div className={styles.userName}>{blog.name || ''}</div>
        <LikeButton
          blogId={blog.id}
          liked={blog.liked}
          isLike={blog.isLike}
          onLikeUpdate={handleLikeUpdate}
        />
      </div>
    </div>
  );
}
