import { Input } from 'antd-mobile';
import { useTranslation } from 'react-i18next';
import { PHONE_REGIONS } from '../../constants/phoneRegions';
import styles from './PhoneNumberField.module.css';

interface PhoneNumberFieldProps {
  regionCode: string;
  phoneNumber: string;
  onRegionChange: (regionCode: string) => void;
  onPhoneChange: (phoneNumber: string) => void;
}

export default function PhoneNumberField({
  regionCode,
  phoneNumber,
  onRegionChange,
  onPhoneChange,
}: PhoneNumberFieldProps) {
  const { t } = useTranslation();
  const selectedRegion = PHONE_REGIONS.find((region) => region.regionCode === regionCode) ?? PHONE_REGIONS[0];

  const changeRegion = (nextRegion: string) => {
    localStorage.setItem('phoneRegion', nextRegion);
    onRegionChange(nextRegion);
  };

  return (
    <div className={styles.phoneRow}>
      <div className={styles.regionPicker}>
        <span className={styles.regionValue} aria-hidden="true">
          <span>{selectedRegion.flag}</span>
          <span>{selectedRegion.callingCode}</span>
        </span>
        <svg className={styles.regionChevron} viewBox="0 0 12 8" aria-hidden="true">
          <path d="M1 1.5 6 6.5l5-5" />
        </svg>
        <select
          className={styles.regionSelect}
          value={regionCode}
          onChange={(event) => changeRegion(event.target.value)}
          aria-label={t('auth.regionLabel')}
        >
          {PHONE_REGIONS.map((region) => (
            <option key={region.regionCode} value={region.regionCode}>
              {region.flag} {region.callingCode}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.phoneInput}>
        <Input
          placeholder={t('auth.phonePlaceholder')}
          value={phoneNumber}
          onChange={onPhoneChange}
          inputMode="tel"
          autoComplete="tel-national"
          style={{ '--font-size': '15px' } as React.CSSProperties}
        />
      </div>
    </div>
  );
}
