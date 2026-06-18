import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LeftOutline } from 'antd-mobile-icons';
import FootBar from '../../components/FootBar';
import styles from './Messages.module.css';

export default function Messages() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={() => navigate(-1)}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.headerTitle}>{t('messages.title')}</div>
      </div>

      <div className={styles.empty}>
        <div className={styles.emptyIcon}>📭</div>
        <div className={styles.emptyText}>{t('messages.empty')}</div>
        <div className={styles.emptyHint}>{t('messages.comingSoon')}</div>
      </div>

      <FootBar activeBtn={3} />
    </div>
  );
}
