import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Toast } from 'antd-mobile';
import { getBlogById, getBlogLikes, likeBlog, getBlogComments, createBlogComment } from '../../api/blog';
import { getShopById } from '../../api/shop';
import { getMe } from '../../api/user';
import { isFollowed, follow } from '../../api/follow';
import ImageSwiper from '../../components/ImageSwiper';
import styles from './BlogDetail.module.css';

interface BlogInfo {
  id: number;
  images: string[];
  icon: string;
  name: string;
  title: string;
  createTime: string;
  content: string;
  userId: number;
  isLike: boolean;
  liked: number;
  shopId: number;
  comments: number;
}

interface ShopInfo {
  id: number;
  image: string;
  name: string;
  score: number;
  avgPrice: number;
}

interface CommentInfo {
  id: number;
  userId: number;
  icon: string;
  name: string;
  content: string;
  liked: number;
  createTime: string;
}

export default function BlogDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [blog, setBlog] = useState<BlogInfo | null>(null);
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [likes, setLikes] = useState<{ id: number; icon: string }[]>([]);
  const [comments, setComments] = useState<CommentInfo[]>([]);
  const [currentUser, setCurrentUser] = useState<{ id: number } | null>(null);
  const [followed, setFollowed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [commentText, setCommentText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!id) return;
    getBlogById(id)
      .then((res) => {
        const data = res.data ?? res;
        data.images = data.images ? data.images.split(',') : [];
        setBlog(data);
        if (data.shopId) {
          getShopById(data.shopId).then((r) => {
            const s = r.data ?? r;
            s.image = s.images ? s.images.split(',')[0] : '';
            setShop(s);
          }).catch(() => {});
        }
        getBlogLikes(id).then((r) => setLikes(r.data ?? r)).catch(() => {});
        getBlogComments(id).then((r) => setComments(r.data ?? r)).catch(() => {});
        getMe()
          .then((r) => {
            const u = r.data ?? r;
            setCurrentUser(u);
            if (u.id !== data.userId) {
              isFollowed(data.userId)
                .then((r2) => setFollowed(r2.data ?? r2))
                .catch(() => {});
            }
          })
          .catch(() => {});
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg || '笔记不存在');
      });
  }, [id]);

  const handleLike = async () => {
    if (!blog) return;
    try {
      await likeBlog(blog.id);
      const res = await getBlogById(blog.id);
      const data = res.data ?? res;
      data.images = data.images ? data.images.split(',') : [];
      setBlog(data);
      const likesRes = await getBlogLikes(blog.id);
      setLikes(likesRes.data ?? likesRes);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleFollow = async () => {
    if (!blog) return;
    try {
      await follow(blog.userId, !followed);
      Toast.show({ icon: 'success', content: followed ? '已取消关注' : '已关注' });
      setFollowed(!followed);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const scrollToComments = () => {
    document.getElementById('comments-section')?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleShare = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try { await navigator.share({ title: blog?.title ?? '笔记详情', url }); } catch {}
    } else {
      await navigator.clipboard.writeText(url);
      Toast.show({ icon: 'success', content: '链接已复制' });
    }
  };

  const handleCommentSubmit = async () => {
    if (!commentText.trim() || !id) return;
    setSubmitting(true);
    try {
      await createBlogComment({ blogId: Number(id), content: commentText.trim() });
      Toast.show({ icon: 'success', content: '评论成功' });
      setCommentText('');
      const res = await getBlogComments(id);
      setComments(res.data ?? res);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    } finally {
      setSubmitting(false);
    }
  };

  /* ---- 渲染 ---- */

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={20} color="#fff" />
          </div>
          <div className={styles.title}>笔记详情</div>
          <div className={styles.share} />
        </div>
        <div className={styles.loadingFull}>{error}</div>
      </div>
    );
  }

  if (!blog) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={20} color="#fff" />
          </div>
          <div className={styles.title}>笔记详情</div>
          <div className={styles.share} />
        </div>
        <div className={styles.loadingFull}>加载中...</div>
      </div>
    );
  }

  const formatDate = (d: string) => {
    const date = new Date(d);
    return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
  };

  const formatDateTime = (d: string) => {
    const date = new Date(d);
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hour}:${min}`;
  };

  const handleAuthorClick = () => {
    if (blog.userId === currentUser?.id) {
      navigate('/profile');
    } else {
      navigate(`/user/${blog.userId}`);
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={20} color="#fff" />
        </div>
        <div className={styles.title}>笔记详情</div>
        <div className={styles.share} onClick={handleShare}>
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="5" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
            <circle cx="12" cy="12" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
            <circle cx="12" cy="19" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
          </svg>
        </div>
      </div>

      <div className={styles.scroll}>
        {/* 图片卡片：Swiper + 作者信息 */}
        <div className={styles.imageCard}>
          <ImageSwiper images={blog.images} />
          <div className={styles.basic}>
            <div className={styles.basicIcon} onClick={handleAuthorClick}>
              <img src={blog.icon || '/imgs/icons/default-icon.png'} alt="" />
            </div>
            <div className={styles.basicInfo}>
              <div className={styles.name}>{blog.name}</div>
              <div className={styles.time}>{formatDate(blog.createTime)}</div>
            </div>
            <div className={styles.followArea}>
              {(!currentUser || currentUser.id !== blog.userId) && (
                <div className={styles.followBtn} onClick={handleFollow}>
                  {followed ? '取消关注' : '关注'}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 正文卡片 */}
        <div className={styles.contentCard}>
          {blog.title && (
            <div className={styles.contentTitle}>{blog.title}</div>
          )}
          <div
            className={styles.contentBody}
            dangerouslySetInnerHTML={{ __html: blog.content }}
          />
        </div>

        {/* 关联商铺卡片 */}
        {shop && (
          <div className={styles.shopBasic} onClick={() => navigate(`/shop-detail/${shop.id}`)}>
            <div className={styles.shopIcon}>
              <img src={shop.image} alt="" />
            </div>
            <div className={styles.shopInfo}>
              <div className={styles.shopName}>{shop.name}</div>
              <span style={{ fontSize: 12, color: '#F63', fontWeight: 600 }}>
                ★ {shop.score / 10}
              </span>
              <div className={styles.shopAvg}>￥{shop.avgPrice}/人</div>
            </div>
          </div>
        )}

        {/* 点赞卡片 */}
        <div className={styles.zanBox}>
          <div className={styles.likeIconWrapper} onClick={handleLike}>
            <svg viewBox="0 0 1024 1024" width="22" height="22" fill={blog.isLike ? '#ff6633' : '#82848a'}>
              <path d="M160 944c0 8.8-7.2 16-16 16h-32c-26.5 0-48-21.5-48-48V528c0-26.5 21.5-48 48-48h32c8.8 0 16 7.2 16 16v448zM96 416c-53 0-96 43-96 96v416c0 53 43 96 96 96h96c17.7 0 32-14.3 32-32V448c0-17.7-14.3-32-32-32H96zM505.6 64c16.2 0 26.4 8.7 31 13.9 4.6 5.2 12.1 16.3 10.3 32.4l-23.5 203.4c-4.9 42.2 8.6 84.6 36.8 116.4 28.3 31.7 68.9 49.9 111.4 49.9h271.2c6.6 0 10.8 3.3 13.2 6.1s5 7.5 4 14l-48 303.4c-6.9 43.6-29.1 83.4-62.7 112C815.8 944.2 773 960 728.9 960h-317c-33.1 0-59.9-26.8-59.9-59.9v-455c0-6.1 1.7-12 5-17.1 69.5-109 106.4-234.2 107-364h41.6z m0-64h-44.9C427.2 0 400 27.2 400 60.7c0 127.1-39.1 251.2-112 355.3v484.1c0 68.4 55.5 123.9 123.9 123.9h317c122.7 0 227.2-89.3 246.3-210.5l47.9-303.4c7.8-49.4-30.4-94.1-80.4-94.1H671.6c-50.9 0-90.5-44.4-84.6-95l23.5-203.4C617.7 55 568.7 0 505.6 0z" />
            </svg>
          </div>
          <div className={styles.zanList}>
            {likes.map((u) => (
              <div key={u.id} className={styles.userIconMini}>
                <img src={u.icon || '/imgs/icons/default-icon.png'} alt="" />
              </div>
            ))}
            <div className={styles.likedCount}>{blog.liked}人点赞</div>
          </div>
        </div>

        {/* 评论卡片 */}
        <div className={styles.comments} id="comments-section">
          <div className={styles.commentsHead}>
            <div>
              网友评价 <span>（{comments.length}）</span>
            </div>
            <div className={styles.commentsHeadArrow} onClick={scrollToComments}>&gt;</div>
          </div>
          {comments.length > 0 ? (
            comments.map((c) => (
              <div className={styles.commentItem} key={c.id}>
                <div className={styles.commentIcon}>
                  <img src={c.icon || '/imgs/icons/default-icon.png'} alt="" />
                </div>
                <div className={styles.commentInfo}>
                  <div className={styles.commentUser}>{c.name}</div>
                  <div className={styles.commentContent}>{c.content}</div>
                  <div className={styles.commentTime}>{formatDateTime(c.createTime)}</div>
                </div>
              </div>
            ))
          ) : (
            <div className={styles.commentPlaceholder}>
              <div className={styles.commentPlaceholderIcon}>💬</div>
              <div>暂无评论，快来抢沙发</div>
            </div>
          )}
        </div>
      </div>

      {/* 底部固定区域 */}
      <div className={styles.bottomSticky}>
        <div className={styles.commentInputBar}>
          <input
            type="text"
            placeholder="说点什么..."
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCommentSubmit(); }}
            className={styles.commentInput}
          />
          <div
            className={styles.commentSubmit}
            onClick={handleCommentSubmit}
            style={{ opacity: commentText.trim() && !submitting ? 1 : 0.4 }}
          >
            发送
          </div>
        </div>

        <div className={styles.bottomBar}>
          <div className={styles.bottomBox} onClick={handleLike}>
            <svg viewBox="0 0 1024 1024" width="26" height="26" fill={blog.isLike ? '#ff6633' : '#82848a'}>
              <path d="M160 944c0 8.8-7.2 16-16 16h-32c-26.5 0-48-21.5-48-48V528c0-26.5 21.5-48 48-48h32c8.8 0 16 7.2 16 16v448zM96 416c-53 0-96 43-96 96v416c0 53 43 96 96 96h96c17.7 0 32-14.3 32-32V448c0-17.7-14.3-32-32-32H96zM505.6 64c16.2 0 26.4 8.7 31 13.9 4.6 5.2 12.1 16.3 10.3 32.4l-23.5 203.4c-4.9 42.2 8.6 84.6 36.8 116.4 28.3 31.7 68.9 49.9 111.4 49.9h271.2c6.6 0 10.8 3.3 13.2 6.1s5 7.5 4 14l-48 303.4c-6.9 43.6-29.1 83.4-62.7 112C815.8 944.2 773 960 728.9 960h-317c-33.1 0-59.9-26.8-59.9-59.9v-455c0-6.1 1.7-12 5-17.1 69.5-109 106.4-234.2 107-364h41.6z m0-64h-44.9C427.2 0 400 27.2 400 60.7c0 127.1-39.1 251.2-112 355.3v484.1c0 68.4 55.5 123.9 123.9 123.9h317c122.7 0 227.2-89.3 246.3-210.5l47.9-303.4c7.8-49.4-30.4-94.1-80.4-94.1H671.6c-50.9 0-90.5-44.4-84.6-95l23.5-203.4C617.7 55 568.7 0 505.6 0z" />
            </svg>
            <span className={blog.isLike ? styles.liked : ''}>{blog.liked}</span>
          </div>
          <div className={styles.bottomBox} onClick={scrollToComments}>
            <svg viewBox="0 0 1024 1024" width="26" height="26" fill="#82848a">
              <path d="M128 128h768v576H128V128zm0-64C92.8 64 64 92.8 64 128v576c0 35.2 28.8 64 64 64h256l128 192 128-192h256c35.2 0 64-28.8 64-64V128c0-35.2-28.8-64-64-64H128z" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
