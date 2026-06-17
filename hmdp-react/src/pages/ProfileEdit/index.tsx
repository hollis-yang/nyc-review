import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { LeftOutline, RightOutline } from 'antd-mobile-icons';
import { Picker, DatePicker, Toast, Input, TextArea, Button, Popup, CascadePicker } from 'antd-mobile';
import { getMe, getUserInfo, updateUser, updateUserInfo } from '../../api/user';
import { uploadBlogImage } from '../../api/upload';
import FootBar from '../../components/FootBar';
import regions from '../../constants/regions';
import styles from './ProfileEdit.module.css';

type EditField = 'nickname' | 'introduce' | null;

export default function ProfileEdit() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [user, setUser] = useState<{ id: number; nickName: string; icon: string } | null>(null);
  const [info, setInfo] = useState<Record<string, any>>({});
  const [genderVisible, setGenderVisible] = useState(false);
  const [dateVisible, setDateVisible] = useState(false);
  const [editField, setEditField] = useState<EditField>(null);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [cityPickerVisible, setCityPickerVisible] = useState(false);

  useEffect(() => {
    getMe()
      .then((res) => {
        const u = res.data ?? res;
        setUser(u);
        getUserInfo(u.id)
          .then((r) => {
            const infoData = r.data ?? r;
            if (infoData) {
              setInfo(infoData);
              sessionStorage.setItem('userInfo', JSON.stringify(infoData));
            }
          })
          .catch(() => {});
      })
      .catch(() => {
        setTimeout(() => navigate('/login'), 1000);
      });
  }, [navigate]);

  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate('/profile');
  };

  // ---- 头像 ----
  const handleAvatarClick = () => fileInputRef.current?.click();

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await uploadBlogImage(file);
      const iconPath = res.data ?? res;
      await updateUser({ icon: String(iconPath) });
      setUser((prev) => (prev ? { ...prev, icon: String(iconPath) } : prev));
      Toast.show({ icon: 'success', content: '头像已更新' });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
    e.target.value = '';
  };

  // ---- 文本编辑弹窗 ----
  const openTextEdit = (field: EditField, currentValue: string) => {
    setEditField(field);
    setEditValue(currentValue);
  };

  const handleTextSave = async () => {
    if (saving) return;
    setSaving(true);
    try {
      if (editField === 'nickname') {
        await updateUser({ nickName: editValue });
        setUser((prev) => (prev ? { ...prev, nickName: editValue } : prev));
      } else if (editField === 'introduce') {
        await updateUserInfo({ introduce: editValue });
        setInfo((prev) => ({ ...prev, introduce: editValue }));
      }
      Toast.show({ icon: 'success', content: '已更新' });
      setEditField(null);
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const fieldLabels: Record<string, string> = {
    nickname: '修改昵称',
    introduce: '修改个人介绍',
  };

  // ---- 性别 ----
  const genderColumns = [
    { label: '男', value: 'true' },
    { label: '女', value: 'false' },
  ];

  const handleGenderConfirm = async (value: any[]) => {
    setGenderVisible(false);
    const gender = value[0];
    if (!gender) return;
    try {
      await updateUserInfo({ gender: gender === 'true' });
      setInfo((prev) => ({ ...prev, gender: gender === 'true' }));
      Toast.show({ icon: 'success', content: '性别已更新' });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  // ---- 生日 ----
  const handleBirthdayConfirm = async (value: Date | null) => {
    setDateVisible(false);
    if (!value) return;
    const birthday = `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    try {
      await updateUserInfo({ birthday });
      setInfo((prev) => ({ ...prev, birthday }));
      Toast.show({ icon: 'success', content: '生日已更新' });
    } catch (err: any) {
      Toast.show({ icon: 'fail', content: String(err) });
    }
  };

  const genderLabel =
    info.gender === true || info.gender === 'true'
      ? '男'
      : info.gender === false || info.gender === 'false'
        ? '女'
        : '选择';

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.backBtn} onClick={handleBack}>
          <LeftOutline fontSize={18} color="white" />
        </div>
        <div className={styles.title}>资料编辑</div>
      </div>

      <div className={styles.scroll}>
        {/* 基本信息 */}
        <div className={styles.infoBox}>
          <div className={styles.infoItem} onClick={handleAvatarClick}>
            <div className={styles.infoLabel}>头像</div>
            <div className={styles.infoBtn}>
              <img width="35" src={user?.icon || '/imgs/icons/default-icon.png'} alt="" style={{ borderRadius: '50%' }} />
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleAvatarChange} />
          <div className={styles.divider} />
          <div className={styles.infoItem} onClick={() => openTextEdit('nickname', user?.nickName || '')}>
            <div className={styles.infoLabel}>昵称</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{user?.nickName || ''}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem} onClick={() => openTextEdit('introduce', info.introduce || '')}>
            <div className={styles.infoLabel}>个人介绍</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.introduce || '介绍一下自己'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>

        {/* 详细信息 */}
        <div className={styles.infoBox}>
          <div className={styles.infoItem} onClick={() => setGenderVisible(true)}>
            <div className={styles.infoLabel}>性别</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{genderLabel}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem} onClick={() => setCityPickerVisible(true)}>
            <div className={styles.infoLabel}>城市</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.city || '选择'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem} onClick={() => setDateVisible(true)}>
            <div className={styles.infoLabel}>生日</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.birthday || '添加'}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>

        {/* 积分/会员 */}
        <div className={styles.infoBox}>
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>我的积分</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>{info.credits ?? 0}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
          <div className={styles.divider} />
          <div className={styles.infoItem}>
            <div className={styles.infoLabel}>会员等级</div>
            <div className={styles.infoBtn}>
              <div className={styles.infoValue}>Lv.{info.level ?? 0}</div>
              <RightOutline fontSize={14} color="#ccc" />
            </div>
          </div>
        </div>

        {/* 文本编辑弹出层 */}
        <Popup
          visible={!!editField}
          onMaskClick={() => setEditField(null)}
          bodyStyle={{ borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: '20px 16px 32px', overflow: 'hidden', boxSizing: 'border-box' }}
        >
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 16, textAlign: 'center' }}>
            {editField ? fieldLabels[editField] : ''}
          </div>
          <div style={{ width: '100%', boxSizing: 'border-box' }}>
          {editField === 'introduce' ? (
            <TextArea
              value={editValue}
              onChange={(val) => setEditValue(val)}
              placeholder="介绍一下自己"
              rows={4}
              maxLength={128}
              style={{ '--font-size': '15px' }}
            />
          ) : (
            <Input
              value={editValue}
              onChange={(val) => setEditValue(val)}
              placeholder="请输入"
              clearable
              style={{ '--font-size': '15px' }}
            />
          )}
          </div>
          <Button
            block
            color="primary"
            size="large"
            loading={saving}
            onClick={handleTextSave}
            style={{ marginTop: 20, borderRadius: 22 }}
          >
            保存
          </Button>
        </Popup>

        {/* 性别选择 */}
        <Picker
          columns={[genderColumns]}
          visible={genderVisible}
          onClose={() => setGenderVisible(false)}
          value={[info.gender === true || info.gender === 'true' ? 'true' : 'false']}
          onConfirm={handleGenderConfirm}
          title="选择性别"
        />

        {/* 生日选择 */}
        <DatePicker
          visible={dateVisible}
          onClose={() => setDateVisible(false)}
          min={new Date(1950, 0, 1)}
          max={new Date()}
          onConfirm={handleBirthdayConfirm}
          title="选择生日"
        />

        {/* 城市选择 */}
        <CascadePicker
          options={regions}
          visible={cityPickerVisible}
          onClose={() => setCityPickerVisible(false)}
          onConfirm={async (value: any[]) => {
            setCityPickerVisible(false);
            const cityStr = value.filter(Boolean).join(' ');
            if (!cityStr) return;
            try {
              await updateUserInfo({ city: cityStr });
              setInfo((prev) => ({ ...prev, city: cityStr }));
              Toast.show({ icon: 'success', content: '城市已更新' });
            } catch (err: any) {
              Toast.show({ icon: 'fail', content: String(err) });
            }
          }}
          title="选择城市"
        />
      </div>

      <FootBar activeBtn={4} />
    </div>
  );
}
