<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { adminApi, type DatabaseOverview, type IssueSeverity, type IssueStatus, type SystemIssue } from '../services/adminApi'

const view = ref<'issues' | 'database'>('issues')
const issues = ref<SystemIssue[]>([])
const database = ref<DatabaseOverview | null>(null)
const loading = ref(false), saving = ref(false), dialog = ref(false)
const error = ref(''), expandedTable = ref<string | null>(null)
const editing = ref<SystemIssue | null>(null)
const form = reactive({ title: '', description: '', page: '', severity: 'medium' as IssueSeverity, status: 'open' as IssueStatus, reproduction_steps: '', resolution_notes: '' })
const unresolvedCount = computed(() => issues.value.filter(item => !['resolved', 'closed'].includes(item.status)).length)
const severityLabel: Record<IssueSeverity, string> = { low: '低', medium: '中', high: '高', critical: '重大' }
const statusLabel: Record<IssueStatus, string> = { open: '待處理', investigating: '調查中', resolved: '已解決', closed: '已結案' }

async function load() {
  loading.value = true; error.value = ''
  try {
    const [a, b] = await Promise.all([adminApi.systemIssues(), adminApi.databaseOverview()])
    issues.value = a.data; database.value = b.data
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '無法載入 IT 維運資料' }
  finally { loading.value = false }
}
function openIssue(issue?: SystemIssue) {
  editing.value = issue || null
  Object.assign(form, issue ? { title: issue.title, description: issue.description, page: issue.page, severity: issue.severity, status: issue.status, reproduction_steps: issue.reproduction_steps || '', resolution_notes: issue.resolution_notes || '' } : { title: '', description: '', page: '', severity: 'medium', status: 'open', reproduction_steps: '', resolution_notes: '' })
  dialog.value = true
}
async function save() {
  saving.value = true; error.value = ''
  const payload = { ...form, title: form.title.trim(), description: form.description.trim(), page: form.page.trim(), reproduction_steps: form.reproduction_steps.trim() || null, resolution_notes: form.resolution_notes.trim() || null }
  try {
    if (editing.value) await adminApi.updateSystemIssue(editing.value.id, payload)
    else await adminApi.createSystemIssue(payload)
    dialog.value = false; await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '問題紀錄儲存失敗' }
  finally { saving.value = false }
}
function date(value: string) { return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) }
onMounted(load)
</script>

<template>
  <section class="ops panel">
    <header class="ops-header"><div><p class="eyebrow">IT OPERATIONS</p><h2>系統維運中心</h2><p>集中追蹤問題，並以唯讀方式檢查資料庫健康與結構。</p></div><button class="button secondary" :disabled="loading" @click="load">{{ loading ? '更新中…' : '重新整理' }}</button></header>
    <div v-if="error" class="alert error-alert"><span>!</span><p>{{ error }}</p><button @click="error = ''">×</button></div>
    <nav class="ops-nav"><button :class="{ active: view === 'issues' }" @click="view = 'issues'">問題紀錄 <b>{{ unresolvedCount }}</b></button><button :class="{ active: view === 'database' }" @click="view = 'database'">資料庫與資料表</button></nav>

    <div v-if="view === 'issues'" class="ops-body">
      <div class="section-title"><div><h3>問題紀錄</h3><p>保留發生頁面、重現方式與每次處理狀態。</p></div><button class="button primary" @click="openIssue()">＋ 新增問題</button></div>
      <div class="issue-list"><article v-for="issue in issues" :key="issue.id" class="issue-card" @click="openIssue(issue)"><div><span class="severity" :data-severity="issue.severity">{{ severityLabel[issue.severity] }}</span><strong>{{ issue.title }}</strong></div><p>{{ issue.description }}</p><footer><span>頁面：{{ issue.page }}</span><span>{{ statusLabel[issue.status] }}</span><span>更新：{{ date(issue.updated_at) }} · #{{ issue.updated_by_user_id || '系統' }}</span></footer></article><p v-if="!issues.length && !loading" class="empty">目前沒有問題紀錄，系統運作順利。</p></div>
    </div>

    <div v-else class="ops-body">
      <div v-if="database" class="db-summary"><article><span class="health-dot" :class="{ healthy: database.healthy }"></span><div><small>連線健康</small><strong>{{ database.healthy ? '正常' : '異常' }}</strong></div></article><article><div><small>資料庫</small><strong>{{ database.dialect }} {{ database.server_version || '' }}</strong></div></article><article><div><small>安全模式</small><strong>{{ database.transport_security }}</strong></div></article><article><div><small>資料表</small><strong>{{ database.tables.length }} 張</strong></div></article></div>
      <p class="privacy-note">此頁只顯示結構與統計，不提供連線字串、密碼或任何個資資料列。</p>
      <div v-if="database" class="table-list"><article v-for="table in database.tables" :key="table.name"><button @click="expandedTable = expandedTable === table.name ? null : table.name"><code>{{ table.name }}</code><span>{{ table.row_count ?? '無權讀取' }} 筆 · {{ table.columns.length }} 欄位</span><b>{{ expandedTable === table.name ? '−' : '+' }}</b></button><div v-if="expandedTable === table.name" class="column-list"><div v-for="column in table.columns" :key="column.name"><code>{{ column.name }}</code><span>{{ column.type }}</span><small>{{ column.primary_key ? 'PK · ' : '' }}{{ column.nullable ? '可空白' : '必填' }}</small></div></div></article></div>
    </div>
  </section>

  <div v-if="dialog" class="modal-overlay" @click.self="dialog = false"><form class="modal-card issue-modal" @submit.prevent="save"><header><div><small>ISSUE LOG</small><h2>{{ editing ? '更新問題紀錄' : '新增問題紀錄' }}</h2></div><button type="button" @click="dialog = false">×</button></header><div class="form-grid"><label>問題標題 *<input v-model="form.title" required maxlength="200"></label><label>發生頁面 *<input v-model="form.page" required maxlength="255" placeholder="例如：/candidates"></label><label>嚴重度<select v-model="form.severity"><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">重大</option></select></label><label>狀態<select v-model="form.status"><option value="open">待處理</option><option value="investigating">調查中</option><option value="resolved">已解決</option><option value="closed">已結案</option></select></label><label class="full">問題說明 *<textarea v-model="form.description" required rows="3"></textarea></label><label class="full">重現步驟<textarea v-model="form.reproduction_steps" rows="4"></textarea></label><label class="full">處理紀錄<textarea v-model="form.resolution_notes" rows="4"></textarea></label></div><footer><button type="button" class="button secondary" @click="dialog = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存紀錄' }}</button></footer></form></div>
</template>

<style scoped>
.ops{overflow:hidden}.ops-header{padding:18px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.ops-header h2{margin:2px 0;font-size:16px}.ops-header p{margin:0;color:var(--muted);font-size:10px}.ops-nav{display:flex;padding:7px 18px;border-bottom:1px solid var(--line);gap:5px}.ops-nav button{border:0;background:transparent;padding:9px 12px;border-radius:8px;color:var(--muted);font-size:10px}.ops-nav button.active{background:#e7f2ef;color:#1f655e;font-weight:700}.ops-nav b{margin-left:5px;background:#d67759;color:white;border-radius:20px;padding:1px 5px}.ops-body{padding:18px}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-title h3{margin:0;font-size:14px}.section-title p{font-size:9px;color:var(--muted);margin:3px 0}.issue-list{display:grid;gap:8px}.issue-card{border:1px solid var(--line);border-radius:10px;padding:13px;background:#fff;cursor:pointer;transition:.2s}.issue-card:hover{border-color:#6ba69d;transform:translateY(-1px)}.issue-card strong{font-size:11px;margin-left:8px}.issue-card p{font-size:9px;color:#526761;margin:8px 0}.issue-card footer{display:flex;gap:14px;flex-wrap:wrap;font-size:8px;color:var(--muted)}.severity{font-size:8px;border-radius:5px;padding:3px 6px;background:#e7f2ef;color:#256a61}.severity[data-severity="high"],.severity[data-severity="critical"]{background:#fbe7e0;color:#a54127}.db-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.db-summary article{border:1px solid var(--line);border-radius:10px;padding:12px;display:flex;align-items:center;gap:8px}.db-summary small,.db-summary strong{display:block;font-size:8px}.db-summary strong{font-size:11px;margin-top:3px}.health-dot{width:9px;height:9px;border-radius:50%;background:#d65d4d}.health-dot.healthy{background:#45a875;box-shadow:0 0 0 4px #45a87520}.privacy-note{font-size:9px;color:#55766f;background:#eff7f5;border-radius:8px;padding:9px 11px}.table-list>article{border-bottom:1px solid var(--line)}.table-list button{width:100%;border:0;background:white;display:grid;grid-template-columns:1fr auto 20px;text-align:left;padding:12px 4px;align-items:center}.table-list button span{font-size:8px;color:var(--muted)}.column-list{background:#f8faf9;padding:4px 12px 10px}.column-list div{display:grid;grid-template-columns:1fr 1fr 100px;padding:7px;border-bottom:1px solid #e7eeec;font-size:8px}.column-list small{color:var(--muted)}.issue-modal{max-width:680px}.form-grid .full{grid-column:1/-1}@media(max-width:700px){.db-summary{grid-template-columns:1fr 1fr}.ops-header,.section-title{align-items:flex-start}}
</style>
