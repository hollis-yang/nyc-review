export interface PhoneRegion {
  regionCode: string;
  callingCode: string;
  flag: string;
}

export const PHONE_REGIONS: PhoneRegion[] = [
  { regionCode: 'US', callingCode: '+1', flag: '🇺🇸' },
  { regionCode: 'CA', callingCode: '+1', flag: '🇨🇦' },
  { regionCode: 'CN', callingCode: '+86', flag: '🇨🇳' },
  { regionCode: 'TW', callingCode: '+886', flag: '🇹🇼' },
  { regionCode: 'HK', callingCode: '+852', flag: '🇭🇰' },
  { regionCode: 'MO', callingCode: '+853', flag: '🇲🇴' },
  { regionCode: 'GB', callingCode: '+44', flag: '🇬🇧' },
  { regionCode: 'JP', callingCode: '+81', flag: '🇯🇵' },
  { regionCode: 'KR', callingCode: '+82', flag: '🇰🇷' },
  { regionCode: 'SG', callingCode: '+65', flag: '🇸🇬' },
  { regionCode: 'AU', callingCode: '+61', flag: '🇦🇺' },
];

export function initialPhoneRegion(language?: string): string {
  const stored = localStorage.getItem('phoneRegion');
  if (stored && PHONE_REGIONS.some((region) => region.regionCode === stored)) {
    return stored;
  }
  return language?.startsWith('zh') ? 'CN' : 'US';
}
