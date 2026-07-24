<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  privacyApi,
  type AnonymizationField,
  type ResumeAnonymizationResult,
} from '../services/privacyApi'

const plainText = ref('')
const additionalNamesText = ref('')
const additionalAddressesText = ref('')
const result = ref<ResumeAnonymizationResult | null>(null)
const processing = ref(false)
const error = ref('')
const copied = ref(false)

const fieldLabels: Record<AnonymizationField, string> = {
  name: '姓名',
  address: '地址',
  phone: '電話',
  email: 'Email',
  birth_date: '出生日期',
  national_id: '身分證字號',
  personal_url: '個人連結',
}
const detectedFields = computed(() => {
  const counts = result.value?.summary.field_counts || {}
  return Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .map(([field, count]) => ({
      field,
      label: fieldLabels[field as AnonymizationField] || field,
      count: Number(count),
    }))
})

function entries(value: string) {
  return [...new Set(value.split(/[\n,，、]/).map(item => item.trim()).filter(Boolean))]
}

async function anonymize() {
  if (!plainText.value.trim()) {
    error.value = '請先貼上要去識別化的履歷文字'
    return
  }
  processing.value = true
  error.value = ''
  copied.value = false
  try {
    const additionalNames = entries(additionalNamesText.value)
    const additionalAddresses = entries(additionalAddressesText.value)
    if (additionalNames.length > 20 || additionalAddresses.length > 20) {
      error.value = '補充姓名與補充地址各最多 20 筆'
      return
    }
    result.value = (await privacyApi.anonymizeResume({
      plain_text: plainText.value,
      additional_names: additionalNames,
      additional_addresses: additionalAddresses,
    })).data
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '履歷去識別化失敗'
  } finally {
    processing.value = false
  }
}

async function copyResult() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.anonymized_text)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 2200)
  } catch {
    error.value = '瀏覽器無法自動複製，請在結果欄位中手動選取文字'
  }
}

function downloadResult() {
  if (!result.value) return
  const file = new Blob([result.value.anonymized_text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(file)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `resume-anonymized-${result.value.operation_id}.txt`
  anchor.click()
  URL.revokeObjectURL(url)
}

function reset() {
  if ((plainText.value || result.value) && !window.confirm('確定清除目前的原文與去識別化結果？')) return
  plainText.value = ''
  additionalNamesText.value = ''
  additionalAddressesText.value = ''
  result.value = null
  error.value = ''
  copied.value = false
}
</script>

<template>
  <section class="anonymization-page" data-testid="resume-anonymization">
    <header class="anonymization-hero">
      <div>
        <p>PRIVACY WORKSPACE</p>
        <h1>履歷去識別化</h1>
        <span>先移除姓名、地址與聯絡資訊，再將內容提供給面試官或跨部門評估。</span>
      </div>
      <div class="isolation-badge"><strong>獨立工具</strong><small>不匯入人才庫</small></div>
    </header>

    <div class="privacy-boundary panel" role="note">
      <span aria-hidden="true">盾</span>
      <div><strong>與履歷匯入、人才建檔完全分開</strong><p>這裡只處理你貼上的文字；系統不建立人才、不建立應徵紀錄，也不保存可回看的履歷原文。請先自行將 PDF／Word 內容複製為文字。</p></div>
    </div>

    <div v-if="error" class="anonymization-alert" role="alert"><strong>!</strong><span>{{ error }}</span><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>

    <div class="anonymization-layout">
      <form class="panel anonymization-input" @submit.prevent="anonymize">
        <header><div><small>STEP 1</small><h2>貼上履歷文字</h2><p>完成後可直接複製或下載去識別化文字。</p></div><em>{{ plainText.length.toLocaleString() }} 字元</em></header>
        <label>
          履歷原文 *
          <textarea v-model="plainText" data-testid="anonymization-source" rows="18" maxlength="200000" placeholder="在此貼上履歷文字，例如：&#10;王小明&#10;台北市……&#10;example@email.com" required></textarea>
        </label>
        <details class="custom-identifiers">
          <summary>補充系統可能辨識不到的內容（選填）</summary>
          <div>
            <label>其他姓名（最多 20 筆）<textarea v-model="additionalNamesText" rows="3" placeholder="例如：英文姓名、曾用名；每行一筆"></textarea></label>
            <label>其他地址（最多 20 筆）<textarea v-model="additionalAddressesText" rows="3" placeholder="例如：通訊地址、非標準格式地址；每行一筆"></textarea></label>
          </div>
        </details>
        <footer><button class="button secondary" type="button" :disabled="processing" @click="reset">清除內容</button><button class="button primary" data-testid="anonymization-submit" :disabled="processing || !plainText.trim()">{{ processing ? '正在安全處理…' : '開始去識別化' }}</button></footer>
      </form>

      <section class="panel anonymization-output" aria-live="polite">
        <header><div><small>STEP 2</small><h2>檢查去識別化結果</h2><p>分享前仍應快速檢查一次內容與上下文。</p></div><span v-if="result" class="complete-badge">已完成</span></header>
        <template v-if="result">
          <div class="replacement-summary">
            <article><span>已替換</span><strong>{{ result.summary.total_replacements }}</strong><small>處個人識別資訊</small></article>
            <article><span>偵測類型</span><strong>{{ detectedFields.length }}</strong><small>種資料類別</small></article>
            <article><span>輸出字元</span><strong>{{ result.summary.output_characters.toLocaleString() }}</strong><small>原文 {{ result.summary.input_characters.toLocaleString() }}</small></article>
          </div>
          <ul v-if="detectedFields.length" class="detected-fields" aria-label="已處理的個資類型">
            <li v-for="item in detectedFields" :key="item.field"><span>{{ item.label }}</span><strong>{{ item.count }} 處</strong></li>
          </ul>
          <label>去識別化文字<textarea :value="result.anonymized_text" data-testid="anonymization-result" rows="17" readonly></textarea></label>
          <div class="operation-note"><span>作業編號 {{ result.operation_id }}</span><small>伺服器只保留處理摘要，不提供原文或結果回查。</small></div>
          <footer><button class="button secondary" type="button" @click="downloadResult">下載 .txt</button><button class="button primary" data-testid="anonymization-copy" type="button" @click="copyResult">{{ copied ? '已複製' : '複製結果' }}</button></footer>
        </template>
        <div v-else class="output-placeholder">
          <span aria-hidden="true">✓</span><strong>結果會顯示在這裡</strong><p>系統會處理姓名、地址、電話、Email、出生日期、身分證字號與個人連結，並列出各類替換數量。</p>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.anonymization-page{display:grid;gap:15px}.anonymization-hero{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:27px 30px;border-radius:20px;background:linear-gradient(120deg,#18384d,#215f67 58%,#6f9f92);color:#fff;box-shadow:0 17px 40px rgba(24,70,76,.14)}.anonymization-hero p{margin:0;color:#f5ca77;font-size:9px;font-weight:800;letter-spacing:1.3px}.anonymization-hero h1{margin:7px 0;font-size:25px}.anonymization-hero span{font-size:13px;color:rgba(255,255,255,.82)}.isolation-badge{min-width:150px;padding:14px 18px;border:1px solid rgba(255,255,255,.3);border-radius:14px;background:rgba(255,255,255,.1);text-align:center}.isolation-badge strong,.isolation-badge small{display:block}.isolation-badge strong{font-size:14px}.isolation-badge small{margin-top:4px;color:rgba(255,255,255,.72);font-size:12px}.privacy-boundary{display:flex;align-items:flex-start;gap:13px;padding:15px 17px;border-color:#cce2dc;background:#f1faf7}.privacy-boundary>span{width:38px;height:38px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#d6eee7;color:#17685e;font-size:12px;font-weight:800}.privacy-boundary strong{font-size:14px;color:#245c54}.privacy-boundary p{margin:4px 0 0;color:#58716b;font-size:12px;line-height:1.65}.anonymization-alert{display:flex;align-items:center;gap:9px;padding:12px 14px;border:1px solid #efd0cd;border-radius:10px;background:#fff0ef;color:#893d39;font-size:13px}.anonymization-alert strong{width:23px;height:23px;display:grid;place-items:center;border-radius:50%;background:#e5b0ac}.anonymization-alert span{flex:1}.anonymization-alert button{border:0;background:transparent;color:inherit;font-size:18px}.anonymization-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:15px;align-items:start}.anonymization-input,.anonymization-output{overflow:hidden}.anonymization-input>header,.anonymization-output>header{display:flex;align-items:flex-start;justify-content:space-between;gap:15px;padding:18px 20px;border-bottom:1px solid var(--line);background:#fbfdfc}.anonymization-input header small,.anonymization-output header small{color:#b07820;font-size:11px;font-weight:800;letter-spacing:1px}.anonymization-input h2,.anonymization-output h2{margin:4px 0 0;font-size:17px}.anonymization-input header p,.anonymization-output header p{margin:4px 0 0;color:var(--muted);font-size:12px}.anonymization-input header em{padding:6px 9px;border-radius:99px;background:#eef4f2;color:#5f746f;font-size:12px;font-style:normal}.anonymization-input>label,.anonymization-output>label{display:grid;gap:7px;padding:17px 20px 0;color:#4f6a64;font-size:13px;font-weight:700}.anonymization-input textarea,.anonymization-output textarea,.custom-identifiers textarea{width:100%;padding:12px;border:1px solid #d3e1dd;border-radius:9px;background:#fff;color:#254640;font:13px/1.65 inherit;resize:vertical}.anonymization-input textarea:focus,.anonymization-output textarea:focus,.custom-identifiers textarea:focus{outline:3px solid rgba(27,123,110,.13);border-color:#56a899}.anonymization-output>label textarea{background:#f8fbfa}.custom-identifiers{margin:14px 20px 0;border:1px solid #dce7e3;border-radius:9px;background:#f9fbfa}.custom-identifiers summary{padding:11px 13px;cursor:pointer;color:#4c6d66;font-size:12px;font-weight:700}.custom-identifiers>div{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:0 12px 12px}.custom-identifiers label{display:grid;gap:5px;color:#627770;font-size:12px}.anonymization-input>footer,.anonymization-output>footer{display:flex;justify-content:flex-end;gap:8px;padding:15px 20px}.complete-badge{padding:6px 10px;border-radius:99px;background:#dff2e8;color:#267159;font-size:12px;font-weight:700}.replacement-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:15px 20px 0}.replacement-summary article{padding:11px;border-radius:9px;background:#f1f7f5}.replacement-summary span,.replacement-summary strong,.replacement-summary small{display:block}.replacement-summary span,.replacement-summary small{color:#687d77;font-size:11px}.replacement-summary strong{margin:3px 0;color:#1f7065;font-size:20px}.detected-fields{list-style:none;display:flex;flex-wrap:wrap;gap:7px;margin:12px 20px 0;padding:0}.detected-fields li{display:flex;gap:7px;padding:6px 9px;border:1px solid #d5e6e1;border-radius:99px;background:#f7fbfa;color:#496a63;font-size:11px}.detected-fields strong{color:#237468}.operation-note{display:flex;justify-content:space-between;gap:12px;margin:10px 20px 0;color:#738680;font-size:11px}.operation-note small{text-align:right}.output-placeholder{min-height:485px;display:grid;place-content:center;justify-items:center;padding:40px;text-align:center;color:#748681}.output-placeholder>span{width:50px;height:50px;display:grid;place-items:center;border-radius:50%;background:#e5f2ee;color:#277368;font-size:23px}.output-placeholder strong{margin-top:14px;color:#405f59;font-size:15px}.output-placeholder p{max-width:390px;margin:7px 0 0;font-size:12px;line-height:1.7}.anonymization-output>footer{border-top:1px solid var(--line);margin-top:15px}
@media(max-width:1050px){.anonymization-layout{grid-template-columns:1fr}.output-placeholder{min-height:280px}}@media(max-width:620px){.anonymization-hero{align-items:flex-start;flex-direction:column;padding:22px 19px}.isolation-badge{width:100%}.custom-identifiers>div,.replacement-summary{grid-template-columns:1fr}.operation-note{align-items:flex-start;flex-direction:column}.operation-note small{text-align:left}}
</style>
