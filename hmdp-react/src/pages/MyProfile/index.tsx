import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Tabs, Toast } from 'antd-mobile';
import { useAuth } from '../../hooks/useAuth';
import { getMe, getUserInfo, sign, signCount } from '../../api/user';
import { useTranslation } from 'react-i18next';
import { getBlogsOfMe, getBlogsOfFollow, likeBlog, getBlogById } from '../../api/blog';
import FeedCard from '../../components/FeedCard';
import FootBar from '../../components/FootBar';
import type { BlogData } from '../../components/BlogCard';
import styles from './MyProfile.module.css';

export default function MyProfile() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { logout } = useAuth();
  const [user, setUser] = useState<{ id: number; nickName: string; icon: string } | null>(null);
  const [info, setInfo] = useState<{ introduce?: string; followee?: number; fans?: number; city?: string }>({});
  const [blogs, setBlogs] = useState<BlogData[]>([]);
  const [followBlogs, setFollowBlogs] = useState<BlogData[]>([]);
  const [activeTab, setActiveTab] = useState('1');
  const [params, setParams] = useState({ minTime: 0, offset: 0 });
  const [loading, setLoading] = useState(false);
  const [signDays, setSignDays] = useState(0);
  const [signedToday, setSignedToday] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getMe()
      .then((res) => {
        const u = res.data ?? res;
        setUser(u);
        getUserInfo(u.id)
          .then((r) => {
            const infoData = r.data ?? r;
            if (infoData) {
              setInfo(infoData);
              sessionStorage.setItem('userInfo', JSON.stringify(infoData));
            }
          })
          .catch(() => {});
        getBlogsOfMe()
          .then((r) => setBlogs(r.data ?? r))
          .catch(() => {});
      })
      .catch(() => {
        navigate('/login');
      });
  }, [navigate]);

  useEffect(() => {
    const checkSign = () => {
      signCount()
        .then((res) => {
          const count = res.data ?? res;
          if (typeof count === 'number' && count > 0) {
            setSignDays(count);
            setSignedToday(true);
          } else {
            setSignDays(0);
            setSignedToday(false);
          }
        })
        .catch(() => {});
    };
    checkSign();
    const onVisible = () => { if (document.visibilityState === 'visible') checkSign(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  const loadFollowBlogs = useCallback(async (clear = false) => {
    if (loading) return;
    setLoading(true);
    try {
      const p = clear
        ? { offset: 0, lastId: Date.now() + 1 }
        : { offset: params.offset, lastId: params.minTime || Date.now() + 1 };
      const res = await getBlogsOfFollow(p);
      const data = res.data ?? res;
      if (!data) return;
      const { list, ...rest } = data;
      const enriched = (list || []).map((b: BlogData) => ({
        ...b,
        img: b.images ? b.images.split(',')[0] : '',
      }));
      setFollowBlogs(clear ? enriched : (prev) => [...prev, ...enriched]);
      setParams(rest);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [params, loading]);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === '4') {
      loadFollowBlogs(true);
    }
  };

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, offsetHeight, scrollHeight } = el;
    if (scrollTop === 0) {
      loadFollowBlogs(true);
    } else if (scrollTop + offsetHeight + 1 > scrollHeight && !loading) {
      loadFollowBlogs();
    }
  }, [loadFollowBlogs, loading]);

  const handleLikeUpdate = async (blogId: number) => {
    try {
      await likeBlog(blogId);
      const r = await getBlogById(blogId);
      const data = r.data ?? r;
      setFollowBlogs((prev) =>
        prev.map((b) =>
          b.id === blogId ? { ...b, liked: data.liked, isLike: data.isLike } : b
        )
      );
    } catch {
      // ignore
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleSign = async () => {
    try {
      await sign();
      const res = await signCount();
      const count = res.data ?? res;
      setSignDays(typeof count === 'number' ? count : 0);
      setSignedToday(true);
      Toast.show({ icon: 'success', content: t('sign.success') });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.headerTitle}>{t('profile.title')}</div>
      </div>

      {user && (
        <div className={styles.profileCard}>
          <div className={styles.profileTop}>
            <div className={styles.avatarWrap}>
              <img src={user.icon || '/imgs/icons/default-icon.png'} alt="" />
            </div>
            <div className={styles.profileInfo}>
              <div className={styles.nickName}>{user.nickName}</div>
              <div className={styles.city}>{info.city || t('profile.notSet')}</div>
              <div className={styles.intro}>
                {info.introduce || t('profile.defaultIntro')}
              </div>
              <div className={styles.actions}>
                <div className={styles.editBtn} onClick={() => navigate('/profile-edit')}>
                  编辑资料
                </div>
                <div className={styles.logoutBtn} onClick={handleLogout}>
                  退出登录
                </div>
              </div>
            </div>
          </div>
          <div className={styles.stats}>
            <div className={styles.statItem}>
              <div className={styles.statNum}>{blogs.length}</div>
              <div className={styles.statLabel}>{t('profile.notes')}</div>
            </div>
            <div className={styles.statDivider} />
            <div className={styles.statItem}>
              <div className={styles.statNum}>{info.followee || 0}</div>
              <div className={styles.statLabel}>{t('profile.following')}</div>
            </div>
          </div>
          <div className={styles.signSection}>
            {signedToday ? (
              <div className={styles.signedBadge}>
                ✅ 已签到 <span className={styles.signDaysNum}>{signDays}</span> 天
              </div>
            ) : (
              <div className={styles.signBtn} onClick={handleSign}>
                {t('profile.signIn')}
              </div>
            )}
          </div>
        </div>
      )}

      <div className={styles.content}>
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          style={{
            '--active-line-color': '#ff6633',
            '--active-title-color': '#ff6633',
          } as React.CSSProperties}
        >
          <Tabs.Tab title="笔记" key="1">
            <div className={styles.tabContent}>
              {blogs.map((b) => (
                <div
                  key={b.id}
                  className={styles.blogItem}
                  onClick={() => navigate(`/blog-detail/${b.id}`)}
                >
                  <div className={styles.blogItemImg}>
                    <img
                      src={b.images ? b.images.split(',')[0] : ''}
                      alt=""
                    />
                  </div>
                  <div className={styles.blogItemInfo}>
                    <div className={styles.blogItemTitle}>{b.title}</div>
                    <div className={styles.blogItemMeta}>
                      <span>👍 {b.liked}</span>
                      <span style={{ marginLeft: 10 }}>💬 {b.comments ?? 0}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Tabs.Tab>
          <Tabs.Tab title="关注" key="4">
            <div className={styles.tabContent} onScroll={handleScroll} ref={containerRef}>
              {followBlogs.map((b) => (
                <FeedCard
                  key={b.id}
                  blog={b}
                  onLikeUpdate={() => handleLikeUpdate(b.id)}
                />
              ))}
              {loading && <div className={styles.loadingMore}>{t('home.loading')}</div>}
            </div>
          </Tabs.Tab>
        </Tabs>
      </div>

      <FootBar activeBtn={4} />
    </div>
  );
}
