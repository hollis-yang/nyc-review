import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';

localStorage.setItem('appLanguage', 'en');

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
  },
  lng: 'en',
  supportedLngs: ['en'],
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18n;
