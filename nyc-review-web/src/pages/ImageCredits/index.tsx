import { useEffect, useState } from 'react';
import { LeftOutline } from 'antd-mobile-icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import styles from './ImageCredits.module.css';

interface CreditAsset {
  assetId?: string;
  title: string;
  sourceUrl: string;
  licenseName: string;
  licenseUrl: string;
  attribution: string;
  publicUrl: string;
}

interface CreditManifest {
  assets: CreditAsset[];
}

export default function ImageCredits() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [assets, setAssets] = useState<CreditAsset[]>([]);

  useEffect(() => {
    fetch('/merchant-visuals/credits.json')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then((manifest: CreditManifest) => setAssets(manifest.assets || []))
      .catch(() => setAssets([]));
  }, []);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <button onClick={() => navigate(-1)} aria-label={t('common.back')}>
          <LeftOutline fontSize={18} />
        </button>
        <h1>{t('imageCredits.title')}</h1>
        <span />
      </header>
      <main className={styles.content}>
        <p className={styles.intro}>{t('imageCredits.intro', { count: assets.length })}</p>
        <div className={styles.grid}>
          {assets.map((asset) => (
            <article key={asset.assetId || asset.sourceUrl}>
              <img src={asset.publicUrl} alt="" loading="lazy" />
              <div>
                <strong>{asset.attribution}</strong>
                <span>{asset.licenseName}</span>
                <a href={asset.sourceUrl} target="_blank" rel="noreferrer">{t('imageCredits.source')}</a>
                <a href={asset.licenseUrl} target="_blank" rel="noreferrer">{t('imageCredits.license')}</a>
              </div>
            </article>
          ))}
        </div>
      </main>
    </div>
  );
}
