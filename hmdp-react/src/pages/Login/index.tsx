import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Input, Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { useAuth } from '../../hooks/useAuth';
import { sendCode, loginByCode, loginByPassword } from '../../api/auth';
import styles from './Login.module.css';

interface LoginProps {
  mode?: string;
}

function BrandIcon({ size = 36 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} fill="none">
      <rect width="64" height="64" rx="16" fill="url(#bg)" />
      <path d="M20 44c0-13.255 10.745-24 24-24S68 30.745 68 44" stroke="#fff" strokeWidth="3" fill="none" />
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="64" y2="64">
          <stop stopColor="#ff6633" />
          <stop offset="1" stopColor="#ff8a5c" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export default function Login({ mode = 'sms' }: LoginProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const isPasswordMode = mode === 'password';

  const [radio, setRadio] = useState('');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [disabled, setDisabled] = useState(false);
  const [codeBtnMsg, setCodeBtnMsg] = useState('获取验证码');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef(60);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const handleBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/');
    }
  };

  const handleSendCode = async () => {
    if (!phone) {
      Toast.show({ icon: 'fail', content: '手机号不能为空' });
      return;
    }
    try {
      await sendCode(phone);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
      return;
    }
    setDisabled(true);
    countdownRef.current = 60;
    setCodeBtnMsg(`${countdownRef.current}秒后可重发`);
    timerRef.current = setInterval(() => {
      countdownRef.current--;
      if (countdownRef.current <= 0) {
        setDisabled(false);
        setCodeBtnMsg('获取验证码');
        if (timerRef.current) clearInterval(timerRef.current);
      } else {
        setCodeBtnMsg(`${countdownRef.current}秒后可重发`);
      }
    }, 1000);
  };

  const handleLogin = async () => {
    if (!radio) {
      Toast.show({ icon: 'fail', content: '请先确认阅读用户协议！' });
      return;
    }
    if (!phone || (!isPasswordMode && !code) || (isPasswordMode && !password)) {
      Toast.show({ icon: 'fail', content: isPasswordMode ? '手机号和密码不能为空！' : '手机号和验证码不能为空！' });
      return;
    }
    try {
      const res = await (isPasswordMode
        ? loginByPassword(phone, password)
        : loginByCode(phone, code));
      const token = res.data ?? res;
      if (token) {
        login(String(token));
        const redirect = searchParams.get('redirect') || '/';
        navigate(redirect, { replace: true });
      }
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={22} color="white" />
        </div>
        <div className={styles.headerTitle}>
          {isPasswordMode ? '密码登录' : '手机号码快捷登录'}
        </div>
      </div>
      <div className={styles.scroll}>
        <div className={styles.brand}>
          <BrandIcon size={48} />
          <div className={styles.brandName}>黑马点评</div>
          <div className={styles.brandSlogan}>发现身边好店</div>
        </div>

        <div className={styles.formCard}>
          <div className={styles.fieldGroup}>
            <Input
              placeholder="请输入手机号"
              value={phone}
              onChange={setPhone}
              style={{ '--font-size': '15px' } as React.CSSProperties}
            />
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.fieldGroup}>
            {isPasswordMode ? (
              <Input
                placeholder="请输入密码"
                type="password"
                value={password}
                onChange={setPassword}
                style={{ '--font-size': '15px' } as React.CSSProperties}
              />
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <Input
                    placeholder="请输入验证码"
                    value={code}
                    onChange={setCode}
                    style={{ '--font-size': '15px' } as React.CSSProperties}
                  />
                </div>
                <div
                  className={`${styles.codeBtn} ${disabled ? styles.codeBtnDisabled : ''}`}
                  onClick={disabled ? undefined : handleSendCode}
                >
                  {codeBtnMsg}
                </div>
              </div>
            )}
          </div>
          <div className={styles.fieldDivider} />
          <div className={styles.hint}>
            {isPasswordMode ? '未注册的手机号码登录后将自动注册' : '未注册的手机号码验证后自动创建账户'}
          </div>
          <button className={styles.loginBtn} onClick={handleLogin}>
            登录
          </button>
          <div className={styles.switchLink}>
            <Link to={isPasswordMode ? '/login' : '/login2'}>
              {isPasswordMode ? '验证码登录' : '密码登录'}
            </Link>
          </div>
        </div>

        <div className={styles.agreement}>
          <div
            className={`${styles.checkbox} ${radio === '1' ? styles.checkboxChecked : ''}`}
            onClick={() => setRadio(radio === '1' ? '' : '1')}
          >
            {radio === '1' && (
              <svg viewBox="0 0 24 24" width="14" height="14" fill="#fff">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
              </svg>
            )}
          </div>
          <div className={styles.agreementText}>
            我已阅读并同意
            <a href="javascript:void(0)">《用户服务协议》</a>
            、
            <a href="javascript:void(0)">《隐私政策》</a>
          </div>
        </div>
      </div>
    </div>
  );
}
