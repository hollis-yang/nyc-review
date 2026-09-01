import { useEffect, useState } from 'react';
import { Input, Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  changePassword,
  getAccountSecurityStatus,
  setRecoveryKey,
} from '../../api/auth';
import FootBar from '../../components/FootBar';
import { localizedAuthError } from '../../utils/authError';
import { isStrongRecoveryKey, isStrongRegistrationPassword } from '../../utils/passwordPolicy';
import { buildAuthEntryUrl } from '../../utils/authRedirect';
import styles from './SecurityForm.module.css';

export default function AccountSecurity() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [recoveryConfigured, setRecoveryConfigured] = useState<boolean | null>(null);
  const [keyPassword, setKeyPassword] = useState('');
  const [recoveryKey, setRecoveryKeyValue] = useState('');
  const [recoveryKeyConfirmation, setRecoveryKeyConfirmation] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirmation, setNewPasswordConfirmation] = useState('');
  const [savingKey, setSavingKey] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  useEffect(() => {
    getAccountSecurityStatus()
      .then((response) => {
        const status = response.data ?? response;
        setRecoveryConfigured(Boolean(status?.recoveryKeyConfigured));
      })
      .catch(() => setRecoveryConfigured(null));
  }, []);

  const saveRecoveryKey = async () => {
    if (!keyPassword || !recoveryKey || !recoveryKeyConfirmation) {
      Toast.show({ icon: 'fail', content: t('accountSecurity.allFieldsRequired') });
      return;
    }
    if (recoveryKey !== recoveryKeyConfirmation) {
      Toast.show({ icon: 'fail', content: t('accountSecurity.recoveryKeyMismatch') });
      return;
    }
    if (!isStrongRecoveryKey(recoveryKey)) {
      Toast.show({ icon: 'fail', content: t('auth.errors.recoveryKeyPolicy') });
      return;
    }
    setSavingKey(true);
    try {
      await setRecoveryKey({ currentPassword: keyPassword, recoveryKey });
      setKeyPassword('');
      setRecoveryKeyValue('');
      setRecoveryKeyConfirmation('');
      setRecoveryConfigured(true);
      Toast.show({ icon: 'success', content: t('accountSecurity.recoveryKeySaved') });
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: localizedAuthError(error, t) });
    } finally {
      setSavingKey(false);
    }
  };

  const savePassword = async () => {
    if (!currentPassword || !newPassword || !newPasswordConfirmation) {
      Toast.show({ icon: 'fail', content: t('accountSecurity.allFieldsRequired') });
      return;
    }
    if (newPassword !== newPasswordConfirmation) {
      Toast.show({ icon: 'fail', content: t('accountSecurity.passwordMismatch') });
      return;
    }
    if (!isStrongRegistrationPassword(newPassword)) {
      Toast.show({ icon: 'fail', content: t('auth.errors.passwordPolicy') });
      return;
    }
    setSavingPassword(true);
    try {
      await changePassword({ currentPassword, newPassword });
      sessionStorage.removeItem('token');
      sessionStorage.removeItem('userInfo');
      window.location.assign(buildAuthEntryUrl('/login', '/account-security', { passwordChanged: '1' }));
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: localizedAuthError(error, t) });
      setSavingPassword(false);
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <button type="button" className={styles.backBtn} onClick={() => navigate('/profile-edit')} aria-label={t('auth.back')}>
          <LeftOutline fontSize={22} color="white" />
        </button>
        <div className={styles.title}>{t('accountSecurity.title')}</div>
      </header>

      <main className={`${styles.scroll} ${styles.securityScroll}`}>
        <div className={`${styles.intro} ${styles.securityIntro}`}>{t('accountSecurity.intro')}</div>

        <div className={styles.securityCards}>
        <section className={styles.card}>
          <div className={styles.cardTitle}>{t('accountSecurity.recoveryTitle')}</div>
          {recoveryConfigured !== null && (
            <div className={`${styles.status} ${recoveryConfigured ? '' : styles.statusUnset}`}>
              {t(recoveryConfigured ? 'accountSecurity.configured' : 'accountSecurity.notConfigured')}
            </div>
          )}
          <p className={styles.description}>{t('accountSecurity.recoveryDescription')}</p>
          <div className={styles.field}>
            <Input type="password" autoComplete="current-password" value={keyPassword} onChange={setKeyPassword} placeholder={t('accountSecurity.currentPassword')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="off" value={recoveryKey} onChange={setRecoveryKeyValue} placeholder={t('accountSecurity.recoveryKey')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="off" value={recoveryKeyConfirmation} onChange={setRecoveryKeyConfirmation} placeholder={t('accountSecurity.confirmRecoveryKey')} />
          </div>
          <div className={styles.hint}>{t('accountSecurity.recoveryHint')}</div>
          <button type="button" className={styles.button} disabled={savingKey} onClick={saveRecoveryKey}>
            {savingKey ? t('auth.submitting') : t('accountSecurity.saveRecoveryKey')}
          </button>
        </section>

        <section className={styles.card}>
          <div className={styles.cardTitle}>{t('accountSecurity.changePasswordTitle')}</div>
          <p className={styles.description}>{t('accountSecurity.changePasswordDescription')}</p>
          <div className={styles.field}>
            <Input type="password" autoComplete="current-password" value={currentPassword} onChange={setCurrentPassword} placeholder={t('accountSecurity.currentPassword')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="new-password" value={newPassword} onChange={setNewPassword} placeholder={t('accountSecurity.newPassword')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="new-password" value={newPasswordConfirmation} onChange={setNewPasswordConfirmation} placeholder={t('accountSecurity.confirmNewPassword')} />
          </div>
          <div className={styles.hint}>{t('register.passwordHint')}</div>
          <button type="button" className={styles.button} disabled={savingPassword} onClick={savePassword}>
            {savingPassword ? t('auth.submitting') : t('accountSecurity.changePassword')}
          </button>
        </section>
        </div>
      </main>
      <FootBar activeBtn={4} />
    </div>
  );
}
