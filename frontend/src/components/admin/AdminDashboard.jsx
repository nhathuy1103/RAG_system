import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { Icon } from '@iconify/react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { useProfileStore } from '../../stores/profileStore.js';
import { getAdminUserCount, getAdminAuthEvents, getAdminAuditLog } from '../../lib/api';

const ACTION_LABELS = {
  login: 'Đăng nhập',
  logout: 'Đăng xuất',
  user_signedup: 'Đăng ký',
};

function formatDateTime(value) {
  return new Date(value).toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function StatCard({ icon, label, value, index }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.05, ease: 'easeOut' }}
      className="flex items-center gap-3.5 rounded-2xl border border-border bg-panel p-5"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
        <Icon icon={icon} width={20} height={20} />
      </div>
      <div className="min-w-0">
        <div className="font-heading text-2xl font-bold text-foreground">{value}</div>
        <div className="text-[12.5px] text-faint">{label}</div>
      </div>
    </motion.div>
  );
}

function formatDay(value) {
  const d = new Date(value);
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
}

export default function AdminDashboard() {
  const profile = useProfileStore((state) => state.profile);
  const [userCount, setUserCount] = useState(null);
  const [authEvents, setAuthEvents] = useState([]);
  const [auditLog, setAuditLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (profile?.role !== 'admin') return;
    let cancelled = false;
    setLoading(true);
    Promise.all([getAdminUserCount(), getAdminAuthEvents(30), getAdminAuditLog(50)])
      .then(([count, events, log]) => {
        if (cancelled) return;
        setUserCount(count.total_users);
        setAuthEvents(events.days.map((d) => ({ ...d, dayLabel: formatDay(d.day) })));
        setAuditLog(log.entries);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Không thể tải số liệu admin');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [profile]);

  // profileStore hasn't resolved yet - avoid a false-negative redirect flash.
  if (profile === null) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-faint">Đang tải...</div>
    );
  }

  if (profile.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  const totalSignups = authEvents.reduce((sum, d) => sum + d.signups, 0);
  const totalLogins = authEvents.reduce((sum, d) => sum + d.logins, 0);
  const totalLogouts = authEvents.reduce((sum, d) => sum + d.logouts, 0);

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-[1000px]">
        <div className="mb-7">
          <div className="font-heading text-2xl font-bold text-foreground">Admin Dashboard</div>
          <div className="mt-1 text-sm text-dim">Thống kê người dùng và hoạt động đăng nhập/đăng ký.</div>
        </div>

        {error && (
          <div className="mb-5 rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-sm text-red">
            {error}
          </div>
        )}

        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard icon="lucide:users" label="Tổng số user" value={userCount ?? '—'} index={0} />
          <StatCard icon="lucide:user-plus" label={`Đăng ký (${authEvents.length} ngày gần nhất)`} value={totalSignups} index={1} />
          <StatCard icon="lucide:log-in" label={`Đăng nhập (${authEvents.length} ngày gần nhất)`} value={totalLogins} index={2} />
          <StatCard icon="lucide:log-out" label={`Đăng xuất (${authEvents.length} ngày gần nhất)`} value={totalLogouts} index={3} />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.22, delay: 0.15, ease: 'easeOut' }}
          className="rounded-2xl border border-border bg-panel p-5"
        >
          <div className="mb-4 text-[13.5px] font-semibold text-foreground">
            Đăng ký &amp; đăng nhập &amp; đăng xuất theo ngày
          </div>
          {loading ? (
            <div className="flex h-[300px] items-center justify-center text-sm text-faint">Đang tải biểu đồ...</div>
          ) : authEvents.length === 0 ? (
            <div className="flex h-[300px] items-center justify-center text-sm text-faint">Chưa có dữ liệu</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={authEvents} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="dayLabel" tick={{ fill: 'var(--faint)', fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: 'var(--faint)', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    background: 'var(--panel, #fff)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    fontSize: 12.5,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12.5 }} />
                <Bar dataKey="signups" name="Đăng ký" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="logins" name="Đăng nhập" fill="var(--green, #16a34a)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="logouts" name="Đăng xuất" fill="var(--red, #dc2626)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.22, delay: 0.2, ease: 'easeOut' }}
          className="mt-6 rounded-2xl border border-border bg-panel p-5"
        >
          <div className="mb-4 text-[13.5px] font-semibold text-foreground">
            Lịch sử đăng nhập gần đây
          </div>
          {loading ? (
            <div className="flex h-[160px] items-center justify-center text-sm text-faint">Đang tải...</div>
          ) : auditLog.length === 0 ? (
            <div className="flex h-[160px] items-center justify-center text-sm text-faint">Chưa có dữ liệu</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-border text-[12px] text-faint">
                    <th className="py-2 pr-4 font-medium">Thời gian</th>
                    <th className="py-2 pr-4 font-medium">Hành động</th>
                    <th className="py-2 pr-4 font-medium">Email</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLog.map((entry, i) => (
                    <tr key={`${entry.created_at}-${i}`} className="border-b border-border/60 last:border-0">
                      <td className="py-2 pr-4 whitespace-nowrap text-dim">{formatDateTime(entry.created_at)}</td>
                      <td className="py-2 pr-4 whitespace-nowrap text-foreground">
                        {ACTION_LABELS[entry.action] || entry.action || '—'}
                      </td>
                      <td className="py-2 pr-4 truncate text-dim">{entry.email || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
