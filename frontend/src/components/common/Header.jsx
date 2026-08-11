import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useThemeStore } from '../../stores/themeStore.js';
import { useProfileStore } from '../../stores/profileStore.js';
import { supabase } from '../../lib/supabase';
import { getEnterpriseMe } from '../../lib/enterpriseApi';
import ConfirmModal from './ConfirmModal.jsx';
import ProfilePopup from '../profile/ProfilePopup.jsx';

function UserMenu({ enterpriseKnowledgeEnabled, canOpenEnterpriseAdmin, onOpenProfile, onSignOut }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const profile = useProfileStore((state) => state.profile);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="Tài khoản"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-accent-foreground"
      >
        <Icon icon="lucide:user" width={16} height={16} />
      </button>

      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: -6 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: -6 }}
              transition={{ duration: 0.14, ease: 'easeOut' }}
              className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-xl border border-border bg-panel py-1.5 shadow-xl"
            >
              {profile && (
                <div className="border-b border-border px-3.5 py-2.5">
                  <div className="truncate text-[13px] font-semibold text-foreground">
                    {profile.display_name || 'Chưa đặt tên'}
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-faint">
                    {canOpenEnterpriseAdmin ? 'Quản trị kho tri thức' : 'Thành viên'}
                  </div>
                </div>
              )}
              {enterpriseKnowledgeEnabled && <button
                onClick={() => { setOpen(false); navigate('/knowledge'); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
              >
                <Icon icon="lucide:library-big" width={15} height={15} />
                Kho tri thức doanh nghiệp
              </button>}
              <button
                onClick={() => { setOpen(false); navigate('/reports/context-quality-v4'); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
              >
                <Icon icon="lucide:chart-no-axes-combined" width={15} height={15} />
                Báo cáo chất lượng ngữ cảnh v4
              </button>
              <button
                onClick={() => { setOpen(false); navigate('/tools/extraction-inspector'); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
              >
                <Icon icon="lucide:scan-text" width={15} height={15} />
                Kiểm tra trích xuất
              </button>
              <button
                onClick={() => { setOpen(false); onOpenProfile(); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
              >
                <Icon icon="lucide:user-round" width={15} height={15} />
                Hồ sơ
              </button>
              {enterpriseKnowledgeEnabled && canOpenEnterpriseAdmin && (
                  <button
                    onClick={() => { setOpen(false); navigate('/admin/knowledge'); }}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
                  >
                    <Icon icon="lucide:shield-check" width={15} height={15} />
                    Quản trị kho tri thức
                  </button>
              )}
              <button
                onClick={() => { setOpen(false); onSignOut(); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-red hover:bg-red/10"
              >
                <Icon icon="lucide:log-out" width={15} height={15} />
                Đăng xuất
              </button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

const ENTERPRISE_ADMIN_PERMISSIONS = new Set([
  'UPLOAD_DOCUMENT',
  'MANAGE_DOCUMENT',
  'REVIEW_DOCUMENT',
  'PUBLISH_DOCUMENT',
  'ARCHIVE_DOCUMENT',
  'MANAGE_ACCESS_POLICY',
  'MANAGE_USER',
  'MANAGE_ROLE',
  'MANAGE_GROUP',
  'MANAGE_DEPARTMENT',
  'VIEW_AUDIT',
  'VIEW_ANALYTICS',
  'MANAGE_REPORT',
]);

export default function Header({ enterpriseKnowledgeEnabled = true }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useThemeStore();
  const fetchProfile = useProfileStore((state) => state.fetchProfile);
  const [showSignOut, setShowSignOut] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [enterprisePermissions, setEnterprisePermissions] = useState([]);

  useEffect(() => {
    fetchProfile().catch((e) => console.error('Failed to fetch profile:', e));
  }, [fetchProfile]);

  useEffect(() => {
    if (!enterpriseKnowledgeEnabled) {
      setEnterprisePermissions([]);
      return undefined;
    }
    let cancelled = false;
    getEnterpriseMe()
      .then((me) => {
        if (!cancelled) setEnterprisePermissions(me.permissions);
      })
      .catch(() => {
        if (!cancelled) setEnterprisePermissions([]);
      });
    return () => { cancelled = true; };
  }, [enterpriseKnowledgeEnabled]);

  const canOpenEnterpriseAdmin = enterprisePermissions.some((permission) =>
    ENTERPRISE_ADMIN_PERMISSIONS.has(permission),
  );

  const handleSignOut = async () => {
    await supabase.auth.signOut();
  };

  return (
    <header className="z-10 flex h-14 shrink-0 items-center gap-4 border-b border-border bg-panel px-5">
      <button
        onClick={() => navigate('/knowledge')}
        className="flex shrink-0 items-center gap-2 rounded-md hover:opacity-80"
      >
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-foreground">
          <Icon icon="lucide:layers" width={14} height={14} />
        </div>
        <span className="font-heading text-[15px] font-bold tracking-tight text-foreground">Kho tri thức doanh nghiệp</span>
      </button>

      <div className="h-5 w-px bg-border" />

      <div className="flex flex-1 items-center gap-1.5 overflow-hidden">
        <span className="truncate text-[13px] font-semibold text-foreground">
          {location.pathname === '/admin/knowledge'
            ? 'Quản trị kho tri thức'
            : location.pathname === '/knowledge'
              ? 'Tra cứu tri thức doanh nghiệp'
            : location.pathname === '/tools/extraction-inspector'
              ? 'Kiểm tra trích xuất'
            : location.pathname === '/reports/context-quality-v4'
              ? 'Báo cáo chất lượng truy xuất ngữ cảnh v4'
              : 'Kho tri thức doanh nghiệp'}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2.5">
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-dim hover:bg-inset"
        >
          {theme === 'dark' ? (
            <Icon icon="lucide:sun" width={16} height={16} />
          ) : (
            <Icon icon="lucide:moon" width={16} height={16} />
          )}
        </button>
        <UserMenu
          enterpriseKnowledgeEnabled={enterpriseKnowledgeEnabled}
          canOpenEnterpriseAdmin={canOpenEnterpriseAdmin}
          onOpenProfile={() => setShowProfile(true)}
          onSignOut={() => setShowSignOut(true)}
        />
      </div>

      <ProfilePopup isOpen={showProfile} onClose={() => setShowProfile(false)} />

      <ConfirmModal
        isOpen={showSignOut}
        title="Đăng xuất"
        message="Bạn có chắc chắn muốn đăng xuất khỏi tài khoản của mình?"
        onConfirm={handleSignOut}
        onCancel={() => setShowSignOut(false)}
        confirmText="Đăng xuất"
        isDanger={false}
      />
    </header>
  );
}
