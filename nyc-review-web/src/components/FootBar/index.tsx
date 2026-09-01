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

function CreateNoteIcon({ size = 26 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M13.5 5H6.8A2.8 2.8 0 0 0 4 7.8v9.4A2.8 2.8 0 0 0 6.8 20h9.4a2.8 2.8 0 0 0 2.8-2.8v-6.7" />
      <path d="m12 14 1.1-3.5 5.8-5.8a1.6 1.6 0 0 1 2.3 2.3l-5.8 5.8L12 14Z" />
      <path d="M8 9h2.5M8 13h1.5" />
    </svg>
  );
}
import styles from './FootBar.module.css';

interface FootBarProps {
  activeBtn: number;
  mobileOnly?: boolean;
}

export default function FootBar({ activeBtn, mobileOnly = false }: FootBarProps) {
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
    <nav
      className={`${styles.foot} ${mobileOnly ? styles.mobileOnly : ''}`}
      aria-label={t('login.brand')}
    >
      <button
        type="button"
        className={`${styles.footBox} ${activeBtn === 1 ? styles.active : ''}`}
        onClick={() => toPage(1)}
        aria-current={activeBtn === 1 ? 'page' : undefined}
      >
        <div className={styles.footView}><HomeIcon size={26} /></div>
        <div className={styles.footText}>{t('nav.home')}</div>
      </button>
      <button
        type="button"
        className={`${styles.footBox} ${activeBtn === 2 ? styles.active : ''}`}
        onClick={() => toPage(2)}
        aria-current={activeBtn === 2 ? 'page' : undefined}
      >
        <div className={styles.footView}><EnvironmentOutline fontSize={26} /></div>
        <div className={styles.footText}>{t('nav.map')}</div>
      </button>
      <button
        type="button"
        className={`${styles.footBox} ${activeBtn === 3 ? styles.active : ''}`}
        onClick={() => toPage(0)}
        aria-label={t('nav.create')}
        aria-current={activeBtn === 3 ? 'page' : undefined}
      >
        <div className={styles.footView}>
          <img className={`${styles.addBtn} ${styles.createMobileIcon}`} src="/imgs/add.png" alt="" />
          <span className={styles.createDesktopIcon}><CreateNoteIcon size={26} /></span>
        </div>
        <div className={`${styles.footText} ${styles.createText}`}>{t('nav.create')}</div>
      </button>
      <button
        type="button"
        className={`${styles.footBox} ${activeBtn === 5 ? styles.active : ''}`}
        onClick={() => toPage(5)}
        aria-current={activeBtn === 5 ? 'page' : undefined}
      >
        <div className={styles.footView}><AiIcon size={26} /></div>
        <div className={styles.footText}>{t('nav.ai')}</div>
      </button>
      <button
        type="button"
        className={`${styles.footBox} ${activeBtn === 4 ? styles.active : ''}`}
        onClick={() => toPage(4)}
        aria-current={activeBtn === 4 ? 'page' : undefined}
      >
        <div className={styles.footView}><UserOutline fontSize={26} /></div>
        <div className={styles.footText}>{t('nav.profile')}</div>
      </button>
    </nav>
  );
}
