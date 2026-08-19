import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { LeftOutline, UserOutline } from 'antd-mobile-icons';
import { useTranslation } from 'react-i18next';
import styles from './Header.module.css';

interface HeaderProps {
  title?: string;
  showBack?: boolean;
  showUser?: boolean;
  showShare?: boolean;
  onRightClick?: () => void;
  children?: ReactNode;
}

export default function Header({
  title,
  showBack = false,
  showUser = false,
  onRightClick,
}: HeaderProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const handleBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/');
    }
  };

  return (
    <div className={styles.header}>
      <div className={styles.left}>
        {showBack && (
          <div className={styles.backBtn} onClick={handleBack}>
            <LeftOutline fontSize={18} />
          </div>
        )}
      </div>
      <div className={styles.title}>{title || t('login.brand')}</div>
      <div className={styles.right}>
        {showUser && (
          <div className={styles.icon} onClick={onRightClick}>
            <UserOutline fontSize={18} />
          </div>
        )}
      </div>
    </div>
  );
}
