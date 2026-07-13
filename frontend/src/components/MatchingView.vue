<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { RequisitionDto } from '../services/hrApi'
import {
  matchingReportsApi,
  type MatchDto,
  type MatchStatus,
  type ScorePart,
} from '../services/matchingReportsApi'

const props = defineProps<{ jobs: RequisitionDto[] }>()
const selectedJobId = ref<number | null>(null)
const matches = ref<MatchDto[]>([])
const loading = ref(false)
const recalculating = ref(false)
const includeIneligible = ref(true)
const error = ref('')

const sortedMatches = computed(() => [...matches.value].sort((a, b) =>
  b.total_score - a.total_score || (a.rank ?? 999999) - (b.rank ?? 999999),
))
const selectedJob = computed(() => props.jobs.find(job => job.id === selectedJobId.value))
const componentLabels: Record<string, string> = {
  skill: '技能', relevance: '職務相關', years: '年資', salary: '薪資', education: '學歷', location: '地點',
}
const statusLabels: Record<string, string> = {
  ineligible: '未通過門檻', recommended: '推薦', shortlisted: '入選', contacted: '已聯繫',
  interview: '面試', offered: '已發 Offer', hired: '已錄取', rejected_by_manager: '主管拒絕', withdrawn: '退出',
}
const editableStatuses: MatchStatus[] = ['recommended', 'shortlisted', 'contacted', 'interview', 'offered', 'hired', 'withdrawn']

watch(() => props.jobs, jobs => {
  if (!selectedJobId.value && jobs.length) selectedJobId.value = jobs[0].id
}, { immediate: true })
watch([selectedJobId, includeIneligible], () => loadMatches())

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '操作失敗'
}

async function loadMatches() {
  if (!selectedJobId.value) {
    matches.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    matches.value = (await matchingReportsApi.matches(selectedJobId.value, includeIneligible.value)).items
  } catch (cause) {
    error.value = message(cause)
  } finally {
    loading.value = false
  }
}

async function rematch() {
  if (!selectedJobId.value) return
  recalculating.value = true
  error.value = ''
  try {
    await matchingReportsApi.rematch(selectedJobId.value)
    await loadMatches()
  } catch (cause) {
    error.value = message(cause)
  } finally {
    recalculating.value = false
  }
}

async function updateStatus(match: MatchDto, event: Event) {
  const previous = match.status
  const next = (event.target as HTMLSelectElement).value as MatchStatus
  match.status = next
  try {
    Object.assign(match, await matchingReportsApi.updateMatchStatus(match.id, next))
  } catch (cause) {
    match.status = previous
    error.value = message(cause)
  }
}

async function reject(match: MatchDto) {
  const reason = window.prompt(`請輸入拒絕「${match.candidate.name}」的理由`)
  if (reason === null) return
  if (!reason.trim()) {
    error.value = '主管拒絕必須填寫理由'
    return
  }
  try {
    Object.assign(match, await matchingReportsApi.rejectMatch(match.id, reason.trim()))
  } catch (cause) {
    error.value = message(cause)
  }
}

function part(match: MatchDto, key: string): ScorePart {
  return match.score_breakdown[key] || {}
}

function values(values: unknown[] | undefined) {
  return (values || []).map(String).filter(Boolean).join('、')
}
</script>

<template>
  <section class="matching-view">
    <div class="page-heading"><div><h1>智慧配對</h1><p>依職缺條件即時計算，結果與主管回饋皆保存於資料庫。</p></div></div>
    <div class="match-toolbar panel">
      <label>選擇職缺<select v-model="selectedJobId"><option :value="null" disabled>請選擇</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}</option></select></label>
      <label class="check"><input v-model="includeIneligible" type="checkbox"> 顯示未通過門檻</label>
      <span>{{ selectedJob ? `${selectedJob.work_city} · ${selectedJob.skills?.join('、') || '未設定技能'}` : '尚無職缺' }}</span>
      <button class="button primary" :disabled="!selectedJobId || recalculating" @click="rematch">{{ recalculating ? '重新計算中…' : '重新計算配對' }}</button>
    </div>
    <div v-if="error" class="match-error">{{ error }}</div>
    <div v-if="loading" class="match-empty panel"><span class="spinner"></span><strong>讀取配對結果…</strong></div>
    <div v-else-if="!jobs.length" class="match-empty panel"><strong>尚無職缺</strong><p>請先建立職缺並設定技能與條件。</p></div>
    <div v-else-if="!sortedMatches.length" class="match-empty panel"><strong>尚無配對結果</strong><p>按下「重新計算配對」，系統會以資料庫人才進行評分。</p></div>
    <div v-else class="match-list">
      <article v-for="item in sortedMatches" :key="item.id" class="panel match-card">
        <header><div class="candidate"><span>{{ item.candidate.name.slice(0, 1) }}</span><div><h2>{{ item.candidate.name }}</h2><p>{{ item.candidate.code }} · {{ item.candidate.current_title || '未填職稱' }} · {{ item.candidate.total_years ?? '—' }} 年</p></div></div><div class="score" :class="{ failed: !item.gate_passed }"><strong>{{ item.total_score.toFixed(1) }}</strong><small>{{ item.gate_passed ? `排名 #${item.rank ?? '—'}` : '未通過門檻' }}</small></div></header>
        <div class="score-grid"><div v-for="(label, key) in componentLabels" :key="key"><span><b>{{ label }}</b><em>{{ Math.round((part(item, key).score || 0) * 100) }}%</em></span><i><u :style="{ width: `${Math.round((part(item, key).score || 0) * 100)}%` }"></u></i><small v-if="part(item, key).hit?.length" class="hit">命中：{{ values(part(item, key).hit) }}</small><small v-if="part(item, key).miss?.length" class="miss">缺口：{{ values(part(item, key).miss) }}</small></div></div>
        <div v-if="item.feedback_reason" class="feedback"><strong>主管拒絕理由</strong>{{ item.feedback_reason }}</div>
        <footer><div><strong>{{ item.candidate.email || '未提供 Email' }}</strong><small>{{ item.candidate.phone || '未提供電話' }}</small></div><select :value="item.status" :disabled="item.status === 'rejected_by_manager'" @change="updateStatus(item, $event)"><option v-if="item.status === 'ineligible'" value="ineligible" disabled>未通過門檻</option><option v-for="status in editableStatuses" :key="status" :value="status">{{ statusLabels[status] }}</option><option v-if="item.status === 'rejected_by_manager'" value="rejected_by_manager">主管拒絕</option></select><button class="button danger" :disabled="item.status === 'rejected_by_manager'" @click="reject(item)">主管拒絕</button></footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.match-toolbar{display:flex;align-items:end;gap:14px;padding:14px;margin-bottom:14px}.match-toolbar label{font-size:9px;color:#627570}.match-toolbar select{display:block;margin-top:5px;height:38px;min-width:280px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 10px}.match-toolbar .check{display:flex;align-items:center;gap:6px;height:38px}.match-toolbar .check input{margin:0}.match-toolbar>span{flex:1;color:#758581;font-size:9px}.match-error{padding:11px 14px;background:#fff0ef;color:#943f3a;border-radius:8px;margin-bottom:12px;font-size:10px}.match-empty{text-align:center;padding:70px 20px}.match-empty strong,.match-empty p{display:block;font-size:12px}.match-empty p{font-size:9px;color:#758581}.match-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.match-card{padding:18px}.match-card header{display:flex;justify-content:space-between;align-items:center}.candidate{display:flex;align-items:center;gap:11px}.candidate>span{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:#dfeeea;color:#286e66;font-weight:700}.candidate h2{font-size:14px;margin:0}.candidate p{font-size:8px;color:#7d8d89;margin:4px 0}.score{text-align:right;color:#216b63}.score.failed{color:#a55049}.score strong,.score small{display:block}.score strong{font-size:27px}.score small{font-size:8px}.score-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:18px 0}.score-grid>div{background:#f7f9f8;border-radius:8px;padding:10px}.score-grid span{display:flex;justify-content:space-between;font-size:9px}.score-grid em{font-style:normal;color:#47726b}.score-grid i{display:block;height:4px;background:#dfe8e5;border-radius:4px;margin:7px 0}.score-grid u{display:block;height:100%;background:#3e8c80;border-radius:4px;text-decoration:none}.score-grid small{display:block;font-size:7px;line-height:1.5}.hit{color:#39806b}.miss{color:#a65a52}.feedback{padding:9px;background:#fff3e9;color:#855b37;border-radius:7px;font-size:9px;margin-bottom:12px}.feedback strong{display:block;margin-bottom:3px}.match-card footer{border-top:1px solid #edf1f0;padding-top:12px;display:flex;align-items:center;gap:8px}.match-card footer>div{flex:1}.match-card footer strong,.match-card footer small{display:block;font-size:9px}.match-card footer small{font-size:8px;color:#81908d;margin-top:3px}.match-card footer select{height:37px;border:1px solid #dce5e2;border-radius:8px;background:#fff;font-size:9px;padding:0 8px}@media(max-width:1050px){.match-list{grid-template-columns:1fr}.match-toolbar{align-items:stretch;flex-direction:column}.match-toolbar select{width:100%;min-width:0}}
</style>
