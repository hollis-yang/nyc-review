import { useNavigate } from 'react-router-dom';
import LikeButton from '../LikeButton';
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
}

interface BlogCardProps {
  blog: BlogData;
  onLikeUpdate?: (blogId: number, liked: number, isLike: boolean) => void;
}

export default function BlogCard({ blog, onLikeUpdate }: BlogCardProps) {
  const navigate = useNavigate();
  const imgSrc = blog.img || (blog.images ? blog.images.split(',')[0] : '');

  const handleLikeUpdate = (liked: number, isLike: boolean) => {
    if (onLikeUpdate) {
      onLikeUpdate(blog.id, liked, isLike);
    }
  };

  return (
    <div className={styles.box} onClick={() => navigate(`/blog-detail/${blog.id}`)}>
      <div className={styles.img}>
        <img src={imgSrc} alt="" />
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
