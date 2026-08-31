import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BellOutline,
  CheckCircleOutline,
  ContentOutline,
  CouponOutline,
  FillinOutline,
  HeartOutline,
  LeftOutline,
  TravelOutline,
} from 'antd-mobile-icons';
import { Toast } from 'antd-mobile';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../hooks/useAuth';
import { getMe, getUserInfo, sign, signCount } from '../../api/user';
import { getBlogsOfMe } from '../../api/blog';
import { getFollowers, getFollowing } from '../../api/follow';
import {
  deleteAgentMemory,
  getProfileAssets,
  updateAgentMemory,
  type ProfileAssets,
} from '../../api/profile';
import FootBar from '../../components/FootBar';
import type { BlogData } from '../../components/BlogCard';
import MerchantVisual, { NoteVisual } from '../../components/MerchantVisual';
import styles from './MyProfile.module.css';

type ProfileSection =
  | 'notes'
  | 'favorites'
  | 'itineraries'
  | 'vouchers'
  | 'reminders'
  | 'memory'
  | 'followers'
  | 'following';

interface ProfileUserSummary {
  id: number;
  nickName: string;
  icon: string;
}

export default function MyProfile() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { logout } = useAuth();
  const [user, setUser] = useState<{ id: number; nickName: string; icon: string } | null>(null);
  const [info, setInfo] = useState<{ introduce?: string; followee?: number; fans?: number; city?: string }>({});
  const [blogs, setBlogs] = useState<BlogData[]>([]);
  const [followers, setFollowers] = useState<ProfileUserSummary[]>([]);
  const [followersLoaded, setFollowersLoaded] = useState(false);
  const [followersLoading, setFollowersLoading] = useState(false);
  const [following, setFollowing] = useState<ProfileUserSummary[]>([]);
  const [followingLoaded, setFollowingLoaded] = useState(false);
  const [followingLoading, setFollowingLoading] = useState(false);
  const [activeSection, setActiveSection] = useState<ProfileSection>('notes');
  const [signDays, setSignDays] = useState(0);
  const [signedToday, setSignedToday] = useState(false);
  const [assets, setAssets] = useState<ProfileAssets | null>(null);
  const [assetsLoading, setAssetsLoading] = useState(true);
  const [memoryItemDrafts, setMemoryItemDrafts] = useState<Record<number, string[]>>({});

  const applyAssets = (profileAssets: ProfileAssets) => {
    setAssets(profileAssets);
    setMemoryItemDrafts(Object.fromEntries(
      profileAssets.memories.map((memory) => [
        memory.id,
        memory.value.split(',').map((item) => item.trim()).filter(Boolean),
      ])
    ));
  };

  const reloadAssets = async () => {
    const response = await getProfileAssets();
    applyAssets((response.data ?? response) as ProfileAssets);
  };

  useEffect(() => {
    getMe()
      .then((res) => {
        const currentUser = res.data ?? res;
        setUser(currentUser);
        getUserInfo(currentUser.id)
          .then((response) => {
            const infoData = response.data ?? response;
            if (infoData) {
              setInfo(infoData);
              sessionStorage.setItem('userInfo', JSON.stringify(infoData));
            }
          })
          .catch(() => {});
        getBlogsOfMe()
          .then((response) => setBlogs(response.data ?? response))
          .catch(() => {});
        getProfileAssets()
          .then((response) => applyAssets((response.data ?? response) as ProfileAssets))
          .catch(() => setAssets(null))
          .finally(() => setAssetsLoading(false));
      })
      .catch(() => navigate('/login'));
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

  const loadFollowers = useCallback(async () => {
    if (followersLoading || followersLoaded) return;
    setFollowersLoading(true);
    try {
      const response = await getFollowers();
      setFollowers((response.data ?? response) as ProfileUserSummary[]);
      setFollowersLoaded(true);
    } finally {
      setFollowersLoading(false);
    }
  }, [followersLoaded, followersLoading]);

  const loadFollowing = useCallback(async () => {
    if (followingLoading || followingLoaded) return;
    setFollowingLoading(true);
    try {
      const response = await getFollowing();
      setFollowing((response.data ?? response) as ProfileUserSummary[]);
      setFollowingLoaded(true);
    } finally {
      setFollowingLoading(false);
    }
  }, [followingLoaded, followingLoading]);

  const handleSectionChange = (key: ProfileSection) => {
    setActiveSection(key);
    if (key === 'following') loadFollowing();
    if (key === 'followers') loadFollowers();
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
      const response = await signCount();
      const count = response.data ?? response;
      setSignDays(typeof count === 'number' ? count : 0);
      setSignedToday(true);
      Toast.show({ icon: 'success', content: t('sign.success') });
    } catch (error) {
      Toast.show({ icon: 'fail', content: String(error) });
    }
  };

  const saveMemory = async (id: number) => {
    try {
      const value = (memoryItemDrafts[id] || []).map((item) => item.trim()).filter(Boolean).join(', ');
      await updateAgentMemory(id, value);
      await reloadAssets();
      Toast.show({ icon: 'success', content: t('profile.memoryUpdated') });
    } catch (error) {
      Toast.show({ icon: 'fail', content: String(error) });
    }
  };

  const updateMemoryItem = (memoryId: number, itemIndex: number, value: string) => {
    setMemoryItemDrafts((previous) => ({
      ...previous,
      [memoryId]: (previous[memoryId] || []).map((item, index) => index === itemIndex ? value : item),
    }));
  };

  const addMemoryItem = (memoryId: number) => {
    setMemoryItemDrafts((previous) => ({
      ...previous,
      [memoryId]: [...(previous[memoryId] || []), ''],
    }));
  };

  const removeMemoryItem = (memoryId: number, itemIndex: number) => {
    setMemoryItemDrafts((previous) => ({
      ...previous,
      [memoryId]: (previous[memoryId] || []).filter((_, index) => index !== itemIndex),
    }));
  };

  const removeMemory = async (id: number) => {
    try {
      await deleteAgentMemory(id);
      await reloadAssets();
      Toast.show({ icon: 'success', content: t('profile.memoryDeleted') });
    } catch (error) {
      Toast.show({ icon: 'fail', content: String(error) });
    }
  };

  const formatDate = (value?: string) => value
    ? new Intl.DateTimeFormat(i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    }).format(new Date(value))
    : '';

  const formatCalendarDate = (value?: string) => value
    ? new Intl.DateTimeFormat(i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    }).format(new Date(value))
    : '';

  const empty = (label: string) => (
    <div className={styles.emptyState}>
      <div className={styles.emptyIcon}>◇</div>
      <div>{label}</div>
    </div>
  );

  const activityItems: Array<{
    key: Exclude<ProfileSection, 'notes' | 'following'>;
    count: number;
    label: string;
    icon: ReactNode;
  }> = [
    { key: 'favorites', count: assets?.counts.favorites ?? 0, label: t('profile.favorites'), icon: <HeartOutline /> },
    { key: 'itineraries', count: assets?.counts.itineraries ?? 0, label: t('profile.itineraries'), icon: <TravelOutline /> },
    { key: 'vouchers', count: assets?.counts.vouchers ?? 0, label: t('profile.myVouchers'), icon: <CouponOutline /> },
    { key: 'reminders', count: assets?.counts.reminders ?? 0, label: t('profile.reminders'), icon: <BellOutline /> },
    { key: 'memory', count: assets?.counts.memories ?? 0, label: t('profile.aiMemory'), icon: <FillinOutline /> },
  ];

  const sectionMeta = activeSection === 'notes'
    ? { label: t('profile.notes'), count: blogs.length, icon: <ContentOutline /> }
    : activeSection === 'followers'
      ? { label: t('profile.fans'), count: info.fans || 0, icon: <HeartOutline /> }
    : activeSection === 'following'
      ? { label: t('profile.following'), count: info.followee || 0, icon: <HeartOutline /> }
      : activityItems.find((item) => item.key === activeSection)!;

  const renderSelectedContent = () => {
    if (activeSection === 'notes') {
      return blogs.length ? blogs.map((blog) => (
        <button key={blog.id} className={styles.blogItem}
          onClick={() => navigate(`/blog-detail/${blog.id}`)}>
          <span className={styles.blogItemImg}>
            <NoteVisual
              blogId={blog.id}
              shopId={blog.shopId}
              shopName={blog.shopName}
              typeId={blog.typeId}
              images={blog.images}
              sourceType={blog.sourceType}
              alt={blog.title}
              loading="lazy"
            />
          </span>
          <span className={styles.blogItemInfo}>
            <span className={styles.blogItemTitle}>{blog.title}</span>
            <span className={styles.blogItemMeta}>👍 {blog.liked} · 💬 {blog.comments ?? 0}</span>
          </span>
        </button>
      )) : empty(t('profile.noNotes'));
    }

    if (activeSection === 'favorites') {
      if (assetsLoading) return <div className={styles.loadingMore}>{t('home.loading')}</div>;
      return assets?.favorites.length ? assets.favorites.map((favorite) => (
        <button className={styles.assetCard} key={favorite.id}
          onClick={() => navigate(`/shop-detail/${favorite.shopId}`)}>
          <MerchantVisual
            className={styles.assetImage}
            shopId={favorite.shopId}
            name={favorite.name}
            images={favorite.images}
            alt={favorite.name}
            loading="lazy"
          />
          <span className={styles.assetBody}>
            <strong>{favorite.name}</strong>
            <small>{[favorite.neighborhood, favorite.borough].filter(Boolean).join(', ')}</small>
            <small>{favorite.address}</small>
          </span>
          <span className={styles.assetArrow}>›</span>
        </button>
      )) : empty(t('profile.noFavorites'));
    }

    if (activeSection === 'itineraries') {
      return assets?.itineraries.length ? assets.itineraries.map((trip) => (
        <button
          className={styles.assetCard}
          key={trip.id}
          onClick={() => navigate(`/ai?runId=${encodeURIComponent(trip.runId)}`)}
        >
          <span className={styles.assetGlyph}>⌖</span>
          <span className={styles.assetBody}>
            <strong>{trip.title}</strong>
            <small>{trip.shopNames.join(' · ')}</small>
            <span className={styles.assetMeta}>
              {t('profile.stops', { n: trip.shopIds.length })}
              {trip.itinerary.total_estimated_cost_cents != null &&
                ` · $${(trip.itinerary.total_estimated_cost_cents / 100).toFixed(0)}`}
              {' · '}{formatDate(trip.updatedAt)}
            </span>
          </span>
          <span className={styles.assetArrow}>›</span>
        </button>
      )) : empty(t('profile.noItineraries'));
    }

    if (activeSection === 'vouchers') {
      return assets?.vouchers.length ? assets.vouchers.map((voucher) => (
        <button
          className={`${styles.voucherAsset} ${voucher.expired ? styles.voucherExpired : ''}`}
          key={voucher.orderId}
          onClick={() => voucher.shopId && navigate(`/shop-detail/${voucher.shopId}`)}>
          <span className={styles.voucherValue}>${(voucher.actualValue / 100).toFixed(0)}</span>
          <span className={styles.assetBody}>
            <strong>{voucher.title}</strong>
            <small>{voucher.shopName || t('profile.shopUnavailable')}</small>
            <span className={styles.assetMeta}>
              {t('profile.acquiredOn', { date: formatCalendarDate(voucher.createdAt) })}
              {' · '}{t(voucher.expired ? 'profile.expiredOn' : 'profile.expiresOn', {
                date: formatCalendarDate(voucher.expiresAt),
              })}
            </span>
          </span>
          <span className={styles.assetArrow}>›</span>
        </button>
      )) : empty(t('profile.noVouchers'));
    }

    if (activeSection === 'reminders') {
      return assets?.reminders.length ? assets.reminders.map((reminder) => (
        <button className={styles.assetCard} key={reminder.id}
          onClick={() => reminder.shopId && navigate(`/shop-detail/${reminder.shopId}`)}>
          <span className={styles.assetGlyph}>◷</span>
          <span className={styles.assetBody}>
            <strong>{reminder.voucherTitle}</strong>
            <small>{reminder.shopName}</small>
            <span className={styles.assetMeta}>
              {t('profile.remindAt', { time: formatDate(reminder.remindAt) })}
            </span>
          </span>
          <span className={styles.statusPill}>{t(
            `profile.reminderStatus.${reminder.status.toLowerCase()}`,
            { defaultValue: reminder.status }
          )}</span>
        </button>
      )) : empty(t('profile.noReminders'));
    }

    if (activeSection === 'memory') {
      return (
        <>
          <div className={styles.memoryNotice}>{t('profile.memoryNotice')}</div>
          {assets?.memories.length ? assets.memories.map((memory) => (
            <div className={styles.memoryCard} key={memory.id}>
              <label>{t(`profile.memoryKeys.${memory.key}`, { defaultValue: memory.key })}</label>
              <div className={styles.memoryValueList}>
                {(memoryItemDrafts[memory.id] || []).map((item, itemIndex) => (
                  <div className={styles.memoryValueRow} key={`${memory.id}-${itemIndex}`}>
                    <input
                      value={item}
                      aria-label={t('profile.memoryItem', { n: itemIndex + 1 })}
                      onChange={(event) => updateMemoryItem(memory.id, itemIndex, event.target.value)}
                    />
                    <button
                      type="button"
                      aria-label={t('profile.removeMemoryItem')}
                      onClick={() => removeMemoryItem(memory.id, itemIndex)}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className={styles.addMemoryItem}
                  onClick={() => addMemoryItem(memory.id)}
                >
                  + {t('profile.addMemoryItem')}
                </button>
              </div>
              <div className={styles.memoryActions}>
                <span />
                <button onClick={() => removeMemory(memory.id)}>{t('common.delete')}</button>
                <button className={styles.memorySave} onClick={() => saveMemory(memory.id)}>
                  {t('common.save')}
                </button>
              </div>
            </div>
          )) : empty(t('profile.noMemory'))}
        </>
      );
    }

    if (activeSection === 'followers') {
      if (followersLoading) return <div className={styles.loadingMore}>{t('home.loading')}</div>;
      return followers.length ? followers.map((follower) => (
        <button
          className={styles.personCard}
          key={follower.id}
          onClick={() => navigate(`/user/${follower.id}`)}
        >
          <img src={follower.icon || '/imgs/icons/default-icon.png'} alt="" />
          <span>{follower.nickName}</span>
          <b>›</b>
        </button>
      )) : empty(t('profile.noFollowers'));
    }

    if (followingLoading) return <div className={styles.loadingMore}>{t('home.loading')}</div>;
    return following.length ? following.map((followedUser) => (
      <button
        className={styles.personCard}
        key={followedUser.id}
        onClick={() => navigate(`/user/${followedUser.id}`)}
      >
        <img src={followedUser.icon || '/imgs/icons/default-icon.png'} alt="" />
        <span>{followedUser.nickName}</span>
        <b>›</b>
      </button>
    )) : empty(t('profile.noFollowingUsers'));
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
              <div className={styles.intro}>{info.introduce || t('profile.defaultIntro')}</div>
              <div className={styles.actions}>
                <button className={styles.editBtn} onClick={() => navigate('/profile-edit')}>
                  {t('profile.editProfile')}
                </button>
                <button className={styles.logoutBtn} onClick={handleLogout}>
                  {t('profile.logout')}
                </button>
              </div>
            </div>
          </div>
          <div className={styles.stats}>
            <button
              className={`${styles.statItem} ${activeSection === 'notes' ? styles.statItemActive : ''}`}
              onClick={() => handleSectionChange('notes')}
            >
              <div className={styles.statNum}>{blogs.length}</div>
              <div className={styles.statLabel}>{t('profile.notes')}</div>
            </button>
            <div className={styles.statDivider} />
            <button
              className={`${styles.statItem} ${activeSection === 'followers' ? styles.statItemActive : ''}`}
              onClick={() => handleSectionChange('followers')}
            >
              <div className={styles.statNum}>{info.fans || 0}</div>
              <div className={styles.statLabel}>{t('profile.fans')}</div>
            </button>
            <div className={styles.statDivider} />
            <button
              className={`${styles.statItem} ${activeSection === 'following' ? styles.statItemActive : ''}`}
              onClick={() => handleSectionChange('following')}
            >
              <div className={styles.statNum}>{info.followee || 0}</div>
              <div className={styles.statLabel}>{t('profile.following')}</div>
            </button>
          </div>
        </div>
      )}

      <section className={styles.activityCard} aria-label={t('profile.activity')}>
        <h2>{t('profile.activity')}</h2>
        <div className={styles.activityGrid}>
          {activityItems.map((item) => (
            <button
              key={item.key}
              className={`${styles.activityItem} ${activeSection === item.key ? styles.activityItemActive : ''}`}
              onClick={() => handleSectionChange(item.key)}
            >
              <span className={styles.activityIcon}>{item.icon}</span>
              <span className={styles.activityText}>
                <strong>{item.label}</strong>
                <small>{item.count}</small>
              </span>
              <span className={styles.activityArrow}>›</span>
            </button>
          ))}
          <button
            type="button"
            className={`${styles.activityItem} ${styles.checkInItem} ${signedToday ? styles.checkInItemComplete : ''}`}
            onClick={handleSign}
            disabled={signedToday}
            aria-label={signedToday
              ? t('profile.signedIn', { n: signDays })
              : t('profile.signIn')}
          >
            <span className={styles.activityIcon}><CheckCircleOutline /></span>
            <span className={styles.activityText}>
              <strong>{t('profile.signIn')}</strong>
              <small>{signedToday
                ? t('profile.signedIn', { n: signDays })
                : t('profile.checkInReady')}</small>
            </span>
            {!signedToday && <span className={styles.activityArrow}>›</span>}
          </button>
        </div>
      </section>

      <div className={styles.content}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionIcon}>{sectionMeta.icon}</span>
          <h2>{sectionMeta.label}</h2>
          <span className={styles.sectionCount}>{sectionMeta.count}</span>
        </div>
        <div
          key={activeSection}
          className={styles.tabContent}
        >
          {renderSelectedContent()}
        </div>
      </div>

      <FootBar activeBtn={4} />
    </div>
  );
}
