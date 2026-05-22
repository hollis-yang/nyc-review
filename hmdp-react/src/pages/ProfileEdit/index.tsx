import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LeftOutline, RightOutline } from 'antd-mobile-icons';
import { getMe } from '../../api/user';
import FootBar from '../../components/FootBar';
import styles from './ProfileEdit.module.css';

export default function ProfileEdit() {
  const navigate = useNavigate();
  const [user, setUser] = useState<{ id: number; nickName: string; icon: string } | null>(null);
  const [info, setInfo] = useState<Record<string, any>>({});

  useEffect(() => {
    getMe()
      .then((res) => {
        setUser(res.data ?? res);
        const stored = sessionStorage.getItem('userInfo');
        if (stored) {
          try {
            setInfo(JSON.parse(stored));
          } catch {
            setInfo({});
          }
        }
      })
      .catch(() => {
        setTimeout(() => navigate('/login'), 1000);
      });
  }, [navigate]);

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/profile');
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.title}>资料编辑</div>
      </div>

      <div className={styles.scroll}>
        <div className={styles.infoBox}>
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>头像</div>
            <div className={styles.infoBtn}>
              <img
                width="35"
                src={user?.icon || '/imgs/icons/default-icon.png'}
                alt=""
                style={{ borderRadius: '50%' }}
              />
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>昵称</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{user?.nickName || ''}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>个人介绍</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>
                {info.introduce || '介绍一下自己'}
              </div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>

        <div className={styles.infoBox}>
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>性别</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.gender ? (info.gender === true || info.gender === 'true' ? '男' : '女') : '选择'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>城市</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.city || '选择'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>生日</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.birthday || '添加'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>

        <div className={styles.infoBox}>
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>我的积分</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>查看积分</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>会员等级</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>
                <a href="javascript:void(0)" style={{ color: '#F63', fontSize: 13 }}>
                  成为VIP尊享特权
                </a>
              </div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>
      </div>

      <FootBar activeBtn={4} />
    </div>
  );
}
