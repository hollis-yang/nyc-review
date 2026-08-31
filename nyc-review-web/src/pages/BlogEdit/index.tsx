import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { CloseOutline, SearchOutline, CameraOutline } from 'antd-mobile-icons';
import { Toast } from 'antd-mobile';
import { getShopLinkOptions, getShopTypes } from '../../api/shop';
import { uploadBlogImage, deleteBlogImage } from '../../api/upload';
import { createBlog } from '../../api/blog';
import { getMe } from '../../api/user';
import { useTranslation } from 'react-i18next';
import styles from './BlogEdit.module.css';

interface ShopItem {
  id: number;
  name: string;
  area: string;
  borough?: string;
  typeId?: number;
}

interface ShopTypeItem {
  id: number;
  name: string;
}

export default function BlogEdit() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const shopRequestRef = useRef(0);
  const [fileList, setFileList] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [showDialog, setShowDialog] = useState(false);
  const [shops, setShops] = useState<ShopItem[]>([]);
  const [shopName, setShopName] = useState('');
  const [selectedShop, setSelectedShop] = useState<ShopItem | null>(null);
  const [shopTypes, setShopTypes] = useState<ShopTypeItem[]>([]);
  const [selectedTypeId, setSelectedTypeId] = useState<number | undefined>();
  const [shopPage, setShopPage] = useState(1);
  const [shopTotal, setShopTotal] = useState(0);
  const [shopsLoading, setShopsLoading] = useState(false);

  useEffect(() => {
    const token = sessionStorage.getItem('token');
    if (!token) {
      navigate('/login');
      return;
    }
    getMe().catch(() => {
      Toast.show({ icon: 'fail', content: t('blogEdit.loginRequired') });
      setTimeout(() => navigate('/login'), 200);
    });
  }, [navigate, t]);

  const queryShops = useCallback(async (
    page = 1,
    replace = true,
    typeId = selectedTypeId,
    query = shopName,
  ) => {
    const requestId = ++shopRequestRef.current;
    setShopsLoading(true);
    try {
      const res = await getShopLinkOptions({ typeId, query: query.trim(), current: page, size: 30 });
      if (requestId !== shopRequestRef.current) return;
      const envelope = res as unknown as { data?: ShopItem[]; total?: number };
      const records = envelope.data ?? [];
      setShops((previous) => replace ? records : [...previous, ...records]);
      setShopTotal(typeof envelope.total === 'number' ? envelope.total : records.length);
      setShopPage(page);
    } catch {
      if (replace && requestId === shopRequestRef.current) setShops([]);
    } finally {
      if (requestId === shopRequestRef.current) setShopsLoading(false);
    }
  }, [selectedTypeId, shopName]);

  const openShopDialog = async () => {
    setShowDialog(true);
    if (shopTypes.length === 0) {
      getShopTypes()
        .then((response) => setShopTypes(response.data ?? response))
        .catch(() => setShopTypes([]));
    }
    await queryShops(1, true);
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await uploadBlogImage(file);
      const path = String(res.data ?? res);
      setFileList((prev) => [...prev, path]);
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDeletePic = async (index: number) => {
    const filePath = fileList[index];
    try {
      await deleteBlogImage(filePath);
      setFileList((prev) => prev.filter((_, i) => i !== index));
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleSubmit = async () => {
    if (!selectedShop) {
      Toast.show({ icon: 'fail', content: t('blogEdit.shopRequired') });
      return;
    }
    try {
      await createBlog({
        title,
        content,
        images: fileList.join(','),
        shopId: selectedShop.id,
      });
      navigate('/profile');
    } catch (err: unknown) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.cancelBtn} onClick={handleBack}>{t('blogEdit.cancel')}</div>
        <div className={styles.title}>{t('blogEdit.title')}</div>
        <div className={styles.commit}>
          <div className={styles.commitBtn} onClick={handleSubmit}>{t('blogEdit.publish')}</div>
        </div>
      </div>

      <div className={styles.uploadBox}>
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          accept="image/jpeg,image/png,image/webp"
          style={{ display: 'none' }}
        />
        <div className={styles.uploadBtn} onClick={() => fileInputRef.current?.click()}>
          <CameraOutline fontSize={22} />
          <div className={styles.uploadText}>{t('blogEdit.uploadPhoto')}</div>
        </div>
        <div className={styles.picList}>
          {fileList.map((f, i) => (
            <div key={i} className={styles.picBox}>
              <img src={f} alt="" />
              <div className={styles.closeIcon} onClick={() => handleDeletePic(i)}>
                <CloseOutline fontSize={14} color="#fff" />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className={styles.blogTitle}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          type="text"
          placeholder={t('blogEdit.titlePlaceholder')}
        />
      </div>
      <div className={styles.blogContent}>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={t('blogEdit.contentPlaceholder')}
        />
      </div>

      <div className={styles.divider} />

      <div className={styles.blogShop} onClick={openShopDialog}>
        <div className={styles.shopLeft}>{t('blogEdit.linkShop')}</div>
        {selectedShop ? (
          <div>{selectedShop.name}</div>
        ) : (
          <div className={styles.selectHint}>{t('blogEdit.selectShop')}</div>
        )}
      </div>

      {showDialog && (
        <>
          <div className={styles.mask} onClick={() => setShowDialog(false)} />
          <div className={styles.shopDialog}>
            <div className={styles.dialogHeader}>
              <div className={styles.shopLeft}>{t('blogEdit.linkShop')}</div>
              <button type="button" onClick={() => setShowDialog(false)}>{t('common.cancel')}</button>
            </div>
            <div className={styles.categoryList} aria-label={t('blogEdit.categoryFilter')}>
              <button
                type="button"
                className={selectedTypeId == null ? styles.categoryActive : ''}
                onClick={() => {
                  setSelectedTypeId(undefined);
                  queryShops(1, true, undefined, shopName);
                }}
              >
                {t('shopList.allCategories')}
              </button>
              {shopTypes.map((type) => (
                <button
                  type="button"
                  key={type.id}
                  className={selectedTypeId === type.id ? styles.categoryActive : ''}
                  onClick={() => {
                    setSelectedTypeId(type.id);
                    queryShops(1, true, type.id, shopName);
                  }}
                >
                  {t(`shopTypes.${type.name}`, type.name)}
                </button>
              ))}
            </div>
            <div className={styles.searchBar}>
              <div className={styles.searchInput}>
                <SearchOutline fontSize={14} onClick={() => queryShops(1, true)} style={{ cursor: 'pointer' }} />
                <input
                  value={shopName}
                  onChange={(e) => setShopName(e.target.value)}
                  type="text"
                  placeholder={t('blogEdit.searchShop')}
                  onKeyDown={(e) => { if (e.key === 'Enter') queryShops(1, true); }}
                />
              </div>
            </div>
            <div className={styles.resultSummary}>
              {t('blogEdit.shopResults', { count: shopTotal })}
            </div>
            <div className={styles.shopList}>
              {shops.map((s) => (
                <div
                  key={s.id}
                  className={styles.shopItem}
                  onClick={() => { setSelectedShop(s); setShowDialog(false); }}
                >
                  <div className={styles.shopItemName}>{s.name}</div>
                  <div style={{ fontSize: 11, color: '#999' }}>{[s.area, s.borough].filter(Boolean).join(', ')}</div>
                </div>
              ))}
              {shopsLoading && <div className={styles.listStatus}>{t('home.loading')}</div>}
              {!shopsLoading && shops.length === 0 && (
                <div className={styles.listStatus}>{t('blogEdit.noShops')}</div>
              )}
              {!shopsLoading && shops.length < shopTotal && (
                <button
                  type="button"
                  className={styles.loadMore}
                  onClick={() => queryShops(shopPage + 1, false)}
                >
                  {t('blogEdit.loadMore')}
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
