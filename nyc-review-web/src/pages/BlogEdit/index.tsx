import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { CloseOutline, SearchOutline, CameraOutline } from 'antd-mobile-icons';
import { Toast } from 'antd-mobile';
import { getShopLinkOptions, getShopTypes } from '../../api/shop';
import { uploadBlogImage, deleteBlogImage } from '../../api/upload';
import { createBlog } from '../../api/blog';
import { getMe } from '../../api/user';
import { useTranslation } from 'react-i18next';
import FootBar from '../../components/FootBar';
import { buildAuthEntryUrl } from '../../utils/authRedirect';
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
  const headerRef = useRef<HTMLDivElement>(null);
  const editorWorkspaceRef = useRef<HTMLDivElement>(null);
  const desktopNavigationRef = useRef<HTMLDivElement>(null);
  const shopTriggerRef = useRef<HTMLButtonElement>(null);
  const shopDialogRef = useRef<HTMLDivElement>(null);
  const shopSearchRef = useRef<HTMLInputElement>(null);
  const shopRequestRef = useRef(0);
  const publishingRef = useRef(false);
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
  const [publishing, setPublishing] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches
  ));
  const loginUrl = buildAuthEntryUrl('/login', '/blog-edit');

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)');
    const handleViewportChange = (event: MediaQueryListEvent | MediaQueryList) => {
      setIsDesktop(event.matches);
      if (event.matches) setShowDialog(false);
    };
    media.addEventListener('change', handleViewportChange);
    return () => media.removeEventListener('change', handleViewportChange);
  }, []);

  useEffect(() => {
    const token = sessionStorage.getItem('token');
    if (!token) {
      navigate(loginUrl);
      return;
    }
    getMe().catch(() => {
      Toast.show({ icon: 'fail', content: t('blogEdit.loginRequired') });
      setTimeout(() => navigate(loginUrl), 200);
    });
  }, [loginUrl, navigate, t]);

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
      const reportedTotal = typeof envelope.total === 'number' ? envelope.total : records.length;
      setShopTotal(Math.max(reportedTotal, (page - 1) * 30 + records.length));
      setShopPage(page);
    } catch {
      if (replace && requestId === shopRequestRef.current) {
        setShops([]);
        setShopTotal(0);
        setShopPage(1);
      }
    } finally {
      if (requestId === shopRequestRef.current) setShopsLoading(false);
    }
  }, [selectedTypeId, shopName]);

  const openShopDialog = () => {
    setShowDialog(true);
  };

  useEffect(() => {
    if (!showDialog && !isDesktop) return;
    if (shopTypes.length > 0) return;
    getShopTypes()
      .then((response) => setShopTypes(response.data ?? response))
      .catch(() => setShopTypes([]));
  }, [isDesktop, shopTypes.length, showDialog]);

  useEffect(() => {
    if (!showDialog && !isDesktop) return;
    const timer = window.setTimeout(() => {
      void queryShops(1, true, selectedTypeId, shopName);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [isDesktop, queryShops, selectedTypeId, shopName, showDialog]);

  useEffect(() => {
    if (!showDialog || isDesktop) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const backgroundElements = [
      headerRef.current,
      editorWorkspaceRef.current,
      desktopNavigationRef.current,
    ].filter((element): element is HTMLDivElement => Boolean(element));

    backgroundElements.forEach((element) => {
      element.inert = true;
      element.setAttribute('aria-hidden', 'true');
    });

    const focusTimer = window.setTimeout(() => shopSearchRef.current?.focus(), 0);
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setShowDialog(false);
        return;
      }
      if (event.key !== 'Tab') return;

      const dialog = shopDialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), '
        + 'select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey && (activeElement === first || !dialog.contains(activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || !dialog.contains(activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleDialogKeyDown);
      backgroundElements.forEach((element) => {
        element.inert = false;
        element.removeAttribute('aria-hidden');
      });
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [isDesktop, showDialog]);

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
    if (publishingRef.current) return;
    if (!selectedShop) {
      Toast.show({ icon: 'fail', content: t('blogEdit.shopRequired') });
      return;
    }
    publishingRef.current = true;
    setPublishing(true);
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
    } finally {
      publishingRef.current = false;
      setPublishing(false);
    }
  };

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  };

  const handleShopSelection = (shop: ShopItem, closeAfterSelection: boolean) => {
    setSelectedShop(shop);
    if (closeAfterSelection) setShowDialog(false);
  };

  const renderShopPicker = (closeAfterSelection: boolean) => (
    <>
      <div className={styles.categoryList} aria-label={t('blogEdit.categoryFilter')}>
        <button
          type="button"
          className={selectedTypeId == null ? styles.categoryActive : ''}
          onClick={() => setSelectedTypeId(undefined)}
        >
          {t('shopList.allCategories')}
        </button>
        {shopTypes.map((type) => (
          <button
            type="button"
            key={type.id}
            className={selectedTypeId === type.id ? styles.categoryActive : ''}
            onClick={() => setSelectedTypeId(type.id)}
          >
            {t(`shopTypes.${type.name}`, type.name)}
          </button>
        ))}
      </div>
      <div className={styles.searchBar}>
        <div className={styles.searchInput}>
          <button
            type="button"
            className={styles.searchAction}
            onClick={() => queryShops(1, true)}
            aria-label={t('blogEdit.searchShop')}
          >
            <SearchOutline fontSize={14} />
          </button>
          <input
            ref={shopSearchRef}
            value={shopName}
            onChange={(e) => setShopName(e.target.value)}
            type="text"
            placeholder={t('blogEdit.searchShop')}
            onKeyDown={(e) => { if (e.key === 'Enter') queryShops(1, true); }}
          />
        </div>
      </div>
      <div className={styles.resultSummary}>
        {shopsLoading
          ? t('blogEdit.searchingShops')
          : t('blogEdit.shopResults', { count: shopTotal })}
      </div>
      <div className={styles.shopList}>
        {shops.map((shop) => {
          const selected = selectedShop?.id === shop.id;
          return (
            <button
              type="button"
              key={shop.id}
              className={`${styles.shopItem} ${selected ? styles.shopItemSelected : ''}`}
              onClick={() => handleShopSelection(shop, closeAfterSelection)}
              aria-pressed={selected}
            >
              <span className={styles.shopItemCopy}>
                <span className={styles.shopItemName}>{shop.name}</span>
                <span className={styles.shopItemMeta}>
                  {[shop.area, shop.borough].filter(Boolean).join(', ')}
                </span>
              </span>
              {selected && <span className={styles.selectedMark} aria-hidden="true">✓</span>}
            </button>
          );
        })}
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
    </>
  );

  return (
    <div className={styles.container}>
      <div ref={headerRef} className={styles.header}>
        <div className={styles.cancelBtn} onClick={handleBack}>{t('blogEdit.cancel')}</div>
        <div className={styles.title}>{t('blogEdit.title')}</div>
        <div className={styles.commit}>
          <button
            type="button"
            className={styles.commitBtn}
            onClick={handleSubmit}
            disabled={publishing}
            aria-busy={publishing}
          >
            {t('blogEdit.publish')}
          </button>
        </div>
      </div>

      <div ref={editorWorkspaceRef} className={styles.editorWorkspace}>
        <div className={styles.mediaPanel}>
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
        </div>

        <main className={styles.editorPanel}>
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
          <div className={styles.desktopPublish}>
            <button
              type="button"
              className={styles.desktopPublishButton}
              onClick={handleSubmit}
              disabled={publishing}
              aria-busy={publishing}
            >
              {t('blogEdit.publish')}
            </button>
          </div>
        </main>

        <div className={styles.shopPanel}>
          <div className={styles.divider} />

          <button
            ref={shopTriggerRef}
            type="button"
            className={`${styles.blogShop} ${styles.mobileShopTrigger}`}
            onClick={openShopDialog}
          >
            <div className={styles.shopLeft}>{t('blogEdit.linkShop')}</div>
            {selectedShop ? (
              <div>{selectedShop.name}</div>
            ) : (
              <div className={styles.selectHint}>{t('blogEdit.selectShop')}</div>
            )}
          </button>

          {isDesktop && (
            <section className={styles.inlineShopPicker} aria-labelledby="inline-shop-picker-title">
              <div className={styles.inlineShopHeader}>
                <div id="inline-shop-picker-title" className={styles.shopLeft}>
                  {t('blogEdit.linkShop')}
                </div>
                <div className={styles.inlineSelection} aria-live="polite">
                  {selectedShop ? selectedShop.name : t('blogEdit.selectShop')}
                </div>
              </div>
              {renderShopPicker(false)}
            </section>
          )}
        </div>
      </div>

      {showDialog && (
        <>
          <div className={styles.mask} onClick={() => setShowDialog(false)} />
          <div
            ref={shopDialogRef}
            className={styles.shopDialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="shop-dialog-title"
          >
            <div className={styles.dialogHeader}>
              <div id="shop-dialog-title" className={styles.shopLeft}>{t('blogEdit.linkShop')}</div>
              <button type="button" onClick={() => setShowDialog(false)}>{t('common.cancel')}</button>
            </div>
            {renderShopPicker(true)}
          </div>
        </>
      )}

      <div ref={desktopNavigationRef} className={styles.desktopNavigation}>
        <FootBar activeBtn={3} />
      </div>
    </div>
  );
}
