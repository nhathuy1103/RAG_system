import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useProfileStore } from '../../stores/profileStore.js';
import { useToastStore } from '../../stores/toastStore.js';

export default function ProfilePopup({ isOpen, onClose }) {
  const { profile, saveProfile } = useProfileStore();
  const showToast = useToastStore((state) => state.showToast);

  const [displayName, setDisplayName] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setDisplayName(profile?.display_name || '');
      setIsEditing(false);
    }
  }, [isOpen, profile]);

  const handleSave = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await saveProfile({ display_name: displayName.trim() || null });
      setIsEditing(false);
      showToast('Đã lưu hồ sơ', 'success');
    } catch (err) {
      showToast(err.message || 'Không thể lưu hồ sơ', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 px-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-[380px] rounded-xl border border-border bg-panel p-6 shadow-xl"
          >
            <div className="mb-5 flex items-center justify-between">
              <div className="font-heading text-lg font-semibold text-foreground">Hồ sơ</div>
              <button
                onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-md text-faint hover:bg-inset hover:text-foreground"
              >
                <Icon icon="lucide:x" width={16} height={16} />
              </button>
            </div>

            {!profile ? (
              <div className="py-8 text-center text-sm text-faint">Đang tải...</div>
            ) : (
              <form onSubmit={handleSave}>
                <div className="mb-5 flex items-center gap-3">
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
                    <Icon icon="lucide:user-round" width={24} height={24} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-[13.5px] font-semibold text-foreground">
                      {profile.display_name || 'Chưa đặt tên'}
                    </div>
                    <div className="mt-0.5 truncate text-[12px] text-faint">
                      {profile.email}
                    </div>
                  </div>
                </div>

                <div className="mb-5 flex items-center gap-1.5 text-[12.5px] text-dim">
                  <Icon icon="lucide:shield-check" width={14} height={14} />
                  {profile.role === 'admin' ? 'Quản trị viên' : 'Thành viên'}
                </div>

                <div className="mb-5">
                  <label className="mb-1.5 block text-[13px] font-medium text-dim">Tên hiển thị</label>
                  {isEditing ? (
                    <input
                      autoFocus
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="Nhập tên hiển thị"
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
                    />
                  ) : (
                    <div className="flex items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                      <span className="truncate">{profile.display_name || 'Chưa đặt tên'}</span>
                      <button
                        type="button"
                        onClick={() => setIsEditing(true)}
                        className="shrink-0 text-[12.5px] font-medium text-accent hover:underline"
                      >
                        Sửa
                      </button>
                    </div>
                  )}
                </div>

                <div className="mb-5 text-[12px] text-faint">
                  Tham gia từ {new Date(profile.created_at).toLocaleDateString('vi-VN')}
                </div>

                {isEditing && (
                  <div className="flex justify-end gap-2.5">
                    <button
                      type="button"
                      onClick={() => { setIsEditing(false); setDisplayName(profile.display_name || ''); }}
                      className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-inset"
                    >
                      Hủy
                    </button>
                    <button
                      type="submit"
                      disabled={isSaving}
                      className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent-dim disabled:opacity-60"
                    >
                      {isSaving ? 'Đang lưu...' : 'Lưu'}
                    </button>
                  </div>
                )}
              </form>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
