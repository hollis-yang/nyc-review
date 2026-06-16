import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import { Tabs, Toast } from 'antd-mobile';
import { getUserById, getUserInfo, getMe } from '../../api/user';
import { getBlogsOfUser } from '../../api/blog';
import { isFollowed, follow, getCommonFollows } from '../../api/follow';
import FootBar from '../../components/FootBar';
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

export default function OtherProfile() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [info, setInfo] = useState<DetailInfo>({});
  const [blogs, setBlogs] = useState<any[]>([]);
  const [followed, setFollowed] = useState(false);
  const [commonFollows, setCommonFollows] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState('1');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setUser(null);
    setInfo({});
    setBlogs([]);
    setFollowed(false);
    setCommonFollows([]);
    setActiveTab('1');
    setError(null);
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
        isFollowed(u.id)
          .then((r) => setFollowed(r.data ?? r))
          .catch(() => {});
      }),
      getMe().then(() => {}).catch(() => {}),
    ]).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || '用户不存在');
    });
  }, [id]);

  const handleFollow = async () => {
    if (!user) return;
    try {
      await follow(user.id, !followed);
      Toast.show({ icon: 'success', content: followed ? '已取消关注' : '已关注' });
      setFollowed(!followed);
    } catch (err: any) {
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
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.headerTitle}>
          {user ? `${user.nickName} 的主页` : ''}
        </div>
      </div>

      {error && <div className={styles.loadingFull}>{error}</div>}
      {!error && !user && <div className={styles.loadingFull}>加载中...</div>}
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
                  {info.city || '杭州'}
                  {info.introduce ? ` · ${info.introduce}` : ''}
                </div>
              </div>
              <div
                className={`${styles.followBtn} ${followed ? styles.followBtnUnfollow : ''}`}
                onClick={handleFollow}
              >
                {followed ? '已关注' : '+ 关注'}
              </div>
            </div>
            {!info.introduce && !info.city && (
              <div className={styles.introRow}>这个人很懒，什么都没有留下</div>
            )}
          </div>

          {/* 内容卡片（笔记 / 共同关注） */}
          <div className={styles.contentCard}>
            <Tabs activeKey={activeTab} onChange={handleTabChange}>
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
                          <span>💬 {b.comments ?? 0}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Tabs.Tab>
              <Tabs.Tab title="共同关注" key="2">
                <div className={styles.tabContent}>
                  <div className={styles.commonFollowHint}>你们都关注了：</div>
                  {commonFollows.map((u) => (
                    <div key={u.id} className={styles.followItem}>
                      <div
                        className={styles.followIcon}
                        onClick={() => navigate(`/user/${u.id}`)}
                      >
                        <img src={u.icon || '/imgs/icons/default-icon.png'} alt="" />
                      </div>
                      <div className={styles.followName}>{u.nickName}</div>
                      <div
                        className={styles.followVisitBtn}
                        onClick={() => navigate(`/user/${u.id}`)}
                      >
                        去主页看看
                      </div>
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
