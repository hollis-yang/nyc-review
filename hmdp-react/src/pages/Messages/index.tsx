import { useNavigate } from 'react-router-dom';
import { LeftOutline } from 'antd-mobile-icons';
import FootBar from '../../components/FootBar';
import styles from './Messages.module.css';

export default function Messages() {
  const navigate = useNavigate();

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={() => navigate(-1)}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.headerTitle}>消息</div>
      </div>

      <div className={styles.empty}>
        <div className={styles.emptyIcon}>📭</div>
        <div className={styles.emptyText}>暂无消息</div>
        <div className={styles.emptyHint}>功能开发中，敬请期待</div>
      </div>

      <FootBar activeBtn={3} />
    </div>
  );
}
