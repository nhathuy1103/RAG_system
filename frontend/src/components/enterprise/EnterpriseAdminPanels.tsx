import { Icon } from "@iconify/react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  EnterpriseAnalyticsSummary,
  EnterpriseAnswerReport,
  EnterpriseAuditLog,
  EnterpriseUserProfile,
  FunctionalPermission,
  OrganizationUnit,
  UserDepartmentMembership,
  UserGroupMembership,
  UserRoleMembership,
  assignEnterpriseMembership,
  assignEnterpriseRolePermission,
  createEnterpriseOrganization,
  getEnterpriseAnalytics,
  listEnterpriseAnswerReports,
  listEnterpriseAuditLogs,
  listEnterpriseDepartments,
  listEnterpriseGroups,
  listEnterpriseFunctionalPermissions,
  listEnterpriseRolePermissions,
  listEnterpriseRoles,
  listEnterpriseUserDepartments,
  listEnterpriseUserGroups,
  listEnterpriseUserRoles,
  listEnterpriseUsers,
  removeEnterpriseMembership,
  removeEnterpriseRolePermission,
  resolveEnterpriseAnswerReport,
  provisionEnterpriseEmployee,
  updateEnterpriseUser,
} from "../../lib/enterpriseApi";

type Notify = (message: string) => void;
type AdminPanelProps = {
  permissions: ReadonlySet<string>;
  onError: Notify;
  onSuccess: Notify;
};

function readableDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function PanelLoader({ label }: { label: string }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-2xl border border-border bg-panel text-sm text-faint">
      <Icon icon="lucide:loader-circle" width={18} className="mr-2 animate-spin" /> {label}
    </div>
  );
}

export function IdentityAdminPanel({ permissions, onError, onSuccess }: AdminPanelProps) {
  const [users, setUsers] = useState<EnterpriseUserProfile[]>([]);
  const [roles, setRoles] = useState<OrganizationUnit[]>([]);
  const [groups, setGroups] = useState<OrganizationUnit[]>([]);
  const [departments, setDepartments] = useState<OrganizationUnit[]>([]);
  const [functionalPermissions, setFunctionalPermissions] = useState<FunctionalPermission[]>([]);
  const [rolePermissions, setRolePermissions] = useState<FunctionalPermission[]>([]);
  const [userRoles, setUserRoles] = useState<UserRoleMembership[]>([]);
  const [userGroups, setUserGroups] = useState<UserGroupMembership[]>([]);
  const [userDepartments, setUserDepartments] = useState<UserDepartmentMembership[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [organizationKind, setOrganizationKind] = useState<"roles" | "groups" | "departments">("groups");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [roleId, setRoleId] = useState("");
  const [membershipKind, setMembershipKind] = useState<"roles" | "groups" | "departments">("roles");
  const [objectId, setObjectId] = useState("");
  const [employeeEmail, setEmployeeEmail] = useState("");
  const [employeeName, setEmployeeName] = useState("");
  const [employeeCode, setEmployeeCode] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");

  const canManageUsers = permissions.has("MANAGE_USER");
  const canManageRoles = permissions.has("MANAGE_ROLE");
  const canManageGroups = permissions.has("MANAGE_GROUP");
  const canManageDepartments = permissions.has("MANAGE_DEPARTMENT");
  const organizationKinds = useMemo<Array<"roles" | "groups" | "departments">>(() => {
    const allowed: Array<"roles" | "groups" | "departments"> = [];
    if (canManageRoles) allowed.push("roles");
    if (canManageGroups) allowed.push("groups");
    if (canManageDepartments) allowed.push("departments");
    return allowed;
  }, [canManageDepartments, canManageGroups, canManageRoles]);

  async function reload() {
    setLoading(true);
    try {
      const [userPage, nextRoles, nextGroups, nextDepartments, nextPermissions] = await Promise.all([
        canManageUsers ? listEnterpriseUsers() : Promise.resolve(null),
        canManageRoles ? listEnterpriseRoles() : Promise.resolve(null),
        canManageGroups ? listEnterpriseGroups() : Promise.resolve(null),
        canManageDepartments ? listEnterpriseDepartments() : Promise.resolve(null),
        canManageRoles ? listEnterpriseFunctionalPermissions() : Promise.resolve(null),
      ]);
      setUsers(userPage?.items ?? []);
      setRoles(nextRoles ?? []);
      setGroups(nextGroups ?? []);
      setDepartments(nextDepartments ?? []);
      setFunctionalPermissions(nextPermissions ?? []);
      if (nextRoles?.length) setRoleId((current) => current || nextRoles[0].id);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tải dữ liệu IAM");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [canManageDepartments, canManageGroups, canManageRoles, canManageUsers]);

  useEffect(() => {
    const firstAllowed = organizationKinds[0];
    if (!firstAllowed) return;
    if (!organizationKinds.includes(organizationKind)) setOrganizationKind(firstAllowed);
    if (!organizationKinds.includes(membershipKind)) {
      setMembershipKind(firstAllowed);
      setObjectId("");
    }
  }, [membershipKind, organizationKind, organizationKinds]);

  useEffect(() => {
    if (!userId) {
      setUserRoles([]);
      setUserGroups([]);
      setUserDepartments([]);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    Promise.all([
      canManageRoles ? listEnterpriseUserRoles(userId) : Promise.resolve([]),
      canManageGroups ? listEnterpriseUserGroups(userId) : Promise.resolve([]),
      canManageDepartments
        ? listEnterpriseUserDepartments(userId, true)
        : Promise.resolve([]),
    ])
      .then(([nextRoles, nextGroups, nextDepartments]) => {
        if (cancelled) return;
        setUserRoles(nextRoles);
        setUserGroups(nextGroups);
        setUserDepartments(nextDepartments);
      })
      .catch((cause: unknown) => {
        if (!cancelled) onError(cause instanceof Error ? cause.message : "Không thể tải membership");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [canManageDepartments, canManageGroups, canManageRoles, userId]);

  useEffect(() => {
    if (!canManageRoles || !roleId) {
      setRolePermissions([]);
      return;
    }
    let cancelled = false;
    listEnterpriseRolePermissions(roleId)
      .then((items) => { if (!cancelled) setRolePermissions(items); })
      .catch((cause: unknown) => {
        if (!cancelled) onError(cause instanceof Error ? cause.message : "Không thể tải quyền của role");
      });
    return () => { cancelled = true; };
  }, [canManageRoles, roleId]);

  const membershipOptions = useMemo(() => {
    if (membershipKind === "roles") return roles;
    if (membershipKind === "groups") return groups;
    return departments;
  }, [membershipKind, roles, groups, departments]);

  async function createOrganization(event: FormEvent) {
    event.preventDefault();
    if (!organizationKinds.includes(organizationKind) || !code.trim() || !name.trim()) return;
    try {
      await createEnterpriseOrganization(organizationKind, {
        code: code.trim(),
        name: name.trim(),
      });
      setCode("");
      setName("");
      await reload();
      onSuccess("Đã tạo đơn vị IAM và ghi audit");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tạo đơn vị IAM");
    }
  }

  async function assignMembership(event: FormEvent) {
    event.preventDefault();
    if (!organizationKinds.includes(membershipKind) || !userId || !objectId) return;
    try {
      await assignEnterpriseMembership(
        userId,
        membershipKind,
        objectId,
        membershipKind === "departments",
      );
      if (membershipKind === "roles") setUserRoles(await listEnterpriseUserRoles(userId));
      if (membershipKind === "groups") setUserGroups(await listEnterpriseUserGroups(userId));
      if (membershipKind === "departments") {
        setUserDepartments(await listEnterpriseUserDepartments(userId, true));
      }
      onSuccess("Đã cập nhật membership; quyền hiệu lực sẽ được tính lại ở request kế tiếp");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật membership");
    }
  }

  async function removeMembership(
    kind: "roles" | "groups" | "departments",
    id: string,
  ) {
    if (!userId || !window.confirm("Thu hồi membership này?")) return;
    setSaving(true);
    try {
      await removeEnterpriseMembership(userId, kind, id);
      if (kind === "roles") setUserRoles(await listEnterpriseUserRoles(userId));
      if (kind === "groups") setUserGroups(await listEnterpriseUserGroups(userId));
      if (kind === "departments") {
        setUserDepartments(await listEnterpriseUserDepartments(userId, true));
      }
      onSuccess("Đã thu hồi membership và ghi audit");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể thu hồi membership");
    } finally {
      setSaving(false);
    }
  }

  async function toggleRolePermission(permission: FunctionalPermission) {
    if (!roleId) return;
    const assigned = rolePermissions.some((item) => item.id === permission.id);
    setSaving(true);
    try {
      if (assigned) await removeEnterpriseRolePermission(roleId, permission.id);
      else await assignEnterpriseRolePermission(roleId, permission.id);
      setRolePermissions(await listEnterpriseRolePermissions(roleId));
      onSuccess(assigned ? "Đã gỡ functional permission" : "Đã gán functional permission");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật role permission");
    } finally {
      setSaving(false);
    }
  }

  async function setUserStatus(status: EnterpriseUserProfile["status"]) {
    if (!userId) return;
    setSaving(true);
    try {
      await updateEnterpriseUser(userId, { status });
      const page = await listEnterpriseUsers();
      setUsers(page.items);
      onSuccess(`Đã chuyển trạng thái tài khoản sang ${status}`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật trạng thái user");
    } finally {
      setSaving(false);
    }
  }

  async function provisionEmployee(event: FormEvent) {
    event.preventDefault();
    if (!employeeEmail.trim() || temporaryPassword.length < 8 || saving) return;
    setSaving(true);
    try {
      const employee = await provisionEnterpriseEmployee({
        email: employeeEmail.trim().toLowerCase(),
        temporary_password: temporaryPassword,
        ...(employeeName.trim() ? { full_name: employeeName.trim() } : {}),
        ...(employeeCode.trim() ? { company_user_id: employeeCode.trim() } : {}),
      });
      setEmployeeEmail("");
      setEmployeeName("");
      setEmployeeCode("");
      setTemporaryPassword("");
      await reload();
      setUserId(employee.user_id);
      onSuccess(`Đã tạo tài khoản ${employee.email} với role EMPLOYEE`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tạo tài khoản nhân viên");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <PanelLoader label="Đang tải IAM…" />;

  const organizationColumns: Array<[string, OrganizationUnit[]]> = [];
  if (canManageRoles) organizationColumns.push(["Roles", roles]);
  if (canManageGroups) organizationColumns.push(["Groups", groups]);
  if (canManageDepartments) organizationColumns.push(["Departments", departments]);
  return (
    <div>
      <h1 className="font-heading text-2xl font-bold">Identity & Organization</h1>
      <p className="mt-1 text-sm text-dim">Quản lý user profile, role, group, department và membership có hiệu lực tức thời.</p>

      <div className={`mt-6 grid gap-5 ${canManageUsers && organizationKinds.length ? "xl:grid-cols-[1.25fr_1fr]" : ""}`}>
        {canManageUsers && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="font-heading font-semibold">Người dùng · {users.length}</div>
            <button onClick={() => void reload()} className="rounded-lg border border-border px-3 py-1.5 text-[11px]">Làm mới</button>
          </div>
          <form onSubmit={provisionEmployee} className="mb-5 rounded-xl border border-accent/25 bg-accent/5 p-4">
            <div className="mb-1 font-heading text-sm font-semibold">Tạo tài khoản nhân viên</div>
            <p className="mb-3 text-[10px] leading-4 text-faint">Tài khoản được xác nhận ngay và tự động nhận role EMPLOYEE. Hãy chuyển mật khẩu tạm qua kênh an toàn.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input type="email" required value={employeeEmail} onChange={(event) => setEmployeeEmail(event.target.value)} placeholder="Email nhân viên" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={employeeName} onChange={(event) => setEmployeeName(event.target.value)} placeholder="Họ và tên" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} placeholder="Mã nhân viên (không bắt buộc)" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input type="password" required minLength={8} autoComplete="new-password" value={temporaryPassword} onChange={(event) => setTemporaryPassword(event.target.value)} placeholder="Mật khẩu tạm · tối thiểu 8 ký tự" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
            </div>
            <button disabled={saving || !employeeEmail.trim() || temporaryPassword.length < 8} className="mt-3 w-full rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground disabled:opacity-50">{saving ? "Đang tạo…" : "Tạo tài khoản EMPLOYEE"}</button>
          </form>
          <div className="max-h-[420px] space-y-2 overflow-y-auto">
            {users.map((user) => (
              <button key={user.user_id} onClick={() => setUserId(user.user_id)} className={`w-full rounded-xl border p-3 text-left ${userId === user.user_id ? "border-accent bg-accent/10" : "border-border bg-background"}`}>
                <div className="flex items-center justify-between gap-3"><span className="truncate text-xs font-semibold">{user.full_name || user.company_user_id || user.user_id}</span><span className="text-[10px] text-faint">{user.status}</span></div>
                <div className="mt-1 truncate text-[10px] text-faint">{user.user_id}</div>
              </button>
            ))}
            {!users.length && <div className="py-12 text-center text-xs text-faint">Chưa có user profile.</div>}
          </div>
          {userId && <div className="mt-4 rounded-xl border border-border bg-background p-3">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-faint">Trạng thái tài khoản</div>
            <div className="flex flex-wrap gap-2">{(["ACTIVE", "LOCKED", "DISABLED"] as const).map((status) => <button key={status} type="button" disabled={saving} onClick={() => void setUserStatus(status)} className="rounded-md border border-border px-2 py-1 text-[10px] disabled:opacity-50">{status}</button>)}</div>
          </div>}
        </section>}

        {!!organizationKinds.length && <div className="space-y-5">
          <form onSubmit={createOrganization} className="rounded-2xl border border-border bg-panel p-5">
            <div className="mb-4 font-heading font-semibold">Tạo role / group / department</div>
            <div className="grid gap-3">
              <select value={organizationKind} onChange={(event) => setOrganizationKind(event.target.value as typeof organizationKind)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{organizationKinds.map((kind) => <option key={kind} value={kind}>{kind === "roles" ? "Role" : kind === "groups" ? "Group" : "Department"}</option>)}</select>
              <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="Mã định danh" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Tên hiển thị" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <button className="rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground">Tạo mới</button>
            </div>
          </form>

          <form onSubmit={assignMembership} className="rounded-2xl border border-border bg-panel p-5">
            <div className="mb-1 font-heading font-semibold">Gán membership</div>
            <div className="mb-4 truncate text-[10px] text-faint">User: {userId || (canManageUsers ? "chọn từ danh sách" : "nhập UUID bên dưới")}</div>
            <div className="grid gap-3">
              {!canManageUsers && <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="User UUID" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />}
              <select value={membershipKind} onChange={(event) => { setMembershipKind(event.target.value as typeof membershipKind); setObjectId(""); }} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{organizationKinds.map((kind) => <option key={kind} value={kind}>{kind === "roles" ? "Role" : kind === "groups" ? "Group" : "Department"}</option>)}</select>
              <select value={objectId} onChange={(event) => setObjectId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs"><option value="">Chọn đối tượng</option>{membershipOptions.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</select>
              <button disabled={!userId || !objectId} className="rounded-lg bg-foreground px-3 py-2 text-xs font-semibold text-background disabled:opacity-50">Gán cho user</button>
            </div>
          </form>
        </div>}
      </div>

      {userId && (canManageRoles || canManageGroups || canManageDepartments) && <section className="mt-5 rounded-2xl border border-border bg-panel p-5">
        <div className="mb-4 flex items-center justify-between"><div className="font-heading font-semibold">Membership hiện tại</div>{detailLoading && <Icon icon="lucide:loader-circle" className="animate-spin" />}</div>
        <div className="grid gap-4 lg:grid-cols-3">
          {canManageRoles && <MembershipList title="Roles" items={userRoles.map((item) => ({ id: item.role_id, label: `${item.role.code} · ${item.role.name}`, inactive: item.role.status !== "ACTIVE" }))} disabled={saving} onRemove={(id) => void removeMembership("roles", id)} />}
          {canManageGroups && <MembershipList title="Groups" items={userGroups.map((item) => ({ id: item.group_id, label: `${item.group.code} · ${item.group.name}`, inactive: item.group.status !== "ACTIVE" }))} disabled={saving} onRemove={(id) => void removeMembership("groups", id)} />}
          {canManageDepartments && <MembershipList title="Departments" items={userDepartments.map((item) => ({ id: item.department_id, label: `${item.department.code} · ${item.department.name}${item.is_primary ? " · primary" : ""}`, inactive: Boolean(item.end_at) }))} disabled={saving} onRemove={(id) => void removeMembership("departments", id)} />}
        </div>
      </section>}

      {canManageRoles && <section className="mt-5 rounded-2xl border border-border bg-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-heading font-semibold">Functional permissions theo role</div><div className="mt-1 text-[10px] text-faint">Mọi thay đổi có hiệu lực ở request kế tiếp và được audit.</div></div><select value={roleId} onChange={(event) => setRoleId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{roles.map((role) => <option key={role.id} value={role.id}>{role.code} · {role.name}</option>)}</select></div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{functionalPermissions.map((permission) => { const assigned = rolePermissions.some((item) => item.id === permission.id); return <button key={permission.id} type="button" disabled={!roleId || saving} onClick={() => void toggleRolePermission(permission)} className={`rounded-xl border p-3 text-left disabled:opacity-50 ${assigned ? "border-green/40 bg-green/10" : "border-border bg-background"}`}><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">{permission.code}</span><Icon icon={assigned ? "lucide:check" : "lucide:plus"} /></div><div className="mt-1 text-[10px] text-faint">{permission.name}</div></button>; })}</div>
      </section>}

      {!!organizationColumns.length && <div className="mt-5 grid gap-4 lg:grid-cols-3">
        {organizationColumns.map(([label, items]) => (
          <section key={label} className="rounded-2xl border border-border bg-panel p-4">
            <div className="mb-3 font-heading text-sm font-semibold">{label} · {items.length}</div>
            <div className="max-h-64 space-y-2 overflow-y-auto">{items.map((item) => <div key={item.id} className="rounded-lg border border-border bg-background px-3 py-2"><div className="text-xs font-semibold">{item.code}</div><div className="mt-0.5 text-[10px] text-faint">{item.name} · {item.status}</div></div>)}</div>
          </section>
        ))}
      </div>}
    </div>
  );
}

function MembershipList({ title, items, disabled, onRemove }: {
  title: string;
  items: Array<{ id: string; label: string; inactive: boolean }>;
  disabled: boolean;
  onRemove: (id: string) => void;
}) {
  return <div className="rounded-xl border border-border bg-background p-3"><div className="mb-2 text-xs font-semibold">{title} · {items.length}</div><div className="space-y-2">{items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-2 py-2"><span className={`truncate text-[10px] ${item.inactive ? "text-faint line-through" : "text-dim"}`}>{item.label}</span><button type="button" disabled={disabled || item.inactive} onClick={() => onRemove(item.id)} className="text-[10px] text-red disabled:opacity-30">Thu hồi</button></div>)}{!items.length && <div className="py-4 text-center text-[10px] text-faint">Không có membership.</div>}</div></div>;
}

export function GovernanceAdminPanel({ permissions, onError, onSuccess }: AdminPanelProps) {
  const [summary, setSummary] = useState<EnterpriseAnalyticsSummary | null>(null);
  const [logs, setLogs] = useState<EnterpriseAuditLog[]>([]);
  const [reports, setReports] = useState<EnterpriseAnswerReport[]>([]);
  const [loading, setLoading] = useState(true);
  const canViewAnalytics = permissions.has("VIEW_ANALYTICS");
  const canViewAudit = permissions.has("VIEW_AUDIT");
  const canManageReports = permissions.has("MANAGE_REPORT");

  async function reload() {
    setLoading(true);
    try {
      const [nextSummary, logPage, reportPage] = await Promise.all([
        canViewAnalytics ? getEnterpriseAnalytics() : Promise.resolve(null),
        canViewAudit ? listEnterpriseAuditLogs() : Promise.resolve(null),
        canViewAudit ? listEnterpriseAnswerReports() : Promise.resolve(null),
      ]);
      setSummary(nextSummary);
      setLogs(logPage?.items ?? []);
      setReports(reportPage?.items ?? []);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tải dữ liệu governance");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [canManageReports, canViewAnalytics, canViewAudit]);

  async function resolve(report: EnterpriseAnswerReport, status: "RESOLVED" | "DISMISSED") {
    if (!canManageReports) return;
    const note = window.prompt("Ghi chú xử lý report:");
    if (!note?.trim()) return;
    try {
      await resolveEnterpriseAnswerReport(report.id, status, note.trim());
      await reload();
      onSuccess(`Đã chuyển report sang ${status}`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể xử lý report");
    }
  }

  if (loading) return <PanelLoader label="Đang tải audit và analytics…" />;

  const metrics: Array<[string, string | number, string]> = summary ? [
    ["Published", summary.published_documents, "text-green"],
    ["Draft", summary.draft_documents, "text-yellow"],
    ["Job lỗi", summary.failed_jobs, "text-red"],
    ["Report mở", summary.open_reports, "text-red"],
    ["Feedback tốt", summary.feedback_up, "text-green"],
    ["No-answer", summary.no_answer_rate === null ? "—" : `${(summary.no_answer_rate * 100).toFixed(1)}%`, "text-blue"],
  ] : [];
  return (
    <div>
      <div className="flex items-end justify-between gap-4"><div><h1 className="font-heading text-2xl font-bold">Audit & Governance</h1><p className="mt-1 text-sm text-dim">Theo dõi lifecycle, chất lượng câu trả lời và audit append-only theo request/trace ID.</p></div><button onClick={() => void reload()} className="rounded-lg border border-border px-3 py-2 text-xs">Làm mới</button></div>
      {!!metrics.length && <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">{metrics.map(([label, value, color]) => <div key={label} className="rounded-2xl border border-border bg-panel p-4"><div className={`font-heading text-2xl font-bold ${color}`}>{value}</div><div className="mt-1 text-[10px] uppercase tracking-wide text-faint">{label}</div></div>)}</div>}

      <div className={`mt-5 grid gap-5 ${canViewAudit ? "xl:grid-cols-[1fr_1.2fr]" : ""}`}>
        {canViewAudit && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 font-heading font-semibold">Answer reports · {reports.length}</div>
          <div className="max-h-[520px] space-y-3 overflow-y-auto">
            {reports.map((report) => <div key={report.id} className="rounded-xl border border-border bg-background p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold">{report.reason_code}</div><div className="mt-1 text-[10px] text-faint">{readableDate(report.created_at)} · {report.reporter_user_id}</div></div><span className="rounded-full border border-border px-2 py-1 text-[10px]">{report.status}</span></div>{report.details && <p className="mt-3 text-xs leading-5 text-dim">{report.details}</p>}{canManageReports && (report.status === "OPEN" || report.status === "INVESTIGATING") ? <div className="mt-3 flex gap-2"><button onClick={() => void resolve(report, "RESOLVED")} className="rounded-md bg-green/10 px-2.5 py-1.5 text-[10px] text-green">Resolve</button><button onClick={() => void resolve(report, "DISMISSED")} className="rounded-md bg-inset px-2.5 py-1.5 text-[10px] text-faint">Dismiss</button></div> : null}</div>)}
            {!reports.length && <div className="py-16 text-center text-xs text-faint">Không có report cần xử lý.</div>}
          </div>
        </section>}

        {canViewAudit && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 font-heading font-semibold">Audit stream · {logs.length}</div>
          <div className="max-h-[520px] space-y-2 overflow-y-auto">{logs.map((log) => <div key={log.id} className="rounded-xl border border-border bg-background p-3"><div className="flex items-center justify-between gap-3"><span className="text-xs font-semibold">{log.action}</span><span className="text-[10px] text-faint">{readableDate(log.created_at)}</span></div><div className="mt-1 truncate text-[10px] text-faint">{log.entity_type} · {log.entity_id || "—"}</div><div className="mt-1 truncate text-[10px] text-faint">request {log.request_id || "—"} · trace {log.trace_id || "—"}</div></div>)}</div>
        </section>}
      </div>
    </div>
  );
}
