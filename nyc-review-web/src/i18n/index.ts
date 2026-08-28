import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zhCN from './locales/zh-CN.json';

const savedLanguage = localStorage.getItem('appLanguage');
const initialLanguage = savedLanguage === 'zh-CN' ? 'zh-CN' : 'en';

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    'zh-CN': { translation: zhCN },
  },
  lng: initialLanguage,
  supportedLngs: ['en', 'zh-CN'],
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

document.documentElement.lang = initialLanguage;

export default i18n;
