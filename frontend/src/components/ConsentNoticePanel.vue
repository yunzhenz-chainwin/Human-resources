<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { consentApi, type ConsentNotice } from '../services/consentApi'
import { formatApiDateTime } from '../utils/dateTime'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const notices = ref<ConsentNotice[]>([])
const dialog = ref(false)
const form = reactive({ title: '', body: '', purpose_code: '', activate: true })

const activeNotice = computed(() => notices.value.find(item => item.is_active) || null)

function showNotice(message: string) {
  notice.value = message
  window.setTimeout(() => { if (notice.value === message) notice.value = '' }, 2500)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    notices.value = (await consentApi.notices()).data
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '告知同意條款載入失敗'
  } finally {
    loading.value = false
  }
}

function openDialog() {
  Object.assign(form, { title: '', body: '', purpose_code: '', activate: true })
  dialog.value = true
}

async function saveNotice() {
  if (!form.title.trim() || !form.body.trim()) {
    error.value = '標題與條款全文為必填'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await consentApi.createNotice({
      title: form.title.trim(),
      body: form.body.trim(),
      purpose_code: form.purpose_code.trim() || null,
      activate: form.activate,
    })
    dialog.value = false
    await load()
    showNotice(form.activate ? '新版本已建立並設為生效' : '新版本已建立')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '條款版本儲存失敗'
  } finally {
    saving.value = false
  }
}

async function activate(item: ConsentNotice) {
  if (item.is_active) return
  const confirmed = window.confirm(
    `確定將「${item.title}（v${item.version}）」設為目前生效版本？\n\n其餘版本將自動取消生效，之後記錄的候選人同意都會對應此版本。`,
  )
  if (!confirmed) return
  saving.value = true
  error.value = ''
  try {
    await consentApi.activateNotice(item.id)
    await load()
    showNotice(`已將 v${item.version} 設為生效版本`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法切換生效版本'
  } finally {
    saving.value = false
  }
}

function date(value: string | null) {
  if (!value) return '—'
  return formatApiDateTime(value, { dateStyle: 'short', timeStyle: 'short' })
}

onMounted(load)
</script>

<template>
  <div class="panel admin-section consent-panel">
    <header>
      <div>
        <h2>告知同意條款</h2>
        <p>維護版本化的招募告知／同意書（個資法 §8／§9）；候選人同意時會綁定目前生效版本。</p>
      </div>
      <div class="consent-actions">
        <button class="button secondary" :disabled="loading" @click="load">{{ loading ? '載入中…' : '重新整理' }}</button>
        <button class="button primary" @click="openDialog">＋ 建立新版本</button>
      </div>
    </header>

    <div v-if="error" class="alert error-alert" role="alert"><span>!</span><p>{{ error }}</p><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>

    <div class="active-banner" :data-empty="!activeNotice">
      <template v-if="activeNotice">
        <span>✓ 目前生效版本</span>
        <strong>v{{ activeNotice.version }}· {{ activeNotice.title }}</strong>
        <small>{{ activeNotice.purpose_code || '未填蒐集目的代碼' }} · 更新於 {{ date(activeNotice.updated_at) }}</small>
      </template>
      <template v-else>
        <span>⚠ 尚無生效版本</span>
        <small>建立版本並設為生效後，才能記錄候選人同意。</small>
      </template>
    </div>

    <div class="admin-table">
      <table>
        <thead><tr><th>版本</th><th>標題</th><th>蒐集目的</th><th>狀態</th><th>建立時間</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in notices" :key="item.id" :data-testid="`consent-notice-${item.id}`">
            <td><strong>v{{ item.version }}</strong></td>
            <td><strong>{{ item.title }}</strong><small class="body-preview">{{ item.body }}</small></td>
            <td>{{ item.purpose_code || '—' }}</td>
            <td><span class="status" :data-status="item.is_active ? 'approved' : 'archived'">{{ item.is_active ? '生效中' : '未生效' }}</span></td>
            <td>{{ date(item.created_at) }}</td>
            <td><button v-if="!item.is_active" class="text-button" :disabled="saving" @click="activate(item)">設為生效</button><span v-else class="muted-text">目前生效</span></td>
          </tr>
          <tr v-if="!notices.length && !loading"><td colspan="6" class="empty">尚未建立任何告知同意條款版本。</td></tr>
        </tbody>
      </table>
    </div>

    <p class="legal-hint">提醒：告知同意條款措辭涉及法律遵循，建議正式啟用前先經法務／律師覆核。</p>
  </div>

  <div v-if="dialog" class="modal-overlay" @click.self="dialog = false" @keydown.esc="dialog = false">
    <form class="modal-card compact-modal" role="dialog" aria-modal="true" aria-labelledby="consent-dialog-title" @submit.prevent="saveNotice">
      <header><div><small>CONSENT NOTICE</small><h2 id="consent-dialog-title">建立新版本</h2></div><button type="button" aria-label="關閉視窗" @click="dialog = false">×</button></header>
      <div class="form-grid">
        <label>標題 *<input v-model="form.title" data-testid="consent-title" required maxlength="200"></label>
        <label>蒐集目的代碼<input v-model="form.purpose_code" placeholder="例如 002 人事管理" maxlength="100"></label>
        <label class="full">條款全文 *<textarea v-model="form.body" data-testid="consent-body" rows="10" required></textarea></label>
        <label class="full inline"><input v-model="form.activate" class="inline-check" type="checkbox"> 建立後立即設為生效版本（其餘版本將自動取消生效）</label>
      </div>
      <footer><button type="button" class="button secondary" @click="dialog = false">取消</button><button class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存版本' }}</button></footer>
    </form>
  </div>
  <Transition name="toast"><div v-if="notice" class="toast" role="status" aria-live="polite"><span>✓</span>{{ notice }}</div></Transition>
</template>

<style scoped>
.consent-panel{display:grid;gap:0}
.consent-panel>header{padding:17px 19px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:15px}
.consent-panel h2{font-size:14px;margin:0}
.consent-panel header p{font-size:9px;color:var(--muted);margin:3px 0 0;max-width:560px;line-height:1.6}
.consent-actions{display:flex;gap:8px;white-space:nowrap}
.active-banner{margin:14px 18px 0;padding:13px 15px;border:1px solid #bfe0d7;border-radius:9px;background:#eef7f4;color:#1f655e;display:grid;gap:4px}
.active-banner[data-empty="true"]{border-color:#efd5a3;background:#fff8e8;color:#77531c}
.active-banner span{font-size:10px;font-weight:700}
.active-banner strong{font-size:12px}
.active-banner small{font-size:9px;color:var(--muted)}
.admin-table{overflow:auto;margin-top:12px}
.admin-table table{min-width:760px}
.body-preview{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:var(--muted);font-size:8px;margin-top:3px;max-width:320px}
.muted-text{color:var(--muted);font-size:9px}
.empty{text-align:center;color:var(--muted);padding:18px;font-size:10px}
.legal-hint{margin:12px 18px 16px;padding:10px 12px;border:1px dashed #d3c08a;border-radius:8px;background:#fffbf0;color:#7a5c1c;font-size:9px;line-height:1.6}
.form-grid label.full{grid-column:1 / -1}
.form-grid label.inline{display:flex;align-items:center;gap:6px;font-weight:600}
.form-grid textarea{width:100%;font:inherit;padding:10px 12px;border:1px solid #bdd8d1;border-radius:8px;background:#f6fbf9;resize:vertical}
.inline-check{display:inline-block!important;width:auto!important;height:auto!important;margin:0 5px 0 0!important}
</style>
