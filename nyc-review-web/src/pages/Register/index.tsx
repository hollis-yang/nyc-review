import { useState } from 'react';
import { Input, Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { register } from '../../api/auth';
import PhoneNumberField from '../../components/PhoneNumberField';
import { initialPhoneRegion } from '../../constants/phoneRegions';
import { useAuth } from '../../hooks/useAuth';
import { localizedAuthError } from '../../utils/authError';
import { buildAuthEntryUrl, safeAuthRedirect } from '../../utils/authRedirect';
import { isStrongRegistrationPassword } from '../../utils/passwordPolicy';
import BrandIcon from '../../components/BrandIcon';
import styles from '../Login/Login.module.css';

export default function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t, i18n } = useTranslation();
  const { login } = useAuth();
  const [regionCode, setRegionCode] = useState(() => initialPhoneRegion(i18n.resolvedLanguage));
  const [phoneNumber, setPhoneNumber] = useState('');
  const [nickName, setNickName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const redirect = safeAuthRedirect(searchParams.get('redirect'));
  const loginUrl = buildAuthEntryUrl('/login', redirect);

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleRegister = async () => {
    if (!agreed) {
      Toast.show({ icon: 'fail', content: t('auth.agreeRequired') });
      return;
    }
    if (!phoneNumber.trim() || !password || !confirmPassword) {
      Toast.show({ icon: 'fail', content: t('register.required') });
      return;
    }
    if (password !== confirmPassword) {
      Toast.show({ icon: 'fail', content: t('register.passwordMismatch') });
      return;
    }
    if (!isStrongRegistrationPassword(password)) {
      Toast.show({ icon: 'fail', content: t('auth.errors.passwordPolicy') });
      return;
    }
    setSubmitting(true);
    try {
      const res = await register({
        regionCode,
        phoneNumber: phoneNumber.trim(),
        password,
        nickName: nickName.trim() || undefined,
      });
      const token = res.data ?? res;
      if (token) {
        login(String(token));
        Toast.show({ icon: 'success', content: t('register.success') });
        navigate(redirect, { replace: true });
      }
    } catch (error: unknown) {
      Toast.show({ icon: 'fail', content: localizedAuthError(error, t) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <button type="button" data-mobile-context-back="true" className={styles.backBtn} onClick={handleBack} aria-label={t('auth.back')}>
          <LeftOutline fontSize={22} color="white" />
        </button>
        <div className={styles.headerTitle}>{t('register.title')}</div>
      </div>
      <div className={styles.scroll}>
        <div className={styles.authPanel}>
        <div className={styles.brand}>
          <BrandIcon size={48} />
          <div className={styles.brandName}>{t('register.heading')}</div>
          <div className={styles.brandSlogan}>{t('register.subtitle')}</div>
        </div>

        <div className={styles.formColumn}>
        <div className={styles.formCard}>
          <div className={styles.fieldGroup}>
            <PhoneNumberField
              regionCode={regionCode}
              phoneNumber={phoneNumber}
              onRegionChange={setRegionCode}
              onPhoneChange={setPhoneNumber}
            />
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.fieldGroup}>
            <Input
              className={styles.textInput}
              placeholder={t('register.nicknamePlaceholder')}
              value={nickName}
              onChange={setNickName}
              maxLength={32}
              autoComplete="nickname"
              style={{ '--font-size': '15px' } as React.CSSProperties}
            />
          </div>
          <div className={styles.fieldDivider} />
          <div className={`${styles.fieldGroup} ${styles.passwordRow}`}>
            <Input
              className={styles.passwordInput}
              placeholder={t('auth.passwordPlaceholder')}
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              style={{ '--font-size': '15px' } as React.CSSProperties}
            />
            <button type="button" className={styles.passwordToggle} onClick={() => setShowPassword(!showPassword)}>
              {showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
            </button>
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.fieldGroup}>
            <Input
              className={styles.textInput}
              placeholder={t('register.confirmPasswordPlaceholder')}
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              style={{ '--font-size': '15px' } as React.CSSProperties}
            />
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.hint}>{t('register.passwordHint')}</div>
          <button className={styles.loginBtn} onClick={handleRegister} disabled={submitting}>
            {submitting ? t('auth.submitting') : t('register.registerBtn')}
          </button>
          <div className={styles.switchLink}>
            <span>{t('register.hasAccount')} </span>
            <Link to={loginUrl}>{t('register.signIn')}</Link>
          </div>
        </div>

        <div className={styles.agreement}>
          <button
            type="button"
            className={`${styles.checkbox} ${agreed ? styles.checkboxChecked : ''}`}
            onClick={() => setAgreed(!agreed)}
            aria-pressed={agreed}
            aria-label={t('auth.agreement')}
          >
            {agreed && (
              <svg viewBox="0 0 24 24" width="14" height="14" fill="#fff" aria-hidden="true">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
              </svg>
            )}
          </button>
          <div className={styles.agreementText}>
            {t('auth.agreement')} <a href="#terms" onClick={(event) => event.preventDefault()}>{t('auth.tos')}</a>
            {t('auth.agreementJoin')}
            <a href="#privacy" onClick={(event) => event.preventDefault()}>{t('auth.privacy')}</a>
          </div>
        </div>
        </div>
        </div>
      </div>
    </div>
  );
}
