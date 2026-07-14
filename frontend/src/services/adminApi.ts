import { apiRequest } from './hrApi'

export type UserRole = 'it' | 'admin' | 'hr' | 'manager'
export type AdminUser = {
  id: number
  username: string
  email: string
  display_name: string
  role: UserRole
  department_id: number | null
  is_active: boolean
}
export type Department = {
  id: number
  name: string
  parent_id: number | null
  is_active: boolean
}
export type CatalogItem = {
  id: number
  name: string
  category: string | null
  is_active: boolean
}
export type SystemSetting = {
  key: string
  value: unknown
  description: string | null
  is_secret: boolean
}
export type AuditLog = {
  id: number
  actor_user_id: number | null
  action: string
  resource_type: string
  resource_id: string | null
  department_id: number | null
  details: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}
export type IssueSeverity = 'low' | 'medium' | 'high' | 'critical'
export type IssueStatus = 'open' | 'investigating' | 'resolved' | 'closed'
export type SystemIssue = {
  id: number; title: string; description: string; page: string
  severity: IssueSeverity; status: IssueStatus
  reproduction_steps: string | null; resolution_notes: string | null
  created_by_user_id: number | null; updated_by_user_id: number | null
  created_at: string; updated_at: string
}
export type SystemIssueWrite = Omit<SystemIssue, 'id' | 'created_by_user_id' | 'updated_by_user_id' | 'created_at' | 'updated_at'>
export type DatabaseColumn = { name: string; type: string; nullable: boolean; primary_key: boolean }
export type DatabaseTable = { name: string; row_count: number | null; columns: DatabaseColumn[] }
export type DatabaseOverview = {
  healthy: boolean; dialect: string; server_version: string | null
  transport_security: string; tables: DatabaseTable[]
}

export type UserWrite = {
  username?: string
  email: string
  password?: string
  display_name: string
  role: UserRole
  department_id: number | null
  is_active?: boolean
}

export const adminApi = {
  users: () => apiRequest<AdminUser[]>('/admin/users'),
  createUser: (payload: UserWrite) => apiRequest<AdminUser>('/admin/users', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateUser: (id: number, payload: UserWrite) => apiRequest<AdminUser>(`/admin/users/${id}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  departments: () => apiRequest<Department[]>('/admin/departments'),
  createDepartment: (payload: { name: string; parent_id: number | null }) => apiRequest<Department>('/admin/departments', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateDepartment: (id: number, payload: Partial<Department>) => apiRequest<Department>(`/admin/departments/${id}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  skills: () => apiRequest<CatalogItem[]>('/admin/skills'),
  tags: () => apiRequest<CatalogItem[]>('/admin/tags'),
  settings: () => apiRequest<SystemSetting[]>('/admin/settings'),
  audits: () => apiRequest<AuditLog[]>('/admin/audit-logs?limit=100'),
  systemIssues: () => apiRequest<SystemIssue[]>('/admin/system-issues'),
  createSystemIssue: (payload: SystemIssueWrite) => apiRequest<SystemIssue>('/admin/system-issues', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateSystemIssue: (id: number, payload: Partial<SystemIssueWrite>) => apiRequest<SystemIssue>(`/admin/system-issues/${id}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  databaseOverview: () => apiRequest<DatabaseOverview>('/admin/database/overview'),
}
