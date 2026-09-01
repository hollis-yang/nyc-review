import { useState } from 'react';
import { Input, Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { resetPassword } from '../../api/auth';
import PhoneNumberField from '../../components/PhoneNumberField';
import { initialPhoneRegion } from '../../constants/phoneRegions';
import { localizedAuthError } from '../../utils/authError';
import { buildAuthEntryUrl, safeAuthRedirect } from '../../utils/authRedirect';
import { isStrongRecoveryKey, isStrongRegistrationPassword } from '../../utils/passwordPolicy';
import styles from '../AccountSecurity/SecurityForm.module.css';

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t, i18n } = useTranslation();
  const [regionCode, setRegionCode] = useState(() => initialPhoneRegion(i18n.resolvedLanguage));
  const [phoneNumber, setPhoneNumber] = useState('');
  const [recoveryKey, setRecoveryKey] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const redirect = safeAuthRedirect(searchParams.get('redirect'));
  const loginUrl = buildAuthEntryUrl('/login', redirect);
  const resetCompleteUrl = buildAuthEntryUrl('/login', redirect, { passwordReset: '1' });

  const submit = async () => {
    if (!phoneNumber.trim() || !recoveryKey || !newPassword || !confirmation) {
      Toast.show({ icon: 'fail', content: t('forgotPassword.allFieldsRequired') });
      return;
    }
    if (newPassword !== confirmation) {
      Toast.show({ icon: 'fail', content: t('accountSecurity.passwordMismatch') });
      return;
    }
    if (!isStrongRegistrationPassword(newPassword)) {
      Toast.show({ icon: 'fail', content: t('auth.errors.passwordPolicy') });
      return;
    }
    // Keep malformed keys local while the server still applies uniform handling to all accounts.
    if (!isStrongRecoveryKey(recoveryKey)) {
      Toast.show({ icon: 'fail', content: t('auth.errors.resetRejected') });
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword({
        regionCode,
        phoneNumber: phoneNumber.trim(),
        recoveryKey,
        newPassword,
      });
      navigate(resetCompleteUrl, { replace: true });
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: localizedAuthError(error, t) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <button type="button" className={styles.backBtn} onClick={() => navigate(loginUrl)} aria-label={t('auth.back')}>
          <LeftOutline fontSize={22} color="white" />
        </button>
        <div className={styles.title}>{t('forgotPassword.title')}</div>
      </header>
      <main className={`${styles.scroll} ${styles.forgotScroll}`}>
        <div className={`${styles.intro} ${styles.forgotIntro}`}>{t('forgotPassword.intro')}</div>
        <section className={`${styles.card} ${styles.forgotCard}`}>
          <div className={styles.field}>
            <PhoneNumberField regionCode={regionCode} phoneNumber={phoneNumber} onRegionChange={setRegionCode} onPhoneChange={setPhoneNumber} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="off" value={recoveryKey} onChange={setRecoveryKey} placeholder={t('accountSecurity.recoveryKey')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="new-password" value={newPassword} onChange={setNewPassword} placeholder={t('accountSecurity.newPassword')} />
          </div>
          <div className={styles.field}>
            <Input type="password" autoComplete="new-password" value={confirmation} onChange={setConfirmation} placeholder={t('accountSecurity.confirmNewPassword')} />
          </div>
          <div className={styles.hint}>{t('register.passwordHint')}</div>
          <button type="button" className={styles.button} disabled={submitting} onClick={submit}>
            {submitting ? t('auth.submitting') : t('forgotPassword.resetPassword')}
          </button>
          <Link className={styles.footerLink} to={loginUrl}>{t('forgotPassword.backToLogin')}</Link>
        </section>
      </main>
    </div>
  );
}
