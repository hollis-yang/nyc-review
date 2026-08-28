import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { EnvironmentOutline, UserOutline } from 'antd-mobile-icons';

function HomeIcon({ size = 26, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" width={size} height={size} fill={color}>
      <path d="M512 128L128 512h128v384h256V640h128v256h256V512h128L512 128z" />
    </svg>
  );
}

function AiIcon({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 2.8c.7 4.7 2.5 6.5 7.2 7.2-4.7.7-6.5 2.5-7.2 7.2-.7-4.7-2.5-6.5-7.2-7.2 4.7-.7 6.5-2.5 7.2-7.2Z" />
      <path d="M19 16c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z" />
    </svg>
  );
}
import styles from './FootBar.module.css';

interface FootBarProps {
  activeBtn: number;
}

export default function FootBar({ activeBtn }: FootBarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const toPage = (i: number) => {
    if (i === 0) {
      navigate('/blog-edit');
    } else if (i === 1) {
      navigate('/');
    } else if (i === 2) {
      navigate('/map');
    } else if (i === 4) {
      navigate('/profile');
    } else if (i === 5) {
      navigate('/ai');
    }
  };

  return (
    <div className={styles.foot}>
      <div
        className={`${styles.footBox} ${activeBtn === 1 ? styles.active : ''}`}
        onClick={() => toPage(1)}
      >
        <div className={styles.footView}><HomeIcon size={26} /></div>
        <div className={styles.footText}>{t('nav.home')}</div>
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 2 ? styles.active : ''}`}
        onClick={() => toPage(2)}
      >
        <div className={styles.footView}><EnvironmentOutline fontSize={26} /></div>
        <div className={styles.footText}>{t('nav.map')}</div>
      </div>
      <div className={styles.footBox} onClick={() => toPage(0)}>
        <img className={styles.addBtn} src="/imgs/add.png" alt={t('nav.create')} />
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 5 ? styles.active : ''}`}
        onClick={() => toPage(5)}
      >
        <div className={styles.footView}><AiIcon size={26} /></div>
        <div className={styles.footText}>{t('nav.ai')}</div>
      </div>
      <div
        className={`${styles.footBox} ${activeBtn === 4 ? styles.active : ''}`}
        onClick={() => toPage(4)}
      >
        <div className={styles.footView}><UserOutline fontSize={26} /></div>
        <div className={styles.footText}>{t('nav.profile')}</div>
      </div>
    </div>
  );
}
