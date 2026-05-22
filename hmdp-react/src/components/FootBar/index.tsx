import { useNavigate } from 'react-router-dom';
import { EnvironmentOutline, MessageOutline, UserOutline } from 'antd-mobile-icons';

function HomeIcon({ size = 26, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" width={size} height={size} fill={color}>
      <path d="M512 128L128 512h128v384h256V640h128v256h256V512h128L512 128z" />
    </svg>
  );
}
import styles from './FootBar.module.css';

interface FootBarProps {
  activeBtn: number;
}

export default function FootBar({ activeBtn }: FootBarProps) {
  const navigate = useNavigate();

  const toPage = (i: number) => {
    if (i === 0) {
      navigate('/blog-edit');
    } else if (i === 1) {
      navigate('/');
    } else if (i === 4) {
      navigate('/profile');
    }
  };

  return (
    <div className={styles.foot}>
      <div
        className={`${styles.footBox} ${activeBtn === 1 ? styles.active : ''}`}
        onClick={() => toPage(1)}
      >
        <div className={styles.footView}><HomeIcon size={26} /></div>
        <div className={styles.footText}>首页</div>
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 2 ? styles.active : ''}`}
        onClick={() => toPage(2)}
      >
        <div className={styles.footView}><EnvironmentOutline fontSize={26} /></div>
        <div className={styles.footText}>地图</div>
      </div>
      <div className={styles.footBox} onClick={() => toPage(0)}>
        <img className={styles.addBtn} src="/imgs/add.png" alt="" />
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 3 ? styles.active : ''}`}
        onClick={() => toPage(3)}
      >
        <div className={styles.footView}><MessageOutline fontSize={26} /></div>
        <div className={styles.footText}>消息</div>
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 4 ? styles.active : ''}`}
        onClick={() => toPage(4)}
      >
        <div className={styles.footView}><UserOutline fontSize={26} /></div>
        <div className={styles.footText}>我的</div>
      </div>
    </div>
  );
}
