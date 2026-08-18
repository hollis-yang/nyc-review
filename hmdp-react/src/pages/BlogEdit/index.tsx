import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { CloseOutline, SearchOutline, CameraOutline } from 'antd-mobile-icons';
import { Toast } from 'antd-mobile';
import { getShopsByName } from '../../api/shop';
import { uploadBlogImage, deleteBlogImage } from '../../api/upload';
import { createBlog } from '../../api/blog';
import { getMe } from '../../api/user';
import styles from './BlogEdit.module.css';

interface ShopItem {
  id: number;
  name: string;
  area: string;
}

export default function BlogEdit() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileList, setFileList] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [showDialog, setShowDialog] = useState(false);
  const [shops, setShops] = useState<ShopItem[]>([]);
  const [shopName, setShopName] = useState('');
  const [selectedShop, setSelectedShop] = useState<ShopItem | null>(null);

  useEffect(() => {
    const token = sessionStorage.getItem('token');
    if (!token) {
      navigate('/login');
      return;
    }
    getMe().catch(() => {
      Toast.show({ icon: 'fail', content: '请先登录' });
      setTimeout(() => navigate('/login'), 200);
    });
  }, [navigate]);

  const queryShops = async () => {
    try {
      const res = await getShopsByName(shopName);
      setShops(res.data ?? res);
    } catch {
      // ignore
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await uploadBlogImage(file);
      const path = String(res.data ?? res);
      setFileList((prev) => [...prev, path]);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDeletePic = async (index: number) => {
    const filePath = fileList[index];
    try {
      await deleteBlogImage(filePath);
      setFileList((prev) => prev.filter((_, i) => i !== index));
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const handleSubmit = async () => {
    if (!selectedShop) {
      Toast.show({ icon: 'fail', content: '请选择关联商户' });
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
    } catch (err: any) {
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
        <div className={styles.cancelBtn} onClick={handleBack}>取消</div>
        <div className={styles.title}>发笔记</div>
        <div className={styles.commit}>
          <div className={styles.commitBtn} onClick={handleSubmit}>发布</div>
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
          <div className={styles.uploadText}>上传照片</div>
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
          placeholder="填写标题更容易上首页哦~"
        />
      </div>
      <div className={styles.blogContent}>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="最近打卡了什么地方，有什么新奇体验呢？"
        />
      </div>

      <div className={styles.divider} />

      <div className={styles.blogShop} onClick={() => { setShowDialog(true); queryShops(); }}>
        <div className={styles.shopLeft}>关联商户</div>
        {selectedShop ? (
          <div>{selectedShop.name}</div>
        ) : (
          <div className={styles.selectHint}>去选择 &gt;</div>
        )}
      </div>

      {showDialog && (
        <>
          <div className={styles.mask} onClick={() => setShowDialog(false)} />
          <div className={styles.shopDialog}>
            <div className={styles.dialogHeader}>
              <div className={styles.shopLeft}>关联商户</div>
            </div>
            <div className={styles.searchBar}>
              <div className={styles.citySelect}>NYC</div>
              <div className={styles.searchInput}>
                <SearchOutline fontSize={14} onClick={queryShops} style={{ cursor: 'pointer' }} />
                <input
                  value={shopName}
                  onChange={(e) => setShopName(e.target.value)}
                  type="text"
                  placeholder="搜索商户名称"
                  onKeyDown={(e) => { if (e.key === 'Enter') queryShops(); }}
                />
              </div>
            </div>
            <div className={styles.shopList}>
              {shops.map((s) => (
                <div
                  key={s.id}
                  className={styles.shopItem}
                  onClick={() => { setSelectedShop(s); setShowDialog(false); }}
                >
                  <div className={styles.shopItemName}>{s.name}</div>
                  <div style={{ fontSize: 11, color: '#999' }}>{s.area}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
