import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Toast, Dialog } from 'antd-mobile';
import { useTranslation } from 'react-i18next';
import { getBlogById, getFollowingBlogLikes, likeBlog, getBlogComments, createBlogComment, deleteBlog, deleteBlogComment } from '../../api/blog';
import { translateBlog, translateComment } from '../../api/translate';
import { getShopById } from '../../api/shop';
import { getMeOptional } from '../../api/user';
import { isFollowed, follow } from '../../api/follow';
import ImageSwiper from '../../components/ImageSwiper';
import MerchantVisual from '../../components/MerchantVisual';
import { useAuth } from '../../hooks/useAuth';
import { normalizeBlogContent } from '../../utils/blogContent';
import { cleanDisplayContent } from '../../utils/displayContent';
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
  sourceType?: string;
}

interface ShopInfo {
  id: number;
  image: string;
  images?: string;
  name: string;
  score: number;
  avgPrice: number;
  typeId?: number;
}

interface CommentInfo {
  id: number;
  userId: number;
  icon: string;
  name: string;
  content: string;
  liked: number;
  createTime: string;
  parentId: number;
  answerId: number;
  replyToName?: string;
  sourceType?: string;
  children: CommentInfo[];
}

export default function BlogDetail() {
  const { id } = useParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [blog, setBlog] = useState<BlogInfo | null>(null);
  const [shop, setShop] = useState<ShopInfo | null>(null);
  const [followingLikes, setFollowingLikes] = useState<{ id: number; icon: string; nickName: string }[]>([]);
  const [comments, setComments] = useState<CommentInfo[]>([]);
  const [currentUser, setCurrentUser] = useState<{ id: number } | null>(null);
  const [followed, setFollowed] = useState(false);
  const [followPending, setFollowPending] = useState(false);
  const followLockRef = useRef<number | null>(null);
  const [likePending, setLikePending] = useState(false);
  const likeLockRef = useRef<number | null>(null);
  const [error, setError] = useState<{ routeId: string; message: string } | null>(null);
  const [commentText, setCommentText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const commentSubmitLockRef = useRef<number | null>(null);
  const [replyTo, setReplyTo] = useState<CommentInfo | null>(null);
  const [replyText, setReplyText] = useState('');
  const [replySubmitting, setReplySubmitting] = useState(false);
  const replySubmitLockRef = useRef<number | null>(null);
  const [blogTL, setBlogTL] = useState<string | null>(null);
  const [blogTitleTL, setBlogTitleTL] = useState<string | null>(null);
  const [blogTLLoading, setBlogTLLoading] = useState(false);
  const blogTranslationLockRef = useRef<number | null>(null);
  const [commentTL, setCommentTL] = useState<Record<number, string>>({});
  const [commentTranslationBusy, setCommentTranslationBusy] = useState<Set<number>>(new Set());
  const commentTranslationLocksRef = useRef(new Map<number, number>());
  const routeGenerationRef = useRef(0);
  const activeRouteIdRef = useRef<string | null>(id ?? null);

  useEffect(() => {
    const routeId = id;
    const generation = ++routeGenerationRef.current;
    activeRouteIdRef.current = routeId ?? null;
    followLockRef.current = null;
    likeLockRef.current = null;
    commentSubmitLockRef.current = null;
    replySubmitLockRef.current = null;
    blogTranslationLockRef.current = null;
    commentTranslationLocksRef.current.clear();

    const timer = window.setTimeout(() => {
      if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
      setBlog(null);
      setShop(null);
      setFollowingLikes([]);
      setComments([]);
      setCurrentUser(null);
      setFollowed(false);
      setFollowPending(false);
      setLikePending(false);
      setError(null);
      setCommentText('');
      setSubmitting(false);
      setReplyTo(null);
      setReplyText('');
      setReplySubmitting(false);
      setBlogTL(null);
      setBlogTitleTL(null);
      setBlogTLLoading(false);
      setCommentTL({});
      setCommentTranslationBusy(new Set());

      if (!routeId) {
        setError({ routeId: '', message: t('blogDetail.notFound') });
        return;
      }

      void (async () => {
        try {
          const response = await getBlogById(routeId);
          if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
          const raw = response.data ?? response;
          const data: BlogInfo = {
            ...raw,
            images: raw.images ? raw.images.split(',') : [],
          };
          setBlog(data);

          if (data.shopId) {
            void getShopById(data.shopId)
              .then((shopResponse) => {
                if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
                const rawShop = shopResponse.data ?? shopResponse;
                setShop({
                  ...rawShop,
                  image: rawShop.images ? rawShop.images.split(',')[0] : '',
                });
              })
              .catch(() => {});
          }

          void getBlogComments(routeId)
            .then((commentsResponse) => {
              if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
                setComments(commentsResponse.data ?? commentsResponse);
              }
            })
            .catch(() => {});

          void getMeOptional()
            .then(async (userResponse) => {
              if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
              const user = userResponse.data ?? userResponse;
              if (!user?.id) return;
              setCurrentUser(user);
              const [likesResult, followedResult] = await Promise.allSettled([
                getFollowingBlogLikes(routeId),
                user.id !== data.userId ? isFollowed(data.userId) : Promise.resolve(null),
              ]);
              if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
              if (likesResult.status === 'fulfilled') {
                setFollowingLikes(likesResult.value.data ?? likesResult.value);
              }
              if (followedResult.status === 'fulfilled' && followedResult.value != null) {
                setFollowed(followedResult.value.data ?? followedResult.value);
              }
            })
            .catch(() => {});
        } catch (loadError: unknown) {
          if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
          const message = loadError instanceof Error ? loadError.message : String(loadError);
          setError({ routeId, message: message || t('blogDetail.notFound') });
        }
      })();
    }, 0);

    return () => {
      window.clearTimeout(timer);
      if (routeGenerationRef.current === generation) routeGenerationRef.current += 1;
    };
  }, [id, t]);

  const handleLike = async () => {
    if (!blog || !id) return;
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (likeLockRef.current === generation) return;
    likeLockRef.current = generation;
    setLikePending(true);
    try {
      try {
        await likeBlog(blog.id);
      } catch {
        if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
          Toast.show({ icon: 'fail', content: t('common.actionFailed') });
        }
        return;
      }
      if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
      setBlog((current) => current && current.id === blog.id
        ? {
            ...current,
            isLike: !current.isLike,
            liked: Math.max(0, current.liked + (current.isLike ? -1 : 1)),
          }
        : current);
      try {
        const res = await getBlogById(blog.id);
        if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
        const data = res.data ?? res;
        data.images = data.images ? data.images.split(',') : [];
        setBlog(data);
        if (currentUser) {
          const followedLikesRes = await getFollowingBlogLikes(blog.id);
          if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
            setFollowingLikes(followedLikesRes.data ?? followedLikesRes);
          }
        }
      } catch {
        // The toggle succeeded; retain the local result if refresh is unavailable.
      }
    } finally {
      if (likeLockRef.current === generation) likeLockRef.current = null;
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setLikePending(false);
      }
    }
  };

  const handleFollow = async () => {
    if (!blog || !id) return;
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (followLockRef.current === generation) return;
    followLockRef.current = generation;
    setFollowPending(true);
    const nextFollowed = !followed;
    try {
      await follow(blog.userId, nextFollowed);
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'success', content: nextFollowed ? t('blogDetail.followed') : t('blogDetail.unfollowed') });
        setFollowed(nextFollowed);
      }
    } catch {
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('common.actionFailed') });
      }
    } finally {
      if (followLockRef.current === generation) followLockRef.current = null;
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setFollowPending(false);
      }
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
      try { await navigator.share({ title: blog?.title ?? t('blogDetail.title'), url }); } catch {}
    } else {
      await navigator.clipboard.writeText(url);
      Toast.show({ icon: 'success', content: t('blogDetail.linkCopied') });
    }
  };

  const refreshComments = async (routeId: string, generation: number): Promise<boolean> => {
    const res = await getBlogComments(routeId);
    if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return false;
    setComments(res.data ?? res);
    const blogRes = await getBlogById(routeId);
    if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return false;
    const data = blogRes.data ?? blogRes;
    if (data) {
      data.images = data.images ? data.images.split(',') : [];
      setBlog(data);
    }
    return true;
  };

  const handleCommentSubmit = async () => {
    if (!commentText.trim() || !id || submitting) return;
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (commentSubmitLockRef.current === generation) return;
    commentSubmitLockRef.current = generation;
    setSubmitting(true);
    try {
      await createBlogComment({ blogId: Number(routeId), content: commentText.trim() });
      if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
      setCommentText('');
      try {
        if (await refreshComments(routeId, generation)) {
          Toast.show({ icon: 'success', content: t('blogDetail.commentSuccess') });
        }
      } catch {
        if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
          Toast.show({ icon: 'success', content: t('blogDetail.commentSuccessRefreshFailed') });
        }
      }
    } catch {
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('common.actionFailed') });
      }
    } finally {
      if (commentSubmitLockRef.current === generation) commentSubmitLockRef.current = null;
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setSubmitting(false);
      }
    }
  };

  const handleInlineReply = async () => {
    if (!replyText.trim() || !replyTo || !id || replySubmitting) return;
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (replySubmitLockRef.current === generation) return;
    replySubmitLockRef.current = generation;
    setReplySubmitting(true);
    try {
      const parentId = replyTo.parentId > 0 ? replyTo.parentId : replyTo.id;
      const answerId = replyTo.id;
      await createBlogComment({
        blogId: Number(routeId),
        content: replyText.trim(),
        parentId,
        answerId,
      });
      if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
      setReplyTo(null);
      setReplyText('');
      try {
        if (await refreshComments(routeId, generation)) {
          Toast.show({ icon: 'success', content: t('blogDetail.replySuccess') });
        }
      } catch {
        if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
          Toast.show({ icon: 'success', content: t('blogDetail.replySuccessRefreshFailed') });
        }
      }
    } catch {
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('common.actionFailed') });
      }
    } finally {
      if (replySubmitLockRef.current === generation) replySubmitLockRef.current = null;
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setReplySubmitting(false);
      }
    }
  };

  const handleTranslateBlog = async () => {
    if (!blog || !id) return;
    if (blogTL) { setBlogTL(null); setBlogTitleTL(null); return; }
    if (!isAuthenticated) {
      Toast.show({ icon: 'fail', content: t('blogDetail.translationLoginRequired') });
      return;
    }
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (blogTranslationLockRef.current === generation) return;
    blogTranslationLockRef.current = generation;
    setBlogTLLoading(true);
    try {
      const res = await translateBlog(blog.id, 'zh-CN');
      if (routeGenerationRef.current !== generation || activeRouteIdRef.current !== routeId) return;
      const full = String(res.data ?? res);
      const parts = full.split('\n\n');
      if (parts.length >= 2) {
        setBlogTitleTL(parts[0].trim());
        setBlogTL(parts.slice(1).join('\n\n').trim());
      } else {
        setBlogTL(full);
      }
    } catch {
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('blogDetail.translationFailed') });
      }
    }
    finally {
      if (blogTranslationLockRef.current === generation) blogTranslationLockRef.current = null;
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setBlogTLLoading(false);
      }
    }
  };

  const handleTranslateComment = async (comment: CommentInfo) => {
    if (commentTL[comment.id]) {
      setCommentTL((current) => {
        const next = { ...current };
        delete next[comment.id];
        return next;
      });
      return;
    }
    if (!id) return;
    if (!isAuthenticated) {
      Toast.show({ icon: 'fail', content: t('blogDetail.translationLoginRequired') });
      return;
    }
    const routeId = id;
    const generation = routeGenerationRef.current;
    if (commentTranslationLocksRef.current.get(comment.id) === generation) return;
    commentTranslationLocksRef.current.set(comment.id, generation);
    setCommentTranslationBusy((current) => new Set(current).add(comment.id));
    try {
      const res = await translateComment(comment.id, 'zh-CN');
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setCommentTL((current) => ({ ...current, [comment.id]: String(res.data ?? res) }));
      }
    } catch {
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        Toast.show({ icon: 'fail', content: t('blogDetail.translationFailed') });
      }
    } finally {
      if (commentTranslationLocksRef.current.get(comment.id) === generation) {
        commentTranslationLocksRef.current.delete(comment.id);
      }
      if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
        setCommentTranslationBusy((current) => {
          const next = new Set(current);
          next.delete(comment.id);
          return next;
        });
      }
    }
  };

  const handleDelete = () => {
    if (!blog || !id) return;
    const routeId = id;
    const generation = routeGenerationRef.current;
    Dialog.confirm({
      content: t('blogDetail.deleteNoteConfirm'),
      cancelText: t('blogDetail.cancel'),
      confirmText: t('blogDetail.confirm'),
      onConfirm: async () => {
        try {
          await deleteBlog(blog.id);
          if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
            Toast.show({ icon: 'success', content: t('blogDetail.deleted') });
            navigate(-1);
          }
        } catch {
          if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
            Toast.show({ icon: 'fail', content: t('common.actionFailed') });
          }
        }
      },
    });
  };

  /* ---- 渲染 ---- */

  if (error?.routeId === (id ?? '')) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div data-mobile-context-back="true" className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={20} color="#fff" />
          </div>
          <div className={styles.title}>{t('blogDetail.title')}</div>
          <div className={styles.share} />
        </div>
        <div className={styles.loadingFull}>{error.message}</div>
      </div>
    );
  }

  if (!blog || String(blog.id) !== id) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div data-mobile-context-back="true" className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={20} color="#fff" />
          </div>
          <div className={styles.title}>{t('blogDetail.title')}</div>
          <div className={styles.share} />
        </div>
        <div className={styles.loadingFull}>{t('blogDetail.loading')}</div>
      </div>
    );
  }

  const formatDate = (d: string) => {
    const date = new Date(d);
    return new Intl.DateTimeFormat(isChinese ? 'zh-CN' : 'en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
    }).format(date);
  };

  const formatDateTime = (d: string) => {
    const date = new Date(d);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hour}:${min}`;
  };

  const handleAuthorClick = () => {
    if (blog.userId === currentUser?.id) {
      navigate('/profile');
    } else {
      navigate(`/user/${blog.userId}`);
    }
  };

  const hasCommented = currentUser && comments.some((c) => c.userId === currentUser.id);

  const countTree = (list: CommentInfo[]): number =>
    list.reduce((s, c) => s + 1 + countTree(c.children), 0);
  const totalCommentCount = countTree(comments);

  const renderComment = (c: CommentInfo, depth: number): JSX.Element => (
    <div key={c.id}>
      <div className={`${styles.commentItem} ${depth === 1 ? styles.commentNested : ''} ${depth > 1 ? styles.commentNestedDeep : ''}`}>
        <div className={styles.commentIcon}>
          <img src={c.icon || '/imgs/icons/default-icon.png'} alt="" />
        </div>
        <div className={styles.commentInfo}>
          <div className={styles.commentHeading}>
            <div className={styles.commentUser}>{c.name}</div>
          </div>
          {c.replyToName && (
            <span className={styles.replyToTag}>{t('blogDetail.replyTo')} @{c.replyToName}</span>
          )}
          <div className={styles.commentContent}>{cleanDisplayContent(c.content)}</div>
          {commentTL[c.id] && (
            <div style={{ background: '#f0f7ff', padding: '6px 8px', borderRadius: 6, margin: '4px 0', fontSize: 12, color: '#555' }}>
              {commentTL[c.id]}
            </div>
          )}
          <div className={styles.commentActions}>
            <div className={styles.commentActionGroup}>
              <div className={styles.commentTime}>{formatDateTime(c.createTime)}</div>
              {currentUser && (
                <span className={styles.replyBtn} onClick={() => { setReplyTo(c); setReplyText(''); }}>
                  {t('blogDetail.reply')}
                </span>
              )}
              {isChinese && (
                <button
                  type="button"
                  className={`${styles.replyBtn} ${styles.translationAction}`}
                  disabled={commentTranslationBusy.has(c.id)}
                  onClick={() => void handleTranslateComment(c)}
                >
                  ✦ {commentTranslationBusy.has(c.id)
                    ? t('blogDetail.translatingAI')
                    : t('blogDetail.aiTranslate')}
                </button>
              )}
            </div>
            {currentUser && currentUser.id === c.userId && (
              <div
                className={styles.deleteCommentButton}
                onClick={() => {
                  if (!id) return;
                  const routeId = id;
                  const generation = routeGenerationRef.current;
                  Dialog.confirm({
                    content: t('blogDetail.deleteCommentConfirm'),
                    cancelText: t('blogDetail.cancel'),
                    confirmText: t('blogDetail.confirm'),
                    onConfirm: async () => {
                      try {
                        await deleteBlogComment(c.id);
                        await refreshComments(routeId, generation);
                      } catch {
                        if (routeGenerationRef.current === generation && activeRouteIdRef.current === routeId) {
                          Toast.show({ icon: 'fail', content: t('common.actionFailed') });
                        }
                      }
                    },
                  });
                }}
              >×</div>
            )}
          </div>
          {/* 行内回复框 */}
          {replyTo?.id === c.id && (
            <div className={styles.inlineReplyBar}>
              <span className={styles.replyToTag}>{t('blogDetail.replyTo')} @{c.name}:</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                <input
                  type="text"
                  value={replyText}
                  disabled={replySubmitting}
                  onChange={(e) => setReplyText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleInlineReply(); }}
                  placeholder={`${t('blogDetail.replyTo')} ${c.name}...`}
                  className={styles.inlineReplyInput}
                />
                <button
                  type="button"
                  className={styles.commentSubmit}
                  disabled={!replyText.trim() || replySubmitting}
                  onClick={handleInlineReply}
                >
                  {replySubmitting ? t('shopDetail.submitting') : t('blogDetail.send')}
                </button>
                <button
                  type="button"
                  className={styles.cancelReply}
                  disabled={replySubmitting}
                  onClick={() => setReplyTo(null)}
                >
                  {t('blogDetail.cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      {c.children && c.children.length > 0 && c.children.map((child) => renderComment(child, depth + 1))}
    </div>
  );

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div data-mobile-context-back="true" className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={20} color="#fff" />
        </div>
        <div className={styles.title}>{t('blogDetail.title')}</div>
        <div className={styles.share} onClick={handleShare}>
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="5" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
            <circle cx="12" cy="12" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
            <circle cx="12" cy="19" r="1.2" fill="rgba(255,255,255,0.85)" stroke="none" />
          </svg>
        </div>
        {currentUser && currentUser.id === blog.userId && (
          <div className={styles.share} onClick={handleDelete}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </div>
        )}
      </div>

      <div className={styles.scroll}>
        <div className={styles.detailLayout}>
        {/* 图片卡片：Swiper + 作者信息 */}
        <div className={styles.imageCard}>
          <ImageSwiper
            images={blog.images}
            blogId={blog.id}
            shopId={blog.shopId}
            shopName={shop?.name}
            typeId={shop?.typeId}
            sourceType={blog.sourceType}
          />
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
                <button
                  type="button"
                  className={styles.followBtn}
                  onClick={handleFollow}
                  disabled={followPending}
                  aria-busy={followPending}
                >
                  {followed ? t('blogDetail.unfollow') : t('blogDetail.follow')}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* 正文卡片 */}
        <div className={styles.contentCard}>
          {blog.title && (
            <div className={styles.contentTitle}>{blog.title}</div>
          )}
          {blogTitleTL && (
            <div style={{ fontSize: 14, color: '#888', marginTop: 2, marginBottom: 8 }}>
              {blogTitleTL}
            </div>
          )}
          <div className={styles.contentBody}>
            {normalizeBlogContent(blog.content)}
          </div>
          {isChinese && <div style={{ padding: '4px 0 8px', textAlign: 'right' }}>
            <span style={{ fontSize: 12, color: '#999', cursor: 'pointer' }}
              onClick={handleTranslateBlog}>
              {blogTLLoading ? t('blogDetail.translatingAI') : blogTL ? t('blogDetail.original') : `✦ ${t('blogDetail.aiTranslate')}`}
            </span>
          </div>}
          {blogTL && (
            <div style={{ background: '#f0f7ff', padding: 10, borderRadius: 8, margin: '0 0 10px', fontSize: 14, color: '#444', lineHeight: 1.7 }}>
              <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>💬 {t('blogDetail.translatedByAI')}</div>
              {blogTL}
            </div>
          )}
        </div>

        <aside className={styles.sideRail}>
        {/* 关联商铺卡片 */}
        {shop && (
          <div className={styles.shopBasic} onClick={() => navigate(`/shop-detail/${shop.id}`)}>
            <div className={styles.shopIcon}>
              <MerchantVisual
                shopId={shop.id}
                name={shop.name}
                typeId={shop.typeId}
                images={shop.images || shop.image}
                alt={shop.name}
                loading="lazy"
              />
            </div>
            <div className={styles.shopInfo}>
              <div className={styles.shopName}>{shop.name}</div>
              <span style={{ fontSize: 12, color: '#F63', fontWeight: 600 }}>
                ★ {shop.score / 10}
              </span>
              <div className={styles.shopAvg}>${shop.avgPrice}{t('shopCard.perPerson')}</div>
            </div>
          </div>
        )}

        {/* 点赞卡片 */}
        <div className={styles.zanBox}>
          <button
            type="button"
            className={styles.likeIconWrapper}
            onClick={handleLike}
            disabled={likePending}
            aria-busy={likePending}
            aria-label={t('shopDetail.like', { n: blog.liked })}
          >
            <svg viewBox="0 0 1024 1024" width="22" height="22" fill={blog.isLike ? '#ff6633' : '#82848a'}>
              <path d="M160 944c0 8.8-7.2 16-16 16h-32c-26.5 0-48-21.5-48-48V528c0-26.5 21.5-48 48-48h32c8.8 0 16 7.2 16 16v448zM96 416c-53 0-96 43-96 96v416c0 53 43 96 96 96h96c17.7 0 32-14.3 32-32V448c0-17.7-14.3-32-32-32H96zM505.6 64c16.2 0 26.4 8.7 31 13.9 4.6 5.2 12.1 16.3 10.3 32.4l-23.5 203.4c-4.9 42.2 8.6 84.6 36.8 116.4 28.3 31.7 68.9 49.9 111.4 49.9h271.2c6.6 0 10.8 3.3 13.2 6.1s5 7.5 4 14l-48 303.4c-6.9 43.6-29.1 83.4-62.7 112C815.8 944.2 773 960 728.9 960h-317c-33.1 0-59.9-26.8-59.9-59.9v-455c0-6.1 1.7-12 5-17.1 69.5-109 106.4-234.2 107-364h41.6z m0-64h-44.9C427.2 0 400 27.2 400 60.7c0 127.1-39.1 251.2-112 355.3v484.1c0 68.4 55.5 123.9 123.9 123.9h317c122.7 0 227.2-89.3 246.3-210.5l47.9-303.4c7.8-49.4-30.4-94.1-80.4-94.1H671.6c-50.9 0-90.5-44.4-84.6-95l23.5-203.4C617.7 55 568.7 0 505.6 0z" />
            </svg>
          </button>
          <div className={styles.zanList}>
            <div className={styles.likedCount}>{t('blogDetail.likes', { n: blog.liked })}</div>
            {followingLikes.length > 0 && (
              <div className={styles.followingLiked}>
                <div className={styles.followingLikeAvatars}>
                  {followingLikes.map((user) => (
                    <button
                      type="button"
                      key={user.id}
                      onClick={() => navigate(`/user/${user.id}`)}
                      aria-label={user.nickName}
                    >
                      <img src={user.icon || '/imgs/icons/default-icon.png'} alt="" />
                    </button>
                  ))}
                </div>
                <span>{t('blogDetail.followingLiked', {
                  names: followingLikes.map((user) => user.nickName).join(', '),
                  count: followingLikes.length,
                })}</span>
              </div>
            )}
          </div>
        </div>
        </aside>

        {/* 评论卡片 */}
        <div className={styles.comments} id="comments-section">
          <div className={styles.commentsHead}>
            <div>
              {t('blogDetail.comments')} <span>({totalCommentCount})</span>
            </div>
            <div className={styles.commentsHeadArrow} onClick={scrollToComments}>&gt;</div>
          </div>
          {comments.length > 0 ? (
            comments.map((c) => renderComment(c, 0))
          ) : (
            <div className={styles.commentPlaceholder}>
              <div className={styles.commentPlaceholderIcon}>💬</div>
              <div>{t('blogDetail.noComments')}</div>
            </div>
          )}
        </div>
        </div>
      </div>

      {/* 底部固定区域 */}
      <div className={styles.bottomFrame}>
      <div className={styles.bottomSticky}>
        <div className={styles.commentInputBar}>
          <input
            type="text"
            placeholder={t('blogDetail.commentPlaceholder')}
            value={commentText}
            disabled={submitting}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCommentSubmit(); }}
            className={styles.commentInput}
          />
          <button
            type="button"
            className={styles.commentSubmit}
            onClick={handleCommentSubmit}
            disabled={!commentText.trim() || submitting}
          >
            {submitting ? t('shopDetail.submitting') : t('blogDetail.send')}
          </button>
        </div>

        <div className={styles.bottomBar}>
          <button
            type="button"
            className={styles.bottomBox}
            onClick={handleLike}
            disabled={likePending}
            aria-busy={likePending}
            aria-label={t('shopDetail.like', { n: blog.liked })}
          >
            <svg viewBox="0 0 1024 1024" width="26" height="26" fill={blog.isLike ? '#ff6633' : '#82848a'}>
              <path d="M160 944c0 8.8-7.2 16-16 16h-32c-26.5 0-48-21.5-48-48V528c0-26.5 21.5-48 48-48h32c8.8 0 16 7.2 16 16v448zM96 416c-53 0-96 43-96 96v416c0 53 43 96 96 96h96c17.7 0 32-14.3 32-32V448c0-17.7-14.3-32-32-32H96zM505.6 64c16.2 0 26.4 8.7 31 13.9 4.6 5.2 12.1 16.3 10.3 32.4l-23.5 203.4c-4.9 42.2 8.6 84.6 36.8 116.4 28.3 31.7 68.9 49.9 111.4 49.9h271.2c6.6 0 10.8 3.3 13.2 6.1s5 7.5 4 14l-48 303.4c-6.9 43.6-29.1 83.4-62.7 112C815.8 944.2 773 960 728.9 960h-317c-33.1 0-59.9-26.8-59.9-59.9v-455c0-6.1 1.7-12 5-17.1 69.5-109 106.4-234.2 107-364h41.6z m0-64h-44.9C427.2 0 400 27.2 400 60.7c0 127.1-39.1 251.2-112 355.3v484.1c0 68.4 55.5 123.9 123.9 123.9h317c122.7 0 227.2-89.3 246.3-210.5l47.9-303.4c7.8-49.4-30.4-94.1-80.4-94.1H671.6c-50.9 0-90.5-44.4-84.6-95l23.5-203.4C617.7 55 568.7 0 505.6 0z" />
            </svg>
            <span className={blog.isLike ? styles.liked : ''}>{blog.liked}</span>
          </button>
          <button type="button" className={styles.bottomBox} onClick={scrollToComments}>
            <svg viewBox="0 0 1024 1024" width="26" height="26" fill={hasCommented ? '#ff6633' : '#82848a'}>
              <path d="M128 128h768v576H128V128zm0-64C92.8 64 64 92.8 64 128v576c0 35.2 28.8 64 64 64h256l128 192 128-192h256c35.2 0 64-28.8 64-64V128c0-35.2-28.8-64-64-64H128z" />
            </svg>
            <span className={hasCommented ? styles.liked : ''}>{blog.comments ?? 0}</span>
          </button>
        </div>
      </div>
      </div>
    </div>
  );
}
