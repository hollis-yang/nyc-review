import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Tabs, Toast } from 'antd-mobile';
import { getUserById, getUserInfo, getMeOptional } from '../../api/user';
import { getBlogsOfUser } from '../../api/blog';
import { isFollowed, follow, getCommonFollows } from '../../api/follow';
import FootBar from '../../components/FootBar';
import { useTranslation } from 'react-i18next';
import { NoteVisual } from '../../components/MerchantVisual';
import styles from './OtherProfile.module.css';

interface UserInfo {
  id: number;
  nickName: string;
  icon: string;
}

interface DetailInfo {
  introduce?: string;
  gender?: boolean;
  city?: string;
  birthday?: string;
}

interface ProfileBlog {
  id: number;
  shopId?: number;
  typeId?: number;
  images?: string;
  sourceType?: string;
  title: string;
  liked: number;
  comments?: number;
}

interface CommonFollow {
  id: number;
  nickName: string;
  icon?: string;
}

export default function OtherProfile() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [info, setInfo] = useState<DetailInfo>({});
  const [blogs, setBlogs] = useState<ProfileBlog[]>([]);
  const [followed, setFollowed] = useState(false);
  const [commonFollows, setCommonFollows] = useState<CommonFollow[]>([]);
  const [activeTab, setActiveTab] = useState('1');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const resetTimer = window.setTimeout(() => {
      setUser(null);
      setInfo({});
      setBlogs([]);
      setFollowed(false);
      setCommonFollows([]);
      setActiveTab('1');
      setError(null);
    }, 0);
    Promise.all([
      getUserById(id).then((res) => {
        const u = res.data ?? res;
        setUser(u);
        getUserInfo(u.id)
          .then((r) => setInfo(r.data ?? r))
          .catch(() => {});
        getBlogsOfUser(u.id)
          .then((r) => setBlogs(r.data ?? r))
          .catch(() => {});
      }),
      getMeOptional()
        .then(() => isFollowed(id))
        .then((r) => setFollowed(r.data ?? r))
        .catch(() => {}),
    ]).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t('otherProfile.notFound'));
    });
    return () => window.clearTimeout(resetTimer);
  }, [id, t]);

  const handleFollow = async () => {
    if (!user) return;
    try {
      await follow(user.id, !followed);
      Toast.show({ icon: 'success', content: followed ? t('otherProfile.unfollowedToast') : t('otherProfile.followedToast') });
      setFollowed(!followed);
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === '2' && user) {
      getCommonFollows(user.id)
        .then((res) => setCommonFollows(res.data ?? res))
        .catch(() => {});
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <button type="button" className={styles.backBtn} onClick={handleBack} aria-label={t('auth.back')}>
          <LeftOutline fontSize={18} color="white" />
        </button>
        <div className={styles.headerTitle}>
          {user ? t('otherProfile.title', { name: user.nickName }) : ''}
        </div>
      </div>

      {error && <div className={styles.loadingFull}>{error}</div>}
      {!error && !user && <div className={styles.loadingFull}>{t('otherProfile.loading')}</div>}
      {user && (
        <div className={styles.scroll}>
          {/* 个人信息卡片 */}
          <div className={styles.profileCard}>
            <div className={styles.profileTop}>
              <div className={styles.avatar}>
                <img src={user.icon || '/imgs/icons/default-icon.png'} alt="" />
              </div>
              <div className={styles.profileInfo}>
                <div className={styles.userName}>{user.nickName}</div>
                <div className={styles.userMeta}>
                  {info.city || t('profile.city')}
                  {info.introduce ? ` · ${info.introduce}` : ''}
                </div>
              </div>
              <button
                type="button"
                className={`${styles.followBtn} ${followed ? styles.followBtnUnfollow : ''}`}
                onClick={handleFollow}
              >
                {followed ? t('otherProfile.followed') : t('otherProfile.follow')}
              </button>
            </div>
            {!info.introduce && !info.city && (
              <div className={styles.introRow}>{t('otherProfile.emptyIntro')}</div>
            )}
          </div>

          {/* 内容卡片（笔记 / 共同关注） */}
          <div className={styles.contentCard}>
            <Tabs activeKey={activeTab} onChange={handleTabChange}>
              <Tabs.Tab title={t('otherProfile.notes')} key="1">
                <div className={styles.tabContent}>
                  {blogs.map((b) => (
                    <button
                      type="button"
                      key={b.id}
                      className={styles.blogItem}
                      onClick={() => navigate(`/blog-detail/${b.id}`)}
                    >
                      <div className={styles.blogItemImg}>
                        <NoteVisual
                          blogId={b.id}
                          shopId={b.shopId}
                          typeId={b.typeId}
                          images={b.images}
                          sourceType={b.sourceType}
                          alt={b.title}
                          loading="lazy"
                        />
                      </div>
                      <div className={styles.blogItemInfo}>
                        <div className={styles.blogItemTitle}>{b.title}</div>
                        <div className={styles.blogItemMeta}>
                          <span>👍 {b.liked}</span>
                          <span>💬 {b.comments ?? 0}</span>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </Tabs.Tab>
              <Tabs.Tab title={t('otherProfile.commonFollows')} key="2">
                <div className={styles.tabContent}>
                  <div className={styles.commonFollowHint}>{t('otherProfile.commonHint')}</div>
                  {commonFollows.map((u) => (
                    <div key={u.id} className={styles.followItem}>
                      <button
                        type="button"
                        className={styles.followIcon}
                        onClick={() => navigate(`/user/${u.id}`)}
                        aria-label={`${u.nickName}: ${t('otherProfile.visitProfile')}`}
                      >
                        <img src={u.icon || '/imgs/icons/default-icon.png'} alt="" />
                      </button>
                      <div className={styles.followName}>{u.nickName}</div>
                      <button
                        type="button"
                        className={styles.followVisitBtn}
                        onClick={() => navigate(`/user/${u.id}`)}
                      >
                        {t('otherProfile.visitProfile')}
                      </button>
                    </div>
                  ))}
                </div>
              </Tabs.Tab>
            </Tabs>
          </div>
        </div>
      )}

      <FootBar activeBtn={0} />
    </div>
  );
}
