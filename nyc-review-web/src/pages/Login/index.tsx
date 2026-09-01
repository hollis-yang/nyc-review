import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Input, Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { useAuth } from '../../hooks/useAuth';
import { useTranslation } from 'react-i18next';
import { loginByPassword } from '../../api/auth';
import PhoneNumberField from '../../components/PhoneNumberField';
import { initialPhoneRegion } from '../../constants/phoneRegions';
import { localizedAuthError } from '../../utils/authError';
import { buildAuthEntryUrl, safeAuthRedirect } from '../../utils/authRedirect';
import BrandIcon from '../../components/BrandIcon';
import styles from './Login.module.css';

export default function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t, i18n } = useTranslation();
  const { login } = useAuth();
  const [regionCode, setRegionCode] = useState(() => initialPhoneRegion(i18n.resolvedLanguage));
  const [phoneNumber, setPhoneNumber] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const redirect = safeAuthRedirect(searchParams.get('redirect'));
  const registerUrl = buildAuthEntryUrl('/register', redirect);
  const forgotPasswordUrl = buildAuthEntryUrl('/forgot-password', redirect);

  useEffect(() => {
    if (searchParams.get('passwordChanged') === '1') {
      Toast.show({ icon: 'success', content: t('login.passwordChanged') });
    } else if (searchParams.get('passwordReset') === '1') {
      Toast.show({ icon: 'success', content: t('login.passwordReset') });
    }
  }, [searchParams, t]);

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleLogin = async () => {
    if (!agreed) {
      Toast.show({ icon: 'fail', content: t('auth.agreeRequired') });
      return;
    }
    if (!phoneNumber.trim() || !password) {
      Toast.show({ icon: 'fail', content: t('auth.phonePasswordRequired') });
      return;
    }
    setSubmitting(true);
    try {
      const res = await loginByPassword({ regionCode, phoneNumber: phoneNumber.trim(), password });
      const token = res.data ?? res;
      if (token) {
        login(String(token));
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
        <div className={styles.headerTitle}>{t('login.title')}</div>
      </div>
      <div className={styles.scroll}>
        <div className={styles.authPanel}>
        <div className={styles.brand}>
          <BrandIcon size={48} />
          <div className={styles.brandName}>{t('login.brand')}</div>
          <div className={styles.brandSlogan}>{t('login.slogan')}</div>
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
          <div className={`${styles.fieldGroup} ${styles.passwordRow}`}>
            <Input
              className={styles.passwordInput}
              placeholder={t('auth.passwordPlaceholder')}
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              style={{ '--font-size': '15px' } as React.CSSProperties}
            />
            <button type="button" className={styles.passwordToggle} onClick={() => setShowPassword(!showPassword)}>
              {showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
            </button>
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.forgotLink}>
            <Link to={forgotPasswordUrl}>{t('login.forgotPassword')}</Link>
          </div>
          <button className={styles.loginBtn} onClick={handleLogin} disabled={submitting}>
            {submitting ? t('auth.submitting') : t('login.loginBtn')}
          </button>
          <div className={styles.switchLink}>
            <span>{t('login.noAccount')} </span>
            <Link to={registerUrl}>{t('login.createAccount')}</Link>
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
