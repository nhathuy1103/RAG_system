import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Icon } from '@iconify/react';
import { useNotebookStore } from '../../stores/notebookStore.js';
import { useThemeStore } from '../../stores/themeStore.js';
import { useUiStore } from '../../stores/uiStore.js';
import { useProfileStore } from '../../stores/profileStore.js';
import { supabase } from '../../lib/supabase';
import { getEnterpriseMe } from '../../lib/enterpriseApi';
import ConfirmModal from './ConfirmModal.jsx';
import ProfilePopup from '../profile/ProfilePopup.jsx';

function UserMenu({ enterpriseKnowledgeEnabled, canOpenEnterpriseAdmin, onOpenProfile, onSignOut }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const profile = useProfileStore((state) => state.profile);
  const isLegacyAdmin = profile?.role === 'admin';

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
                    {canOpenEnterpriseAdmin ? 'Quản trị Enterprise' : isLegacyAdmin ? 'Quản trị viên' : 'Thành viên'}
                  </div>
                </div>
              )}
              <button
                onClick={() => { setOpen(false); navigate('/legacy/notebooks'); }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
              >
                <Icon icon="lucide:home" width={15} height={15} />
                Notebook legacy
              </button>
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
                Báo cáo Context v4
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
                    Knowledge Admin
                  </button>
              )}
              {isLegacyAdmin && (
                  <button
                    onClick={() => { setOpen(false); navigate('/admin'); }}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] text-foreground hover:bg-inset"
                  >
                    <Icon icon="lucide:layout-dashboard" width={15} height={15} />
                    Admin Dashboard cũ
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
  const { activeNotebook } = useNotebookStore();
  const { theme, toggleTheme } = useThemeStore();
  const { sidebarOpen, toggleSidebar } = useUiStore();
  const fetchProfile = useProfileStore((state) => state.fetchProfile);
  const [showSignOut, setShowSignOut] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [enterprisePermissions, setEnterprisePermissions] = useState([]);

  const inWorkspace = location.pathname.startsWith('/notebook/');

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
        onClick={() => navigate(enterpriseKnowledgeEnabled ? '/knowledge' : '/legacy/notebooks')}
        className="flex shrink-0 items-center gap-2 rounded-md hover:opacity-80"
      >
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-foreground">
          <Icon icon="lucide:layers" width={14} height={14} />
        </div>
        <span className="font-heading text-[15px] font-bold tracking-tight text-foreground">Enterprise Knowledge</span>
      </button>

      <div className="h-5 w-px bg-border" />

      {inWorkspace && (
        <button
          onClick={toggleSidebar}
          title={sidebarOpen ? 'Ẩn thanh bên' : 'Hiện thanh bên'}
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border transition-colors ${
            sidebarOpen ? 'bg-accent/10 text-accent' : 'bg-background text-faint'
          } hover:bg-accent/10 hover:text-accent`}
        >
          <Icon icon="lucide:panel-left" width={16} height={16} />
        </button>
      )}

      <div className="flex flex-1 items-center gap-1.5 overflow-hidden">
        {inWorkspace ? (
          <>
            <button
              onClick={() => navigate('/legacy/notebooks')}
              title="Về sổ tay của tôi"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-inset hover:text-foreground"
            >
              <Icon icon="lucide:arrow-left" width={15} height={15} />
            </button>
            <button
              onClick={() => navigate('/legacy/notebooks')}
              className="shrink-0 text-[13px] text-faint hover:text-foreground hover:underline"
            >
              Notebook legacy
            </button>
            <Icon icon="lucide:chevron-right" width={14} height={14} />
            <span className="truncate text-[13px] font-semibold text-foreground">
              {activeNotebook ? activeNotebook.title : 'Chưa chọn sổ tay'}
            </span>
          </>
        ) : (
          <span className="truncate text-[13px] font-semibold text-foreground">
            {location.pathname === '/admin/knowledge'
              ? 'Knowledge Admin'
              : location.pathname === '/knowledge'
                ? 'Tra cứu tri thức doanh nghiệp'
              : location.pathname === '/admin'
              ? 'Admin Dashboard'
              : location.pathname === '/tools/extraction-inspector'
                ? 'Kiểm tra trích xuất'
              : location.pathname === '/reports/context-quality-v4'
                ? 'Báo cáo Contextual Retrieval v4'
                : 'Sổ tay của bạn'}
          </span>
        )}
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
