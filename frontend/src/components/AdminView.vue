<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  adminApi,
  type AdminUser,
  type AuditLog,
  type CatalogItem,
  type Department,
  type SystemSetting,
  type UserRole,
} from '../services/adminApi'
import type { CurrentUser } from '../services/auth'

const props = defineProps<{ currentUser: CurrentUser }>()
const tab = ref<'users' | 'departments' | 'catalogs' | 'settings' | 'audits'>('users')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const users = ref<AdminUser[]>([])
const departments = ref<Department[]>([])
const skills = ref<CatalogItem[]>([])
const tags = ref<CatalogItem[]>([])
const settings = ref<SystemSetting[]>([])
const audits = ref<AuditLog[]>([])
const userDialog = ref(false)
const departmentDialog = ref(false)
const editingUser = ref<AdminUser | null>(null)
const editingDepartment = ref<Department | null>(null)
const userForm = reactive({ username: '', email: '', password: '', display_name: '', role: 'hr' as UserRole, department_id: null as number | null, is_active: true })
const departmentForm = reactive({ name: '', parent_id: null as number | null, is_active: true })

const roleLabels: Record<UserRole, string> = { admin: '系統管理員', hr: 'HR', manager: '用人主管' }

function showNotice(message: string) {
  notice.value = message
  window.setTimeout(() => { if (notice.value === message) notice.value = '' }, 2500)
}

async function load() {
  if (props.currentUser.role !== 'admin') return
  loading.value = true
  error.value = ''
  try {
    const result = await Promise.all([
      adminApi.users(), adminApi.departments(), adminApi.skills(), adminApi.tags(), adminApi.settings(), adminApi.audits(),
    ])
    ;[users.value, departments.value, skills.value, tags.value, settings.value, audits.value] = result.map(item => item.data) as [
      AdminUser[], Department[], CatalogItem[], CatalogItem[], SystemSetting[], AuditLog[],
    ]
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '管理資料載入失敗'
  } finally {
    loading.value = false
  }
}

function openUser(user?: AdminUser) {
  editingUser.value = user || null
  Object.assign(userForm, user ? {
    username: user.username, email: user.email, password: '', display_name: user.display_name,
    role: user.role, department_id: user.department_id, is_active: user.is_active,
  } : { username: '', email: '', password: '', display_name: '', role: 'hr', department_id: null, is_active: true })
  userDialog.value = true
}

async function saveUser() {
  if (!userForm.email.trim() || !userForm.display_name.trim()) return
  if (!editingUser.value && (!userForm.username.trim() || userForm.password.length < 12)) {
    error.value = '新帳號必須填寫帳號及至少 12 字元密碼'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const common = {
      email: userForm.email.trim(), display_name: userForm.display_name.trim(), role: userForm.role,
      department_id: userForm.department_id, is_active: userForm.is_active,
      ...(userForm.password ? { password: userForm.password } : {}),
    }
    if (editingUser.value) await adminApi.updateUser(editingUser.value.id, common)
    else await adminApi.createUser({ ...common, username: userForm.username.trim(), password: userForm.password })
    userDialog.value = false
    await load()
    showNotice(editingUser.value ? '帳號已更新' : '帳號已建立')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '帳號儲存失敗'
  } finally {
    saving.value = false
  }
}

function openDepartment(item?: Department) {
  editingDepartment.value = item || null
  Object.assign(departmentForm, item ? {
    name: item.name, parent_id: item.parent_id, is_active: item.is_active,
  } : { name: '', parent_id: null, is_active: true })
  departmentDialog.value = true
}

async function saveDepartment() {
  if (!departmentForm.name.trim()) return
  saving.value = true
  error.value = ''
  try {
    if (editingDepartment.value) {
      await adminApi.updateDepartment(editingDepartment.value.id, { ...departmentForm, name: departmentForm.name.trim() })
    } else {
      await adminApi.createDepartment({ name: departmentForm.name.trim(), parent_id: departmentForm.parent_id })
    }
    departmentDialog.value = false
    await load()
    showNotice(editingDepartment.value ? '部門已更新' : '部門已建立')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '部門儲存失敗'
  } finally {
    saving.value = false
  }
}

function departmentName(id: number | null) {
  return departments.value.find(item => item.id === id)?.name || (id ? `部門 #${id}` : '不限部門')
}

function date(value: string) {
  return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <section v-if="currentUser.role !== 'admin'" class="admin-denied panel">
    <span>🔒</span><p class="eyebrow">ADMIN ONLY</p><h1>此頁僅限系統管理員</h1>
    <p>你的角色是「{{ roleLabels[currentUser.role] }}」，可繼續使用招募相關功能，但無法查看或修改帳號與系統設定。</p>
  </section>
  <section v-else class="admin-page">
    <div class="page-heading"><div><h1>帳號與權限</h1><p>管理使用者、部門及系統基礎資料；所有變更都會留下稽核紀錄。</p></div><button class="button secondary" :disabled="loading" @click="load">{{ loading ? '載入中…' : '重新整理' }}</button></div>
    <div v-if="error" class="alert error-alert"><span>!</span><p>{{ error }}</p><button @click="error = ''">×</button></div>
    <div class="admin-tabs panel">
      <button v-for="item in ([['users','使用者'],['departments','部門'],['catalogs','技能與標籤'],['settings','系統設定'],['audits','稽核紀錄']] as const)" :key="item[0]" :class="{ active: tab === item[0] }" @click="tab = item[0]">{{ item[1] }}</button>
    </div>

    <div v-if="tab === 'users'" class="panel admin-section">
      <header><div><h2>使用者帳號</h2><p>{{ users.length }} 個內部帳號，系統不開放公開註冊。</p></div><button class="button primary" @click="openUser()">＋ 新增帳號</button></header>
      <div class="admin-table"><table><thead><tr><th>使用者</th><th>角色</th><th>部門</th><th>狀態</th><th></th></tr></thead><tbody>
        <tr v-for="user in users" :key="user.id"><td><strong>{{ user.display_name }}</strong><small>{{ user.username }} · {{ user.email }}</small></td><td>{{ roleLabels[user.role] }}</td><td>{{ departmentName(user.department_id) }}</td><td><span class="status" :data-status="user.is_active ? 'approved' : 'archived'">{{ user.is_active ? '啟用' : '停用' }}</span></td><td><button class="text-button" @click="openUser(user)">編輯</button></td></tr>
      </tbody></table></div>
    </div>

    <div v-else-if="tab === 'departments'" class="panel admin-section">
      <header><div><h2>部門結構</h2><p>部門會用於 HR 與主管的資料範圍限制。</p></div><button class="button primary" @click="openDepartment()">＋ 新增部門</button></header>
      <div class="admin-table"><table><thead><tr><th>部門名稱</th><th>上層部門</th><th>狀態</th><th></th></tr></thead><tbody>
        <tr v-for="item in departments" :key="item.id"><td><strong>{{ item.name }}</strong><small>ID {{ item.id }}</small></td><td>{{ item.parent_id ? departmentName(item.parent_id) : '—' }}</td><td><span class="status" :data-status="item.is_active ? 'approved' : 'archived'">{{ item.is_active ? '啟用' : '停用' }}</span></td><td><button class="text-button" @click="openDepartment(item)">編輯</button></td></tr>
      </tbody></table></div>
    </div>

    <div v-else-if="tab === 'catalogs'" class="catalog-grid">
      <article class="panel admin-section"><header><div><h2>技能目錄</h2><p>{{ skills.length }} 筆標準化技能</p></div></header><ul class="catalog-list"><li v-for="item in skills" :key="item.id"><strong>{{ item.name }}</strong><span>{{ item.is_active ? '啟用' : '停用' }}</span></li><li v-if="!skills.length">尚無技能資料</li></ul></article>
      <article class="panel admin-section"><header><div><h2>人才標籤</h2><p>{{ tags.length }} 筆分類標籤</p></div></header><ul class="catalog-list"><li v-for="item in tags" :key="item.id"><strong>{{ item.name }}</strong><span>{{ item.category || 'candidate' }}</span></li><li v-if="!tags.length">尚無標籤資料</li></ul></article>
    </div>

    <div v-else-if="tab === 'settings'" class="panel admin-section"><header><div><h2>系統設定</h2><p>敏感設定的值會由 API 遮蔽。</p></div></header><div class="setting-list"><article v-for="item in settings" :key="item.key"><div><strong>{{ item.key }}</strong><small>{{ item.description || '未填說明' }}</small></div><code>{{ item.is_secret ? '••••••••' : JSON.stringify(item.value) }}</code></article><p v-if="!settings.length" class="empty">尚無系統設定</p></div></div>

    <div v-else class="panel admin-section"><header><div><h2>稽核紀錄</h2><p>最近 {{ audits.length }} 筆登入、管理操作與個資存取紀錄。</p></div></header><div class="admin-table"><table><thead><tr><th>時間</th><th>操作者</th><th>動作</th><th>資源</th><th>來源 IP</th></tr></thead><tbody><tr v-for="item in audits" :key="item.id"><td>{{ date(item.created_at) }}</td><td>#{{ item.actor_user_id || '系統' }}</td><td><strong>{{ item.action }}</strong></td><td>{{ item.resource_type }} {{ item.resource_id ? `#${item.resource_id}` : '' }}</td><td>{{ item.ip_address || '—' }}</td></tr></tbody></table></div></div>
  </section>

  <div v-if="userDialog" class="modal-overlay" @click.self="userDialog = false"><form class="modal-card compact-modal" @submit.prevent="saveUser"><header><div><small>ADMIN</small><h2>{{ editingUser ? '編輯使用者' : '新增使用者' }}</h2></div><button type="button" @click="userDialog = false">×</button></header><div class="form-grid"><label>帳號 *<input v-model="userForm.username" :disabled="!!editingUser" required></label><label>顯示名稱 *<input v-model="userForm.display_name" required></label><label>Email *<input v-model="userForm.email" type="email" required></label><label>{{ editingUser ? '新密碼（不變請留空）' : '密碼（至少 12 字元）*' }}<input v-model="userForm.password" type="password" :required="!editingUser" minlength="12"></label><label>角色<select v-model="userForm.role"><option value="admin">系統管理員</option><option value="hr">HR</option><option value="manager">用人主管</option></select></label><label>部門<select v-model="userForm.department_id"><option :value="null">不限部門</option><option v-for="item in departments" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label v-if="editingUser"><input v-model="userForm.is_active" class="inline-check" type="checkbox"> 啟用帳號</label></div><footer><button type="button" class="button secondary" @click="userDialog = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存' }}</button></footer></form></div>

  <div v-if="departmentDialog" class="modal-overlay" @click.self="departmentDialog = false"><form class="modal-card compact-modal" @submit.prevent="saveDepartment"><header><div><small>ORGANIZATION</small><h2>{{ editingDepartment ? '編輯部門' : '新增部門' }}</h2></div><button type="button" @click="departmentDialog = false">×</button></header><div class="form-grid"><label>部門名稱 *<input v-model="departmentForm.name" required></label><label>上層部門<select v-model="departmentForm.parent_id"><option :value="null">無</option><option v-for="item in departments.filter(item => item.id !== editingDepartment?.id)" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label v-if="editingDepartment"><input v-model="departmentForm.is_active" class="inline-check" type="checkbox"> 啟用部門</label></div><footer><button type="button" class="button secondary" @click="departmentDialog = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存' }}</button></footer></form></div>
  <Transition name="toast"><div v-if="notice" class="toast"><span>✓</span>{{ notice }}</div></Transition>
</template>

<style scoped>
.admin-page{display:grid;gap:14px}.admin-tabs{padding:6px;display:flex;gap:4px;overflow:auto}.admin-tabs button{border:0;background:transparent;border-radius:7px;padding:9px 13px;white-space:nowrap;color:#6b7d79;font-size:10px}.admin-tabs button.active{background:#e7f2ef;color:#1f655e;font-weight:700}.admin-section>header{padding:17px 19px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:15px}.admin-section h2{font-size:14px;margin:0}.admin-section header p{font-size:9px;color:var(--muted);margin:3px 0 0}.admin-table{overflow:auto}.admin-table table{min-width:680px}.catalog-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.catalog-list{list-style:none;margin:0;padding:8px 18px 18px}.catalog-list li{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #edf1f0;font-size:10px}.catalog-list span{font-size:8px;color:var(--muted)}.setting-list article{padding:13px 19px;border-bottom:1px solid #edf1f0;display:flex;justify-content:space-between;gap:18px}.setting-list strong,.setting-list small{display:block;font-size:10px}.setting-list small{font-size:8px;color:var(--muted);margin-top:3px}.setting-list code{font-size:9px;color:#52706a;max-width:45%;overflow:hidden;text-overflow:ellipsis}.admin-denied{text-align:center;padding:75px 22px}.admin-denied>span{font-size:30px}.admin-denied h1{font-size:21px}.admin-denied>p:last-child{font-size:10px;line-height:1.8;color:var(--muted);max-width:520px;margin:auto}.compact-modal{max-width:620px}.inline-check{display:inline-block!important;width:auto!important;height:auto!important;margin:0 5px 0 0!important}@media(max-width:700px){.catalog-grid{grid-template-columns:1fr}.admin-section>header{align-items:flex-start}.setting-list article{display:block}.setting-list code{display:block;max-width:100%;margin-top:8px}}
</style>
