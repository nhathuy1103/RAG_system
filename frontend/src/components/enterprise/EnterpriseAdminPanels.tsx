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

const USER_STATUS_LABEL: Record<string, string> = {
  ACTIVE: "Đang hoạt động",
  LOCKED: "Đã khóa",
  DISABLED: "Đã vô hiệu hóa",
};

const ORGANIZATION_KIND_LABEL = {
  roles: "Vai trò",
  groups: "Nhóm",
  departments: "Phòng ban",
} as const;

const REPORT_STATUS_LABEL: Record<string, string> = {
  OPEN: "Chờ xử lý",
  INVESTIGATING: "Đang xác minh",
  RESOLVED: "Đã giải quyết",
  DISMISSED: "Đã bỏ qua",
};

const FUNCTIONAL_PERMISSION_LABEL: Record<string, string> = {
  ASK_KNOWLEDGE: "Tra cứu kho tri thức",
  UPLOAD_DOCUMENT: "Tải tài liệu lên",
  MANAGE_DOCUMENT: "Quản lý tài liệu",
  REVIEW_DOCUMENT: "Kiểm duyệt tài liệu",
  PUBLISH_DOCUMENT: "Xuất bản tài liệu",
  ARCHIVE_DOCUMENT: "Lưu trữ tài liệu",
  MANAGE_ACCESS_POLICY: "Quản lý chính sách truy cập",
  MANAGE_USER: "Quản lý người dùng",
  MANAGE_ROLE: "Quản lý vai trò",
  MANAGE_GROUP: "Quản lý nhóm",
  MANAGE_DEPARTMENT: "Quản lý phòng ban",
  VIEW_AUDIT: "Xem nhật ký kiểm toán",
  VIEW_ANALYTICS: "Xem số liệu tổng hợp",
  MANAGE_REPORT: "Xử lý báo cáo câu trả lời",
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  ENTERPRISE_ANSWER_COMPLETED: "Hoàn tất câu trả lời doanh nghiệp",
  DOCUMENT_CREATED: "Tạo tài liệu",
  DOCUMENT_UPDATED: "Cập nhật tài liệu",
  DOCUMENT_ARCHIVED: "Lưu trữ tài liệu",
  DOCUMENT_VERSION_CREATED: "Tạo phiên bản tài liệu",
  DOCUMENT_VERSION_REVIEWED: "Kiểm duyệt phiên bản",
  DOCUMENT_VERSION_PUBLISHED: "Xuất bản phiên bản",
  DOCUMENT_PERMISSION_GRANTED: "Cấp quyền tài liệu",
  DOCUMENT_PERMISSION_REVOKED: "Thu hồi quyền tài liệu",
  PROCESSING_JOB_RETRIED: "Chạy lại xử lý tài liệu",
  PROCESSING_JOB_REPROCESSED_FROM_REVIEW: "Xử lý lại theo yêu cầu kiểm duyệt",
  USER_PROFILE_CREATED: "Tạo hồ sơ người dùng",
  USER_PROFILE_UPDATED: "Cập nhật hồ sơ người dùng",
  DOCUMENT_METADATA_ASSERTION_VERIFIED: "Xác nhận metadata đề xuất",
  DOCUMENT_METADATA_ASSERTION_REJECTED: "Từ chối metadata đề xuất",
};

const DEFAULT_ORGANIZATION_NAME: Record<string, string> = {
  ADMIN: "Quản trị viên",
  DOCUMENT_REVIEWER: "Người kiểm duyệt tài liệu",
  EMPLOYEE: "Nhân viên",
};

const AUDIT_ENTITY_LABEL: Record<string, string> = {
  enterprise_message: "Tin nhắn hỏi đáp",
  source_files: "Tệp nguồn",
  user_roles: "Vai trò của người dùng",
  role_permissions: "Quyền của vai trò",
  knowledge_document: "Tài liệu tri thức",
  document_version: "Phiên bản tài liệu",
  document_permission: "Quyền tài liệu",
  processing_job: "Yêu cầu xử lý",
  document_metadata_assertion: "Metadata đề xuất",
};

const AUDIT_TABLE_LABEL: Record<string, string> = {
  SOURCE_FILES: "tệp nguồn",
  USER_ROLES: "vai trò của người dùng",
  ROLE_PERMISSIONS: "quyền của vai trò",
  USER_GROUPS: "nhóm của người dùng",
  USER_DEPARTMENTS: "phòng ban của người dùng",
  DOCUMENT_PERMISSIONS: "quyền tài liệu",
};

function auditActionLabel(value: string) {
  if (AUDIT_ACTION_LABEL[value]) return AUDIT_ACTION_LABEL[value];
  const tableAction = /^TABLE_(.+)_(INSERT|UPDATE|DELETE)$/.exec(value);
  if (!tableAction) return value;
  const operation = { INSERT: "Thêm", UPDATE: "Cập nhật", DELETE: "Xóa" }[tableAction[2]];
  return `${operation} ${AUDIT_TABLE_LABEL[tableAction[1]] || tableAction[1].toLocaleLowerCase("vi-VN")}`;
}

function organizationName(item: OrganizationUnit) {
  return DEFAULT_ORGANIZATION_NAME[item.code] || item.name;
}

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
      onError(cause instanceof Error ? cause.message : "Không thể tải dữ liệu người dùng và tổ chức");
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
        if (!cancelled) onError(cause instanceof Error ? cause.message : "Không thể tải thông tin thành viên");
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
        if (!cancelled) onError(cause instanceof Error ? cause.message : "Không thể tải quyền của vai trò");
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
      onSuccess("Đã tạo đơn vị tổ chức và ghi nhật ký kiểm toán");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tạo đơn vị tổ chức");
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
      onSuccess("Đã cập nhật tư cách thành viên; quyền sẽ được tính lại ở yêu cầu tiếp theo");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật tư cách thành viên");
    }
  }

  async function removeMembership(
    kind: "roles" | "groups" | "departments",
    id: string,
  ) {
    if (!userId || !window.confirm("Thu hồi tư cách thành viên này?")) return;
    setSaving(true);
    try {
      await removeEnterpriseMembership(userId, kind, id);
      if (kind === "roles") setUserRoles(await listEnterpriseUserRoles(userId));
      if (kind === "groups") setUserGroups(await listEnterpriseUserGroups(userId));
      if (kind === "departments") {
        setUserDepartments(await listEnterpriseUserDepartments(userId, true));
      }
      onSuccess("Đã thu hồi tư cách thành viên và ghi nhật ký kiểm toán");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể thu hồi tư cách thành viên");
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
      onSuccess(assigned ? "Đã gỡ quyền chức năng" : "Đã gán quyền chức năng");
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật quyền của vai trò");
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
      onError(cause instanceof Error ? cause.message : "Không thể cập nhật trạng thái người dùng");
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
      onSuccess(`Đã tạo tài khoản ${employee.email} với vai trò Nhân viên`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể tạo tài khoản nhân viên");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <PanelLoader label="Đang tải người dùng và tổ chức…" />;

  const organizationColumns: Array<[string, OrganizationUnit[]]> = [];
  if (canManageRoles) organizationColumns.push(["Vai trò", roles]);
  if (canManageGroups) organizationColumns.push(["Nhóm", groups]);
  if (canManageDepartments) organizationColumns.push(["Phòng ban", departments]);
  return (
    <div>
      <h1 className="font-heading text-2xl font-bold">Người dùng và cơ cấu tổ chức</h1>
      <p className="mt-1 text-sm text-dim">Quản lý hồ sơ người dùng, vai trò, nhóm, phòng ban và tư cách thành viên.</p>

      <div className={`mt-6 grid gap-5 ${canManageUsers && organizationKinds.length ? "xl:grid-cols-[1.25fr_1fr]" : ""}`}>
        {canManageUsers && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="font-heading font-semibold">Người dùng · {users.length}</div>
            <button onClick={() => void reload()} className="rounded-lg border border-border px-3 py-1.5 text-[11px]">Làm mới</button>
          </div>
          <form onSubmit={provisionEmployee} className="mb-5 rounded-xl border border-accent/25 bg-accent/5 p-4">
            <div className="mb-1 font-heading text-sm font-semibold">Tạo tài khoản nhân viên</div>
            <p className="mb-3 text-[10px] leading-4 text-faint">Tài khoản được xác nhận ngay và tự động nhận vai trò Nhân viên. Hãy chuyển mật khẩu tạm qua kênh an toàn.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input type="email" required value={employeeEmail} onChange={(event) => setEmployeeEmail(event.target.value)} placeholder="Email nhân viên" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={employeeName} onChange={(event) => setEmployeeName(event.target.value)} placeholder="Họ và tên" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} placeholder="Mã nhân viên (không bắt buộc)" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input type="password" required minLength={8} autoComplete="new-password" value={temporaryPassword} onChange={(event) => setTemporaryPassword(event.target.value)} placeholder="Mật khẩu tạm · tối thiểu 8 ký tự" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
            </div>
            <button disabled={saving || !employeeEmail.trim() || temporaryPassword.length < 8} className="mt-3 w-full rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground disabled:opacity-50">{saving ? "Đang tạo…" : "Tạo tài khoản nhân viên"}</button>
          </form>
          <div className="max-h-[420px] space-y-2 overflow-y-auto">
            {users.map((user) => (
              <button key={user.user_id} onClick={() => setUserId(user.user_id)} className={`w-full rounded-xl border p-3 text-left ${userId === user.user_id ? "border-accent bg-accent/10" : "border-border bg-background"}`}>
                <div className="flex items-center justify-between gap-3"><span className="truncate text-xs font-semibold">{user.full_name || user.company_user_id || user.user_id}</span><span title={user.status} className="text-[10px] text-faint">{USER_STATUS_LABEL[user.status]}</span></div>
                <div className="mt-1 truncate text-[10px] text-faint">{user.user_id}</div>
              </button>
            ))}
            {!users.length && <div className="py-12 text-center text-xs text-faint">Chưa có hồ sơ người dùng.</div>}
          </div>
          {userId && <div className="mt-4 rounded-xl border border-border bg-background p-3">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-faint">Trạng thái tài khoản</div>
            <div className="flex flex-wrap gap-2">{(["ACTIVE", "LOCKED", "DISABLED"] as const).map((status) => <button key={status} type="button" disabled={saving} onClick={() => void setUserStatus(status)} className="rounded-md border border-border px-2 py-1 text-[10px] disabled:opacity-50">{USER_STATUS_LABEL[status]}</button>)}</div>
          </div>}
        </section>}

        {!!organizationKinds.length && <div className="space-y-5">
          <form onSubmit={createOrganization} className="rounded-2xl border border-border bg-panel p-5">
            <div className="mb-4 font-heading font-semibold">Tạo vai trò, nhóm hoặc phòng ban</div>
            <div className="grid gap-3">
              <select value={organizationKind} onChange={(event) => setOrganizationKind(event.target.value as typeof organizationKind)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{organizationKinds.map((kind) => <option key={kind} value={kind}>{ORGANIZATION_KIND_LABEL[kind]}</option>)}</select>
              <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="Mã định danh" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Tên hiển thị" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />
              <button className="rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-accent-foreground">Tạo mới</button>
            </div>
          </form>

          <form onSubmit={assignMembership} className="rounded-2xl border border-border bg-panel p-5">
            <div className="mb-1 font-heading font-semibold">Gán người dùng vào tổ chức</div>
            <div className="mb-4 truncate text-[10px] text-faint">Người dùng: {userId || (canManageUsers ? "chọn từ danh sách" : "nhập UUID bên dưới")}</div>
            <div className="grid gap-3">
              {!canManageUsers && <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="UUID người dùng" className="rounded-lg border border-border bg-background px-3 py-2 text-xs" />}
              <select value={membershipKind} onChange={(event) => { setMembershipKind(event.target.value as typeof membershipKind); setObjectId(""); }} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{organizationKinds.map((kind) => <option key={kind} value={kind}>{ORGANIZATION_KIND_LABEL[kind]}</option>)}</select>
              <select value={objectId} onChange={(event) => setObjectId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs"><option value="">Chọn đối tượng</option>{membershipOptions.map((item) => <option key={item.id} value={item.id}>{item.code} · {organizationName(item)}</option>)}</select>
              <button disabled={!userId || !objectId} className="rounded-lg bg-foreground px-3 py-2 text-xs font-semibold text-background disabled:opacity-50">Gán cho người dùng</button>
            </div>
          </form>
        </div>}
      </div>

      {userId && (canManageRoles || canManageGroups || canManageDepartments) && <section className="mt-5 rounded-2xl border border-border bg-panel p-5">
        <div className="mb-4 flex items-center justify-between"><div className="font-heading font-semibold">Tư cách thành viên hiện tại</div>{detailLoading && <Icon icon="lucide:loader-circle" className="animate-spin" />}</div>
        <div className="grid gap-4 lg:grid-cols-3">
          {canManageRoles && <MembershipList title="Vai trò" items={userRoles.map((item) => ({ id: item.role_id, label: `${item.role.code} · ${organizationName(item.role)}`, inactive: item.role.status !== "ACTIVE" }))} disabled={saving} onRemove={(id) => void removeMembership("roles", id)} />}
          {canManageGroups && <MembershipList title="Nhóm" items={userGroups.map((item) => ({ id: item.group_id, label: `${item.group.code} · ${organizationName(item.group)}`, inactive: item.group.status !== "ACTIVE" }))} disabled={saving} onRemove={(id) => void removeMembership("groups", id)} />}
          {canManageDepartments && <MembershipList title="Phòng ban" items={userDepartments.map((item) => ({ id: item.department_id, label: `${item.department.code} · ${organizationName(item.department)}${item.is_primary ? " · chính" : ""}`, inactive: Boolean(item.end_at) }))} disabled={saving} onRemove={(id) => void removeMembership("departments", id)} />}
        </div>
      </section>}

      {canManageRoles && <section className="mt-5 rounded-2xl border border-border bg-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-heading font-semibold">Quyền chức năng theo vai trò</div><div className="mt-1 text-[10px] text-faint">Mọi thay đổi có hiệu lực ở yêu cầu tiếp theo và được ghi vào nhật ký kiểm toán.</div></div><select value={roleId} onChange={(event) => setRoleId(event.target.value)} className="rounded-lg border border-border bg-background px-3 py-2 text-xs">{roles.map((role) => <option key={role.id} value={role.id}>{role.code} · {organizationName(role)}</option>)}</select></div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{functionalPermissions.map((permission) => { const assigned = rolePermissions.some((item) => item.id === permission.id); return <button key={permission.id} type="button" disabled={!roleId || saving} onClick={() => void toggleRolePermission(permission)} className={`rounded-xl border p-3 text-left disabled:opacity-50 ${assigned ? "border-green/40 bg-green/10" : "border-border bg-background"}`}><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">{FUNCTIONAL_PERMISSION_LABEL[permission.code] || permission.name}</span><Icon icon={assigned ? "lucide:check" : "lucide:plus"} /></div><div className="mt-1 text-[10px] text-faint">Mã quyền: {permission.code}</div></button>; })}</div>
      </section>}

      {!!organizationColumns.length && <div className="mt-5 grid gap-4 lg:grid-cols-3">
        {organizationColumns.map(([label, items]) => (
          <section key={label} className="rounded-2xl border border-border bg-panel p-4">
            <div className="mb-3 font-heading text-sm font-semibold">{label} · {items.length}</div>
            <div className="max-h-64 space-y-2 overflow-y-auto">{items.map((item) => <div key={item.id} className="rounded-lg border border-border bg-background px-3 py-2"><div className="text-xs font-semibold">{item.code}</div><div className="mt-0.5 text-[10px] text-faint">{organizationName(item)} · {USER_STATUS_LABEL[item.status] || item.status}</div></div>)}</div>
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
  return <div className="rounded-xl border border-border bg-background p-3"><div className="mb-2 text-xs font-semibold">{title} · {items.length}</div><div className="space-y-2">{items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg border border-border px-2 py-2"><span className={`truncate text-[10px] ${item.inactive ? "text-faint line-through" : "text-dim"}`}>{item.label}</span><button type="button" disabled={disabled || item.inactive} onClick={() => onRemove(item.id)} className="text-[10px] text-red disabled:opacity-30">Thu hồi</button></div>)}{!items.length && <div className="py-4 text-center text-[10px] text-faint">Không có tư cách thành viên.</div>}</div></div>;
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
      onError(cause instanceof Error ? cause.message : "Không thể tải dữ liệu kiểm toán và giám sát");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [canManageReports, canViewAnalytics, canViewAudit]);

  async function resolve(report: EnterpriseAnswerReport, status: "RESOLVED" | "DISMISSED") {
    if (!canManageReports) return;
    const note = window.prompt("Ghi chú xử lý báo cáo:");
    if (!note?.trim()) return;
    try {
      await resolveEnterpriseAnswerReport(report.id, status, note.trim());
      await reload();
      onSuccess(`Đã chuyển báo cáo sang trạng thái: ${REPORT_STATUS_LABEL[status]}`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Không thể xử lý báo cáo");
    }
  }

  if (loading) return <PanelLoader label="Đang tải nhật ký và số liệu tổng hợp…" />;

  const metrics: Array<[string, string | number, string]> = summary ? [
    ["Đã xuất bản", summary.published_documents, "text-green"],
    ["Bản nháp", summary.draft_documents, "text-yellow"],
    ["Lần xử lý lỗi", summary.failed_jobs, "text-red"],
    ["Báo cáo chờ xử lý", summary.open_reports, "text-red"],
    ["Phản hồi tích cực", summary.feedback_up, "text-green"],
    ["Không có câu trả lời", summary.no_answer_rate === null ? "—" : `${(summary.no_answer_rate * 100).toFixed(1)}%`, "text-blue"],
  ] : [];
  return (
    <div>
      <div className="flex items-end justify-between gap-4"><div><h1 className="font-heading text-2xl font-bold">Kiểm toán và giám sát</h1><p className="mt-1 text-sm text-dim">Theo dõi vòng đời tài liệu, chất lượng câu trả lời và nhật ký không thể sửa theo mã yêu cầu/truy vết.</p></div><button onClick={() => void reload()} className="rounded-lg border border-border px-3 py-2 text-xs">Làm mới</button></div>
      {!!metrics.length && <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">{metrics.map(([label, value, color]) => <div key={label} className="rounded-2xl border border-border bg-panel p-4"><div className={`font-heading text-2xl font-bold ${color}`}>{value}</div><div className="mt-1 text-[10px] uppercase tracking-wide text-faint">{label}</div></div>)}</div>}

      <div className={`mt-5 grid gap-5 ${canViewAudit ? "xl:grid-cols-[1fr_1.2fr]" : ""}`}>
        {canViewAudit && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 font-heading font-semibold">Báo cáo câu trả lời · {reports.length}</div>
          <div className="max-h-[520px] space-y-3 overflow-y-auto">
            {reports.map((report) => <div key={report.id} className="rounded-xl border border-border bg-background p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold">{report.reason_code}</div><div className="mt-1 text-[10px] text-faint">{readableDate(report.created_at)} · {report.reporter_user_id}</div></div><span title={report.status} className="rounded-full border border-border px-2 py-1 text-[10px]">{REPORT_STATUS_LABEL[report.status]}</span></div>{report.details && <p className="mt-3 text-xs leading-5 text-dim">{report.details}</p>}{canManageReports && (report.status === "OPEN" || report.status === "INVESTIGATING") ? <div className="mt-3 flex gap-2"><button onClick={() => void resolve(report, "RESOLVED")} className="rounded-md bg-green/10 px-2.5 py-1.5 text-[10px] text-green">Đánh dấu đã giải quyết</button><button onClick={() => void resolve(report, "DISMISSED")} className="rounded-md bg-inset px-2.5 py-1.5 text-[10px] text-faint">Bỏ qua</button></div> : null}</div>)}
            {!reports.length && <div className="py-16 text-center text-xs text-faint">Không có báo cáo nào cần xử lý.</div>}
          </div>
        </section>}

        {canViewAudit && <section className="rounded-2xl border border-border bg-panel p-5">
          <div className="mb-4 font-heading font-semibold">Nhật ký kiểm toán · {logs.length}</div>
          <div className="max-h-[520px] space-y-2 overflow-y-auto">{logs.map((log) => <div key={log.id} className="rounded-xl border border-border bg-background p-3"><div className="flex items-center justify-between gap-3"><span title={log.action} className="text-xs font-semibold">{auditActionLabel(log.action)}</span><span className="text-[10px] text-faint">{readableDate(log.created_at)}</span></div><div className="mt-1 truncate text-[10px] text-faint">Đối tượng: {AUDIT_ENTITY_LABEL[log.entity_type] || log.entity_type} · {log.entity_id || "—"}</div><div className="mt-1 truncate text-[10px] text-faint">Mã yêu cầu {log.request_id || "—"} · mã truy vết {log.trace_id || "—"}</div></div>)}</div>
        </section>}
      </div>
    </div>
  );
}
