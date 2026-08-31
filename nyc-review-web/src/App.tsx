import './i18n';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ConfigProvider } from 'antd-mobile';
import enUS from 'antd-mobile/es/locales/en-US';
import zhCN from 'antd-mobile/es/locales/zh-CN';
import { useTranslation } from 'react-i18next';
import { AuthProvider } from './contexts/AuthContext';
import Home from './pages/Home';
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ShopList from './pages/ShopList';
import ShopDetail from './pages/ShopDetail';
import ShopReviews from './pages/ShopReviews';
import BlogDetail from './pages/BlogDetail';
import BlogEdit from './pages/BlogEdit';
import MyProfile from './pages/MyProfile';
import ProfileEdit from './pages/ProfileEdit';
import AccountSecurity from './pages/AccountSecurity';
import OtherProfile from './pages/OtherProfile';
import MapPage from './pages/Map';
import AiWorkspace from './pages/AiWorkspace';
import ProtectedRoute from './components/ProtectedRoute';
import LegacyRedirect from './components/LegacyRedirect';
import styles from './App.module.css';

const routesWithPrimaryNavigation = [
  '/',
  '/map',
  '/ai',
  '/blog-edit',
  '/profile',
  '/profile-edit',
  '/account-security',
];

function hasPrimaryNavigation(pathname: string) {
  const normalizedPath = pathname === '/' ? pathname : pathname.replace(/\/+$/, '');
  return routesWithPrimaryNavigation.includes(normalizedPath) || /^\/user\/[^/]+$/.test(normalizedPath);
}

function AppRoutes() {
  const { pathname } = useLocation();
  const withPrimaryNavigation = hasPrimaryNavigation(pathname);

  return (
    <div className={`${styles.shell} ${withPrimaryNavigation ? styles.withPrimaryNavigation : ''}`}>
      <div className={styles.routeViewport}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/login2" element={<Navigate to="/login" replace />} />
          <Route path="/shop-list" element={<ShopList />} />
          <Route path="/shop-detail/:id" element={<ShopDetail />} />
          <Route path="/shop-reviews/:id" element={<ShopReviews />} />
          <Route path="/blog-detail/:id" element={<BlogDetail />} />
          <Route path="/blog-edit" element={
            <ProtectedRoute><BlogEdit /></ProtectedRoute>
          } />
          <Route path="/profile" element={
            <ProtectedRoute><MyProfile /></ProtectedRoute>
          } />
          <Route path="/profile-edit" element={
            <ProtectedRoute><ProfileEdit /></ProtectedRoute>
          } />
          <Route path="/account-security" element={
            <ProtectedRoute><AccountSecurity /></ProtectedRoute>
          } />
          <Route path="/user/:id" element={<OtherProfile />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/ai" element={<AiWorkspace />} />
          {/* 兼容旧版 .html URL 格式 */}
          <Route path="/index.html" element={<LegacyRedirect />} />
          <Route path="/login.html" element={<LegacyRedirect />} />
          <Route path="/login2.html" element={<LegacyRedirect />} />
          <Route path="/info.html" element={<LegacyRedirect />} />
          <Route path="/info-edit.html" element={<LegacyRedirect />} />
          <Route path="/blog-edit.html" element={<LegacyRedirect />} />
          <Route path="/shop-detail.html" element={<LegacyRedirect />} />
          <Route path="/blog-detail.html" element={<LegacyRedirect />} />
          <Route path="/shop-list.html" element={<LegacyRedirect />} />
          <Route path="/other-info.html" element={<LegacyRedirect />} />
        </Routes>
      </div>
    </div>
  );
}

export default function App() {
  const { i18n } = useTranslation();
  const mobileLocale = i18n.resolvedLanguage?.startsWith('zh') ? zhCN : enUS;

  return (
    <ConfigProvider locale={mobileLocale}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ConfigProvider>
  );
}
