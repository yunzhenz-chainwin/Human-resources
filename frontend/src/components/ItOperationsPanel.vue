<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  adminApi,
  type DatabaseColumn,
  type DatabaseOverview,
  type DatabaseTablePreview,
  type IssueSeverity,
  type IssueStatus,
  type SystemIssue,
} from '../services/adminApi'

const view = ref<'issues' | 'database'>('issues')
const issues = ref<SystemIssue[]>([])
const database = ref<DatabaseOverview | null>(null)
const preview = ref<DatabaseTablePreview | null>(null)
const loading = ref(false), saving = ref(false), dialog = ref(false), previewLoading = ref(false)
const rowDialog = ref(false), rowSaving = ref(false), rowMode = ref<'create' | 'edit'>('create')
const privacyDialog = ref(false), piiRevealed = ref(false), privacyReason = ref('')
const error = ref(''), selectedTable = ref(''), tableFilter = ref(''), rowSearch = ref('')
const editing = ref<SystemIssue | null>(null)
const editingRowId = ref<number | string | null>(null)
const rowValues = ref<Record<string, string>>({})
let previewRequestSequence = 0
const form = reactive({ title: '', description: '', page: '', severity: 'medium' as IssueSeverity, status: 'open' as IssueStatus, progress_percent: 0, expected_completion_date: '', reproduction_steps: '', resolution_notes: '' })
const unresolvedCount = computed(() => issues.value.filter(item => !['resolved', 'closed'].includes(item.status)).length)
const resolvedCount = computed(() => issues.value.filter(item => ['resolved', 'closed'].includes(item.status)).length)
const averageProgress = computed(() => issues.value.length ? Math.round(issues.value.reduce((sum, item) => sum + item.progress_percent, 0) / issues.value.length) : 0)
const overdueCount = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return issues.value.filter(item => item.expected_completion_date && item.expected_completion_date < today && item.progress_percent < 100).length
})
const filteredTables = computed(() => {
  const keyword = tableFilter.value.trim().toLowerCase()
  return database.value?.tables.filter(table =>
    !keyword || table.name.toLowerCase().includes(keyword) || table.display_name.toLowerCase().includes(keyword),
  ) || []
})
const selectedTableMeta = computed(() => database.value?.tables.find(table => table.name === selectedTable.value) || null)
const revealableColumns = computed(() => selectedTableMeta.value?.columns.filter(column => column.revealable) || [])
const editableColumns = computed(() => selectedTableMeta.value?.columns.filter(column => column.editable) || [])
const primaryKeyColumn = computed(() => selectedTableMeta.value?.columns.find(column => column.primary_key) || null)
const totalPages = computed(() => Math.max(1, Math.ceil((preview.value?.total || 0) / (preview.value?.page_size || 20))))
const severityLabel: Record<IssueSeverity, string> = { low: '低', medium: '中', high: '高', critical: '緊急' }
const statusLabel: Record<IssueStatus, string> = { open: '待處理', investigating: '調查中', resolved: '已修復', closed: '已關閉' }

async function load() {
  loading.value = true; error.value = ''
  try {
    const [a, b] = await Promise.all([adminApi.systemIssues(), adminApi.databaseOverview()])
    issues.value = a.data; database.value = b.data
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '無法載入 IT 維運資料' }
  finally { loading.value = false }
}
async function openTable(name: string, page = 1) {
  const requestId = ++previewRequestSequence
  const search = rowSearch.value
  if (selectedTable.value !== name) preview.value = null
  selectedTable.value = name; previewLoading.value = true; error.value = ''
  try {
    const result = (await adminApi.databaseTableRows(name, page, search, piiRevealed.value, privacyReason.value)).data
    if (requestId === previewRequestSequence && selectedTable.value === name) preview.value = result
  } catch (cause) {
    if (requestId === previewRequestSequence) error.value = cause instanceof Error ? cause.message : '無法載入資料預覽'
  } finally {
    if (requestId === previewRequestSequence) previewLoading.value = false
  }
}
function selectTable(name: string) {
  piiRevealed.value = false
  privacyReason.value = ''
  rowSearch.value = ''
  void openTable(name)
}
function requestPiiReveal() {
  privacyReason.value = ''
  privacyDialog.value = true
}
async function confirmPiiReveal() {
  const reason = privacyReason.value.trim()
  if (reason.length < 5) {
    error.value = '請填寫至少 5 個字元的個資查閱原因'
    return
  }
  privacyDialog.value = false
  piiRevealed.value = true
  await openTable(selectedTable.value, preview.value?.page || 1)
  if (!preview.value?.pii_revealed) piiRevealed.value = false
}
async function hidePii() {
  piiRevealed.value = false
  privacyReason.value = ''
  await openTable(selectedTable.value, preview.value?.page || 1)
}
function serializeRowValue(value: unknown) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  if (typeof value === 'string' && /T\d{2}:\d{2}:\d{2}/.test(value)) return value.slice(0, 16)
  return String(value)
}
function defaultRowValue(column: DatabaseColumn) {
  if (/BOOL/i.test(column.type)) return 'true'
  if (/JSON/i.test(column.type)) return column.name === 'match_weights' ? '{}' : '[]'
  const defaults: Record<string, string> = {
    category: 'candidate', employment_type: 'full_time', headcount: '1', urgency: 'normal',
    status: selectedTable.value === 'job_applications' ? 'submitted' : 'draft',
    source: 'manual', sort_order: '0', is_active: 'true',
  }
  return defaults[column.name] || ''
}
function openRowEditor(row?: Record<string, unknown>) {
  if (!selectedTableMeta.value || !editableColumns.value.length) return
  rowMode.value = row ? 'edit' : 'create'
  const key = primaryKeyColumn.value?.name
  editingRowId.value = row && key ? row[key] as number | string : null
  rowValues.value = Object.fromEntries(editableColumns.value.map(column => [
    column.name,
    row ? serializeRowValue(row[column.name]) : defaultRowValue(column),
  ]))
  rowDialog.value = true
}
function rowInputKind(column: DatabaseColumn) {
  if (/BOOL/i.test(column.type)) return 'boolean'
  if (/JSON|TEXT/i.test(column.type) || ['jd', 'summary', 'description', 'content', 'cover_letter'].includes(column.name)) return 'textarea'
  if (/DATETIME/i.test(column.type)) return 'datetime-local'
  if (/DATE/i.test(column.type)) return 'date'
  if (/INT|NUMERIC|DECIMAL|FLOAT|REAL/i.test(column.type)) return 'number'
  return 'text'
}
function parseRowValue(column: DatabaseColumn) {
  const raw = rowValues.value[column.name]?.trim() ?? ''
  if (!raw && column.nullable) return null
  if (/JSON/i.test(column.type)) {
    try { return JSON.parse(raw) }
    catch { throw new Error(`${column.name} 必須是有效 JSON，例如 [] 或 {}`) }
  }
  if (/BOOL/i.test(column.type)) return raw === 'true'
  if (/INT/i.test(column.type)) return Number.parseInt(raw, 10)
  if (/NUMERIC|DECIMAL|FLOAT|REAL/i.test(column.type)) return Number(raw)
  return raw
}
async function refreshSelectedTable(page = preview.value?.page || 1) {
  const overview = await adminApi.databaseOverview()
  database.value = overview.data
  await openTable(selectedTable.value, page)
}
async function saveRow() {
  if (!selectedTableMeta.value) return
  rowSaving.value = true; error.value = ''
  try {
    const values = Object.fromEntries(editableColumns.value.map(column => [column.name, parseRowValue(column)]))
    if (rowMode.value === 'edit' && editingRowId.value !== null) {
      await adminApi.updateDatabaseRow(selectedTable.value, editingRowId.value, values)
    } else {
      await adminApi.createDatabaseRow(selectedTable.value, values)
    }
    rowDialog.value = false
    await refreshSelectedTable(rowMode.value === 'create' ? 1 : preview.value?.page || 1)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '資料列儲存失敗'
  } finally { rowSaving.value = false }
}
async function deleteRow(row: Record<string, unknown>) {
  const key = primaryKeyColumn.value?.name
  const rowId = key ? row[key] as number | string : null
  if (!selectedTableMeta.value?.can_delete || rowId === null || rowId === undefined) return
  if (!window.confirm(`確定刪除 ${selectedTableMeta.value.display_name} 的資料 #${rowId}？此動作會留下稽核紀錄。`)) return
  error.value = ''
  try {
    await adminApi.deleteDatabaseRow(selectedTable.value, rowId)
    await refreshSelectedTable(preview.value?.page || 1)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '資料列刪除失敗' }
}
function openIssue(issue?: SystemIssue) {
  editing.value = issue || null
  Object.assign(form, issue ? { title: issue.title, description: issue.description, page: issue.page, severity: issue.severity, status: issue.status, progress_percent: issue.progress_percent, expected_completion_date: issue.expected_completion_date || '', reproduction_steps: issue.reproduction_steps || '', resolution_notes: issue.resolution_notes || '' } : { title: '', description: '', page: '', severity: 'medium', status: 'open', progress_percent: 0, expected_completion_date: '', reproduction_steps: '', resolution_notes: '' })
  dialog.value = true
}
async function save() {
  saving.value = true; error.value = ''
  const payload = { ...form, title: form.title.trim(), description: form.description.trim(), page: form.page.trim(), expected_completion_date: form.expected_completion_date || null, reproduction_steps: form.reproduction_steps.trim() || null, resolution_notes: form.resolution_notes.trim() || null }
  try {
    if (editing.value) await adminApi.updateSystemIssue(editing.value.id, payload)
    else await adminApi.createSystemIssue(payload)
    dialog.value = false; await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '儲存問題失敗' }
  finally { saving.value = false }
}
function date(value: string) { return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) }
function dateOnly(value: string | null) { return value ? new Intl.DateTimeFormat('zh-TW', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`)) : '未設定' }
function display(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
onMounted(load)
watch(view, next => {
  if (next !== 'database' && piiRevealed.value) {
    piiRevealed.value = false
    privacyReason.value = ''
    preview.value = null
    selectedTable.value = ''
  }
})
</script>

<template>
  <section class="ops panel">
    <header class="ops-header"><div><p class="eyebrow">IT OPERATIONS</p><h2>系統維運中心</h2><p>集中追蹤頁面問題，並安全檢視資料庫結構與資料狀態。</p></div><button class="button secondary" :disabled="loading" @click="load">{{ loading ? '更新中…' : '重新整理' }}</button></header>
    <div v-if="error" class="alert error-alert" role="alert"><span>!</span><p>{{ error }}</p><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
    <nav class="ops-nav" aria-label="系統維運功能" role="tablist"><button role="tab" :aria-selected="view === 'issues'" :class="{ active: view === 'issues' }" @click="view = 'issues'">問題紀錄 <b>{{ unresolvedCount }}</b></button><button role="tab" :aria-selected="view === 'database'" :class="{ active: view === 'database' }" @click="view = 'database'">資料表維護</button></nav>

    <div v-if="view === 'issues'" class="ops-body">
      <div class="section-title"><div><h3>問題與修復紀錄</h3><p>保留重現步驟、處理狀態及修復方式，供後續維護追蹤。</p></div><button class="button primary" @click="openIssue()">新增問題</button></div>
      <div class="issue-dashboard">
        <article><small>全部問題</small><strong>{{ issues.length }}</strong><span>集中留存維護歷程</span></article>
        <article><small>處理中</small><strong>{{ unresolvedCount }}</strong><span>需要持續追蹤</span></article>
        <article><small>已完成</small><strong>{{ resolvedCount }}</strong><span>完成率 {{ issues.length ? Math.round(resolvedCount / issues.length * 100) : 0 }}%</span></article>
        <article class="overall-progress"><div><small>整體平均進度</small><strong>{{ averageProgress }}%</strong></div><div class="progress-track"><i :style="{ width: `${averageProgress}%` }"></i></div><span v-if="overdueCount" class="overdue">{{ overdueCount }} 件已超過預計完成日</span><span v-else>目前沒有逾期項目</span></article>
      </div>
      <div class="issue-list">
        <article v-for="issue in issues" :key="issue.id" class="issue-card" role="button" tabindex="0" :aria-label="`編輯問題：${issue.title}，目前進度 ${issue.progress_percent}%`" @click="openIssue(issue)" @keydown.enter.prevent="openIssue(issue)" @keydown.space.prevent="openIssue(issue)">
          <div class="issue-heading"><div><span class="severity" :data-severity="issue.severity">{{ severityLabel[issue.severity] }}</span><strong>{{ issue.title }}</strong></div><b>{{ issue.progress_percent }}%</b></div>
          <p>{{ issue.description }}</p>
          <div class="progress-track" role="progressbar" aria-label="問題處理進度" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="issue.progress_percent"><i :class="{ complete: issue.progress_percent === 100 }" :style="{ width: `${issue.progress_percent}%` }"></i></div>
          <div class="issue-dates"><span>狀態<strong>{{ statusLabel[issue.status] }}</strong></span><span>發生頁面<strong>{{ issue.page }}</strong></span><span>最後修改<strong>{{ date(issue.updated_at) }}</strong></span><span>預計完成<strong>{{ dateOnly(issue.expected_completion_date) }}</strong></span></div>
        </article>
        <p v-if="!issues.length && !loading" class="empty">目前沒有問題紀錄。</p>
      </div>
    </div>

    <div v-else class="ops-body db-body">
      <div v-if="database" class="db-summary"><article><span class="health-dot" :class="{ healthy: database.healthy }"></span><div><small>連線狀態</small><strong>{{ database.healthy ? '正常' : '異常' }}</strong></div></article><article><div><small>資料庫</small><strong>{{ database.dialect }} {{ database.server_version || '' }}</strong></div></article><article><div><small>連線保護</small><strong>{{ database.transport_security }}</strong></div></article><article><div><small>資料表</small><strong>{{ database.tables.length }} 張</strong></div></article></div>
      <p class="privacy-note" :class="{ revealed: piiRevealed }">{{ piiRevealed ? '個資暫時顯示中：本次查閱人員、時間、原因與顯示欄位已寫入稽核紀錄。離開資料表頁面會自動恢復遮罩。' : '此頁預設遮罩人才個資。IT 可針對人才主檔填寫原因後暫時顯示；密碼、Token、Secret 與履歷原文永遠不會解除遮罩。' }}</p>
      <div class="db-workspace">
        <aside class="table-sidebar">
          <input v-model="tableFilter" class="table-search" placeholder="搜尋資料表…">
          <button v-for="table in filteredTables" :key="table.name" :class="{ selected: selectedTable === table.name }" @click="selectTable(table.name)"><strong class="table-display-name">{{ table.display_name }}</strong><span class="table-technical-name">{{ table.name }}</span><small>{{ table.row_count ?? '未知' }} 筆 · {{ table.columns.length }} 欄</small></button>
        </aside>
        <main class="preview-panel">
          <div v-if="preview" class="preview-toolbar"><div><h3>{{ preview.display_name }}</h3><p class="table-description">{{ preview.description }}</p><small>資料表：{{ preview.table_name }} · 共 {{ preview.total }} 筆；{{ preview.redacted_columns.length }} 個敏感欄位已遮蔽</small></div><div class="preview-actions"><button v-if="revealableColumns.length && !piiRevealed" class="button privacy-button" @click="requestPiiReveal">顯示個資</button><button v-if="revealableColumns.length && piiRevealed" class="button privacy-button active" @click="hidePii">重新遮罩</button><button v-if="selectedTableMeta?.can_create" class="button primary" @click="openRowEditor()">＋ 新增資料</button><form @submit.prevent="openTable(selectedTable)"><input v-model="rowSearch" placeholder="搜尋本表文字欄位"><button class="button secondary">搜尋</button></form></div></div>
          <details v-if="selectedTableMeta" class="schema-details"><summary>欄位結構（{{ selectedTableMeta.columns.length }}）</summary><div><span v-for="column in selectedTableMeta.columns" :key="column.name" :class="{ redacted: column.redacted, revealable: column.revealable }"><code>{{ column.name }}</code> {{ column.type }}<small>{{ column.primary_key ? ' PK' : '' }}{{ column.nullable ? ' 可空' : ' 必填' }}{{ column.revealable ? ' · 可授權顯示' : column.redacted ? ' · 永久遮蔽' : '' }}</small></span></div></details>
          <p v-if="selectedTableMeta?.protection_reason" class="table-protection">🔒 {{ selectedTableMeta.protection_reason }}</p>
          <div v-if="previewLoading" class="empty">讀取資料中…</div>
          <div v-else-if="preview" class="table-scroll"><table><thead><tr><th v-for="column in preview.visible_columns" :key="column">{{ column }}</th><th v-if="selectedTableMeta?.can_update || selectedTableMeta?.can_delete" class="row-actions-head">操作</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td v-for="column in preview.visible_columns" :key="column" :title="display(row[column])">{{ display(row[column]) }}</td><td v-if="selectedTableMeta?.can_update || selectedTableMeta?.can_delete" class="row-actions"><button v-if="selectedTableMeta?.can_update" @click="openRowEditor(row)">編輯</button><button v-if="selectedTableMeta?.can_delete" class="danger" @click="deleteRow(row)">刪除</button></td></tr></tbody></table><p v-if="!preview.rows.length" class="empty">沒有符合條件的資料。</p></div>
          <div v-if="preview && totalPages > 1" class="pagination"><button :disabled="preview.page <= 1" @click="openTable(selectedTable, preview.page - 1)">上一頁</button><span>第 {{ preview.page }} / {{ totalPages }} 頁</span><button :disabled="preview.page >= totalPages" @click="openTable(selectedTable, preview.page + 1)">下一頁</button></div>
          <p v-if="!preview && !previewLoading" class="empty">請從左側選擇資料表，查看結構與分頁資料。</p>
        </main>
      </div>
    </div>
  </section>

  <div v-if="dialog" class="modal-overlay" @click.self="dialog = false" @keydown.esc="dialog = false"><form class="modal-card issue-modal" role="dialog" aria-modal="true" aria-labelledby="issue-dialog-title" @submit.prevent="save"><header><div><small>ISSUE LOG</small><h2 id="issue-dialog-title">{{ editing ? '更新問題紀錄' : '新增問題紀錄' }}</h2></div><button type="button" aria-label="關閉問題視窗" @click="dialog = false">×</button></header><div class="form-grid"><label>問題標題 *<input v-model="form.title" required maxlength="200"></label><label>發生頁面 *<input v-model="form.page" required maxlength="255" placeholder="例如：/candidates"></label><label>嚴重程度<select v-model="form.severity"><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">緊急</option></select></label><label>狀態<select v-model="form.status"><option value="open">待處理</option><option value="investigating">調查中</option><option value="resolved">已修復</option><option value="closed">已關閉</option></select></label><label>目前進度（{{ form.progress_percent }}%）<input v-model.number="form.progress_percent" type="range" min="0" max="100" step="5"></label><label>預計完成日期<input v-model="form.expected_completion_date" type="date"></label><label class="full">問題說明 *<textarea v-model="form.description" required rows="3"></textarea></label><label class="full">重現步驟<textarea v-model="form.reproduction_steps" rows="4"></textarea></label><label class="full">處理與修復方式<textarea v-model="form.resolution_notes" rows="4"></textarea></label></div><footer><button type="button" class="button secondary" @click="dialog = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存紀錄' }}</button></footer></form></div>

  <div v-if="rowDialog" class="modal-overlay" @click.self="rowDialog = false" @keydown.esc="rowDialog = false"><form class="modal-card row-editor-modal" role="dialog" aria-modal="true" aria-labelledby="row-dialog-title" @submit.prevent="saveRow"><header><div><small>DATABASE EDITOR</small><h2 id="row-dialog-title">{{ rowMode === 'create' ? `新增${selectedTableMeta?.display_name || '資料'}` : `編輯資料 #${editingRowId}` }}</h2></div><button type="button" aria-label="關閉資料編輯視窗" @click="rowDialog = false">×</button></header><p class="row-editor-note">只顯示後端允許維護的欄位；關聯欄位請填寫現有資料的 ID，JSON 欄位請使用有效的 JSON 格式。</p><div class="row-editor-grid"><label v-for="column in editableColumns" :key="column.name" :class="{ wide: rowInputKind(column) === 'textarea' }"><span>{{ column.name }} <b v-if="!column.nullable">*</b></span><small>{{ column.type }}{{ column.nullable ? ' · 可留空' : '' }}</small><select v-if="rowInputKind(column) === 'boolean'" v-model="rowValues[column.name]"><option value="true">true</option><option value="false">false</option></select><textarea v-else-if="rowInputKind(column) === 'textarea'" v-model="rowValues[column.name]" :required="!column.nullable" rows="4"></textarea><input v-else v-model="rowValues[column.name]" :type="rowInputKind(column)" :required="!column.nullable" :step="rowInputKind(column) === 'number' ? 'any' : undefined"></label></div><footer><button type="button" class="button secondary" @click="rowDialog = false">取消</button><button class="button primary" :disabled="rowSaving">{{ rowSaving ? '儲存中…' : '確認儲存' }}</button></footer></form></div>

  <div v-if="privacyDialog" class="modal-overlay" @click.self="privacyDialog = false" @keydown.esc="privacyDialog = false"><form class="modal-card privacy-modal" role="dialog" aria-modal="true" aria-labelledby="privacy-dialog-title" @submit.prevent="confirmPiiReveal"><header><div><small>PRIVACY ACCESS</small><h2 id="privacy-dialog-title">暫時顯示人才個資</h2></div><button type="button" aria-label="關閉個資授權視窗" @click="privacyDialog = false">×</button></header><div class="privacy-form"><p>只會顯示人才主檔的姓名、聯絡方式與招募必要欄位。每次查閱都會記錄帳號、時間、IP、原因與顯示欄位。</p><label>查閱原因 *<textarea v-model="privacyReason" minlength="5" maxlength="200" rows="4" required placeholder="例如：協助 HR 排查人才資料同步問題"></textarea><small>{{ privacyReason.trim().length }} / 200</small></label></div><footer><button type="button" class="button secondary" @click="privacyDialog = false">保持遮罩</button><button class="button privacy-button" :disabled="privacyReason.trim().length < 5">確認並顯示</button></footer></form></div>
</template>

<style scoped>
.ops{overflow:hidden}.ops-header{padding:18px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.ops-header h2{margin:2px 0;font-size:16px}.ops-header p{margin:0;color:var(--muted);font-size:10px}.ops-nav{display:flex;padding:7px 18px;border-bottom:1px solid var(--line);gap:5px}.ops-nav button{border:0;background:transparent;padding:9px 12px;border-radius:8px;color:var(--muted);font-size:10px}.ops-nav button.active{background:#e7f2ef;color:#1f655e;font-weight:700}.ops-nav b{margin-left:5px;background:#d67759;color:white;border-radius:20px;padding:1px 5px}.ops-body{padding:18px}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-title h3{margin:0;font-size:14px}.section-title p{font-size:9px;color:var(--muted);margin:3px 0}.issue-list{display:grid;gap:8px}.issue-card{border:1px solid var(--line);border-radius:10px;padding:13px;background:#fff;cursor:pointer;transition:.2s}.issue-card:hover{border-color:#6ba69d;transform:translateY(-1px)}.issue-card:focus-visible{outline:3px solid rgba(33,107,99,.28);outline-offset:2px;border-color:#4a9188}.issue-card strong{font-size:11px;margin-left:8px}.issue-card p{font-size:9px;color:#526761;margin:8px 0}.issue-card footer{display:flex;gap:14px;flex-wrap:wrap;font-size:8px;color:var(--muted)}.severity{font-size:8px;border-radius:5px;padding:3px 6px;background:#e7f2ef;color:#256a61}.severity[data-severity="high"],.severity[data-severity="critical"]{background:#fbe7e0;color:#a54127}.db-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.db-summary article{border:1px solid var(--line);border-radius:10px;padding:12px;display:flex;align-items:center;gap:8px}.db-summary small,.db-summary strong{display:block;font-size:8px}.db-summary strong{font-size:11px;margin-top:3px}.health-dot{width:9px;height:9px;border-radius:50%;background:#d65d4d}.health-dot.healthy{background:#45a875;box-shadow:0 0 0 4px #45a87520}.privacy-note{font-size:9px;color:#55766f;background:#eff7f5;border-radius:8px;padding:9px 11px}.db-workspace{display:grid;grid-template-columns:220px minmax(0,1fr);border:1px solid var(--line);border-radius:12px;min-height:420px;overflow:hidden}.table-sidebar{border-right:1px solid var(--line);padding:10px;max-height:540px;overflow:auto;background:#f8faf9}.table-search,.preview-toolbar input{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;padding:9px;background:white}.table-sidebar button{display:flex;flex-direction:column;width:100%;border:0;border-radius:8px;padding:9px;text-align:left;background:transparent}.table-sidebar button:hover,.table-sidebar button.selected{background:#e2f0ed;color:#175b53}.table-sidebar small{font-size:8px;color:var(--muted);margin-top:3px}.preview-panel{min-width:0;padding:12px}.preview-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.preview-toolbar h3{margin:0;font-size:13px}.preview-toolbar small{font-size:8px;color:var(--muted)}.preview-toolbar form{display:flex;gap:5px;width:300px}.table-scroll{overflow:auto;max-height:390px}.table-scroll table{border-collapse:collapse;width:max-content;min-width:100%;font-size:8px}.table-scroll th{position:sticky;top:0;background:#174f49;color:white;text-align:left}.table-scroll th,.table-scroll td{padding:8px;border:1px solid #e0e8e6;max-width:240px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.table-scroll tr:nth-child(even){background:#f8faf9}.pagination{display:flex;justify-content:center;align-items:center;gap:12px;margin-top:10px;font-size:9px}.pagination button{border:1px solid var(--line);background:white;border-radius:7px;padding:6px 10px}.issue-modal{max-width:680px}.form-grid .full{grid-column:1/-1}@media(max-width:800px){.db-summary{grid-template-columns:1fr 1fr}.db-workspace{grid-template-columns:1fr}.table-sidebar{border-right:0;border-bottom:1px solid var(--line);max-height:180px}.preview-toolbar{align-items:flex-start;flex-direction:column}.preview-toolbar form{width:100%}}
.schema-details{margin:0 0 10px;background:#f7faf9;border:1px solid var(--line);border-radius:8px;padding:8px;font-size:9px}.schema-details summary{cursor:pointer;font-weight:700;color:#315f59}.schema-details>div{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.schema-details span{padding:5px 7px;background:white;border:1px solid #dfebe8;border-radius:6px}.schema-details span.redacted{background:#fff4ec;color:#8a4b31}.schema-details span.revealable{border-color:#e4bd7b}.schema-details small{color:var(--muted)}
.table-display-name{font-family:inherit;font-size:11px;font-weight:700;line-height:1.4;color:#183f3a}.table-technical-name{font-family:inherit;font-size:8px;line-height:1.35;color:#6b7f7a;letter-spacing:.01em}.table-description{margin:3px 0;font-size:9px;color:#496963}
.issue-dashboard{display:grid;grid-template-columns:repeat(3,minmax(110px,1fr)) minmax(220px,1.6fr);gap:9px;margin-bottom:14px}.issue-dashboard article{border:1px solid #dfeae7;border-radius:12px;padding:12px;background:linear-gradient(145deg,#fff,#f5faf8)}.issue-dashboard small,.issue-dashboard span{display:block;font-size:8px;color:var(--muted)}.issue-dashboard strong{display:block;font-size:21px;color:#194f49;margin:3px 0}.issue-dashboard .overall-progress{display:flex;flex-direction:column;justify-content:center}.overall-progress>div:first-child{display:flex;align-items:center;justify-content:space-between}.overall-progress>div:first-child strong{font-size:16px}.progress-track{height:7px;border-radius:99px;background:#e4eeeb;overflow:hidden}.progress-track i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#de9b40,#5aa095);transition:width .3s}.progress-track i.complete{background:#45a875}.overall-progress .overdue{color:#b44934}.issue-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.issue-heading>b{font-size:15px;color:#276b62}.issue-card>.progress-track{margin:10px 0 12px}.issue-dates{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.issue-dates span{font-size:8px;color:var(--muted);padding:7px 8px;border-radius:7px;background:#f5f8f7}.issue-dates strong{display:block;margin:3px 0 0;font-size:8px;color:#294f4a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.issue-modal input[type="range"]{padding:0;accent-color:#2d766d}@media(max-width:900px){.issue-dashboard{grid-template-columns:1fr 1fr}.issue-dates{grid-template-columns:1fr 1fr}}
.preview-actions{display:flex;align-items:center;gap:7px}.preview-actions form{width:300px}.table-protection{margin:0 0 10px;padding:9px 11px;border-radius:8px;background:#fff7e8;color:#795d2f;font-size:9px}.row-actions-head{position:sticky!important;right:0;z-index:2}.row-actions{position:sticky;right:0;background:#fff!important;display:flex;gap:5px}.table-scroll tr:nth-child(even) .row-actions{background:#f8faf9!important}.row-actions button{border:1px solid #bad2cd;background:#fff;color:#24645c;border-radius:6px;padding:5px 8px;font-size:8px}.row-actions button.danger{border-color:#efc4ba;color:#a33d2c}.row-editor-modal{max-width:820px}.row-editor-note{margin:0;padding:10px 20px;background:#eef7f5;color:#466d66;font-size:9px}.row-editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:18px 20px;max-height:60vh;overflow:auto}.row-editor-grid label{display:flex;flex-direction:column;gap:4px;font-size:9px}.row-editor-grid label.wide{grid-column:1/-1}.row-editor-grid label>span{font-weight:700;color:#244a45}.row-editor-grid label>span b{color:#b44934}.row-editor-grid small{color:var(--muted);font-size:8px}.row-editor-grid input,.row-editor-grid select,.row-editor-grid textarea{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff;color:inherit;font:inherit}.row-editor-grid textarea{resize:vertical;line-height:1.5}@media(max-width:800px){.preview-actions{align-items:stretch;flex-direction:column;width:100%}.preview-actions form{width:100%}.row-editor-grid{grid-template-columns:1fr}.row-editor-grid label.wide{grid-column:auto}}
.privacy-note.revealed{background:#fff4df;color:#7b5319;border:1px solid #ebc884}.privacy-button{border-color:#d79b38;background:#fff8ea;color:#7a4f0b}.privacy-button.active{background:#7a4f0b;color:#fff}.privacy-modal{max-width:560px}.privacy-form{padding:18px 20px}.privacy-form p{margin:0 0 14px;padding:11px;border-radius:8px;background:#fff7e8;color:#72562d;font-size:9px;line-height:1.7}.privacy-form label{display:block;font-size:9px;color:#45625d}.privacy-form textarea{width:100%;box-sizing:border-box;margin-top:6px;border:1px solid #d8e3e0;border-radius:8px;padding:10px;resize:vertical;font:inherit}.privacy-form small{display:block;margin-top:4px;text-align:right;color:var(--muted)}
</style>
