<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { privacyApi, type TalentRetentionPurgeResult } from '../services/privacyApi'

const emit = defineEmits<{
  purged: []
  policyUpdated: []
  policyLoaded: [years: number]
}>()

const retentionYears = ref(2)
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const purging = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref<TalentRetentionPurgeResult | null>(null)
const lastRun = ref<TalentRetentionPurgeResult | null>(null)

async function loadPolicy() {
  loading.value = true
  error.value = ''
  try {
    retentionYears.value = (await privacyApi.retentionPolicy()).data.retention_years
    emit('policyLoaded', retentionYears.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法載入人才保存政策'
  } finally {
    loading.value = false
  }
}

async function savePolicy() {
  if (!Number.isInteger(retentionYears.value) || retentionYears.value < 1 || retentionYears.value > 20) {
    error.value = '保存年限必須是 1 到 20 的整數'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const updated = (await privacyApi.updateRetentionPolicy(retentionYears.value)).data
    retentionYears.value = updated.retention_years
    preview.value = null
    notice.value = `已將人才保存年限設為 ${retentionYears.value} 年，套用至 ${updated.applied_candidates} 筆人才`
    emit('policyLoaded', retentionYears.value)
    emit('policyUpdated')
    window.setTimeout(() => { notice.value = '' }, 2800)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法更新人才保存政策'
  } finally {
    saving.value = false
  }
}

function scrollToCandidates() {
  document.getElementById('candidate-retention-list')?.scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  })
}

async function previewPurge() {
  previewing.value = true
  error.value = ''
  lastRun.value = null
  try {
    const result = (await privacyApi.purgeExpiredTalent(true)).data
    if (!result.lock_acquired) {
      error.value = '另一個到期清理作業正在執行，請稍後再試'
      return
    }
    preview.value = result
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法預演到期清理'
  } finally {
    previewing.value = false
  }
}

async function purge() {
  if (!preview.value || preview.value.eligible_candidates <= 0) return
  const confirmed = window.confirm(
    `確定清除 ${preview.value.eligible_candidates} 筆已超過保存期限的人才？\n\n這會刪除人才資料、履歷檔案與照片，且無法復原。`,
  )
  if (!confirmed) return
  purging.value = true
  error.value = ''
  try {
    lastRun.value = (await privacyApi.purgeExpiredTalent(false)).data
    if (!lastRun.value.lock_acquired) {
      error.value = '另一個到期清理作業正在執行，本次沒有變更資料'
      lastRun.value = null
      return
    }
    preview.value = null
    notice.value = lastRun.value.remaining_candidates > 0
      ? `本批已清理 ${lastRun.value.deleted_candidates} 筆，仍有 ${lastRun.value.remaining_candidates} 筆待後續批次`
      : `已完成清理：刪除 ${lastRun.value.deleted_candidates} 筆到期人才`
    emit('purged')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法執行到期清理'
  } finally {
    purging.value = false
  }
}

onMounted(loadPolicy)
</script>

<template>
  <section class="retention-panel panel" data-testid="talent-retention-panel">
    <header>
      <div><p>DATA RETENTION</p><h2>保存期限設定</h2><span>先設定公司預設，再到每張人才卡指定 1～20 年；個別設定會優先於公司預設。</span></div>
      <span class="retention-state"><i></i>公司預設 {{ retentionYears }} 年</span>
    </header>

    <div v-if="error" class="retention-message error" role="alert"><strong>!</strong><span>{{ error }}</span><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
    <div v-if="notice" class="retention-message success" role="status"><strong>✓</strong><span>{{ notice }}</span></div>

    <div class="retention-body">
      <form class="retention-policy" @submit.prevent="savePolicy">
        <div><strong>① 公司預設保存年限</strong><p>沒有個別指定的人才會套用此年限；自同意日期起算，沒有同意日期時則從建檔日計算。</p></div>
        <label><input v-model.number="retentionYears" data-testid="retention-years" type="number" min="1" max="20" step="1" :disabled="loading || saving"><span>年</span></label>
        <button class="button secondary" data-testid="retention-save" :disabled="loading || saving">{{ saving ? '儲存中…' : '儲存公司預設' }}</button>
      </form>

      <div class="individual-retention-guide">
        <span class="individual-retention-example"><b>1 年</b><i>或</i><b>5 年</b></span>
        <div><strong>② 個別人才可另外指定</strong><p>在下方每張人才卡直接選擇年限，畫面會同時顯示「公司預設／個別設定」與實際到期日。</p></div>
        <button class="button primary" type="button" @click="scrollToCandidates">開始逐筆設定 ↓</button>
      </div>

      <div class="retention-cleanup">
        <div><strong>③ 到期資料清理</strong><p>預演只計算影響範圍，不會變更任何資料。確認筆數後才能真正清理。</p></div>
        <button class="button secondary" data-testid="retention-preview" type="button" :disabled="previewing || purging" @click="previewPurge">{{ previewing ? '檢查中…' : '預演到期清理' }}</button>
      </div>

      <div v-if="preview" class="purge-preview" role="status" data-testid="retention-preview-result">
        <div><small>預演日期</small><strong>{{ preview.as_of }}</strong></div>
        <div><small>已到期人才</small><strong>{{ preview.eligible_candidates }}</strong></div>
        <div><small>關聯履歷檔案</small><strong>{{ preview.eligible_resume_files }} 份</strong></div>
        <button class="button danger" data-testid="retention-purge" type="button" :disabled="purging || preview.eligible_candidates === 0" @click="purge">{{ purging ? '清理中…' : '確認並立即清理' }}</button>
      </div>

      <div v-if="lastRun" class="purge-result" data-testid="retention-purge-result">
        <strong>{{ lastRun.remaining_candidates > 0 ? '本批清理完成，仍有待清資料' : '到期資料清理完成' }}</strong>
        <span>人才 {{ lastRun.deleted_candidates }} 筆</span><span>履歷檔案 {{ lastRun.deleted_resume_files }} 份</span><span>照片 {{ lastRun.deleted_photos }} 張</span>
        <em v-if="lastRun.remaining_candidates" class="pending">仍有 {{ lastRun.remaining_candidates }} 筆人才待後續批次；請再次預演，或等待排程續清。</em>
        <em v-if="lastRun.queued_storage_deletions" class="pending">{{ lastRun.queued_storage_deletions }} 個檔案已排入背景刪除。</em>
        <em v-if="lastRun.storage_delete_failures">{{ lastRun.storage_delete_failures }} 個儲存檔案未能刪除，請交由系統管理員追蹤。</em>
      </div>
    </div>
  </section>
</template>

<style scoped>
.retention-panel{overflow:hidden;border-color:#d5e5e0}.retention-panel>header{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 20px;border-bottom:1px solid var(--line);background:linear-gradient(110deg,#f2faf7,#fffaf1)}.retention-panel header p{margin:0;color:#ad761f;font-size:11px;font-weight:800;letter-spacing:1px}.retention-panel h2{margin:3px 0;font-size:16px}.retention-panel header span:not(.retention-state){color:#61766f;font-size:12px}.retention-state{display:flex;align-items:center;gap:7px;padding:7px 10px;border-radius:99px;background:#e6f4ec;color:#296b55;font-size:12px;font-weight:700;white-space:nowrap}.retention-state i{width:7px;height:7px;border-radius:50%;background:#36a173}.retention-message{display:flex;align-items:center;gap:8px;margin:12px 18px 0;padding:10px 12px;border:1px solid;border-radius:8px;font-size:12px}.retention-message strong{width:21px;height:21px;display:grid;place-items:center;border-radius:50%}.retention-message span{flex:1}.retention-message button{border:0;background:transparent;color:inherit;font-size:18px}.retention-message.error{border-color:#eccbc8;background:#fff1f0;color:#8d3f3b}.retention-message.success{border-color:#c5dfcd;background:#eef8f1;color:#2b6747}.retention-body{display:grid;gap:0}.retention-policy,.retention-cleanup{display:flex;align-items:center;gap:14px;padding:15px 20px}.retention-policy{border-bottom:1px solid #e7efec}.retention-policy>div,.retention-cleanup>div{flex:1}.retention-policy strong,.retention-cleanup strong{font-size:13px}.retention-policy p,.retention-cleanup p{margin:3px 0 0;color:#687d77;font-size:12px;line-height:1.55}.retention-policy label{display:flex;align-items:center;overflow:hidden;border:1px solid #cdded9;border-radius:8px;background:#fff}.retention-policy input{width:76px;height:39px;border:0;padding:0 10px;color:#235a52;font-size:15px;font-weight:700;text-align:right}.retention-policy label span{padding-right:11px;color:#61766f;font-size:12px}.purge-preview{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) auto;align-items:center;gap:12px;margin:0 20px 16px;padding:13px 14px;border:1px solid #ead8b1;border-radius:10px;background:#fffaf0}.purge-preview small,.purge-preview strong{display:block}.purge-preview small{color:#7c735f;font-size:11px}.purge-preview strong{margin-top:3px;color:#73531f;font-size:14px}.purge-result{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 20px 16px;padding:12px 14px;border-radius:9px;background:#edf8f1;color:#346750;font-size:12px}.purge-result>strong{margin-right:auto}.purge-result span{padding:5px 7px;border-radius:6px;background:#fff}.purge-result em{flex-basis:100%;color:#9c4f47;font-style:normal}.purge-result em.pending{color:#865f24}
.individual-retention-guide{display:flex;align-items:center;gap:14px;padding:15px 20px;border-bottom:1px solid #e7efec;background:#f7fbfa}.individual-retention-guide>div{flex:1}.individual-retention-guide strong{font-size:13px}.individual-retention-guide p{margin:3px 0 0;color:#687d77;font-size:12px}.individual-retention-example{display:flex;align-items:center;gap:6px;padding:8px;border-radius:10px;background:#e7f3ef;color:#23685d}.individual-retention-example b{padding:5px 8px;border-radius:7px;background:#fff;font-size:12px}.individual-retention-example i{font-size:10px;font-style:normal;color:#708a84}
@media(max-width:760px){.retention-panel>header,.retention-policy,.retention-cleanup,.individual-retention-guide{align-items:flex-start;flex-direction:column}.retention-state{align-self:flex-start}.retention-policy label,.retention-policy .button,.retention-cleanup .button,.individual-retention-guide .button{width:100%}.retention-policy input{flex:1}.purge-preview{grid-template-columns:1fr 1fr}.purge-preview .button{grid-column:1/-1}}@media(max-width:460px){.purge-preview{grid-template-columns:1fr}}
</style>
