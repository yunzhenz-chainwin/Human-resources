<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { RequisitionDto } from '../services/hrApi'
import {
  matchingReportsApi,
  type CandidateMatchOverview,
  type CandidateMatchOverviewItem,
  type MatchDto,
  type MatchReadiness,
  type MatchStatus,
  type MatchingCriteria,
  type ScorePart,
} from '../services/matchingReportsApi'

const props = defineProps<{ jobs: RequisitionDto[]; canConfigure?: boolean }>()
const selectedJobId = ref<number | null>(null)
const overview = ref<CandidateMatchOverview | null>(null)
const readiness = ref<MatchReadiness | null>(null)
const loading = ref(false)
const recalculating = ref(false)
const error = ref('')
const criteria = ref<MatchingCriteria | null>(null)
const requiredSkillsText = ref('')
const preferredSkillsText = ref('')
const showCriteria = ref(false)
const savingCriteria = ref(false)
const minDisplayScore = ref(0)
const onlyPassed = ref(false)
const talentSearch = ref('')
let overviewRequestSequence = 0

const allPeople = computed(() => [...(overview.value?.items || [])].sort((a, b) => {
  if (!a.match && b.match) return 1
  if (a.match && !b.match) return -1
  if (a.match && b.match) return b.match.total_score - a.match.total_score
  return a.candidate.name.localeCompare(b.candidate.name, 'zh-Hant')
}))
const people = computed(() => allPeople.value.filter(item => {
  const score = item.match?.total_score ?? -1
  const keyword = talentSearch.value.trim().toLocaleLowerCase('zh-Hant')
  return (minDisplayScore.value === 0 || (!!item.match && score >= minDisplayScore.value))
    && (!onlyPassed.value || !!item.match?.gate_passed)
    && (!keyword || `${item.candidate.name} ${item.candidate.current_title || ''} ${item.candidate.code}`.toLocaleLowerCase('zh-Hant').includes(keyword))
}))
const selectedJob = computed(() => props.jobs.find(job => job.id === selectedJobId.value))
const componentLabels: Record<string, string> = {
  skill: '技能', relevance: '職務相關', years: '年資', salary: '薪資', education: '學歷', location: '地點',
}
const eligibleTotalCount = computed(() => allPeople.value.filter(item => item.match?.gate_passed).length)
const formulaParts = computed(() => {
  const sample = allPeople.value.find(item => item.match)?.match
  return Object.entries(componentLabels).map(([key, label]) => {
    const weight = Number(sample?.score_breakdown[key]?.weight)
    return { key, label, percent: Number.isFinite(weight) ? Math.round(weight * 100) : null }
  })
})
const statusLabels: Record<string, string> = {
  ineligible: '未通過必要條件', recommended: '建議人選', shortlisted: '入選名單', contacted: '已聯絡',
  interview: '面試中', offered: '已發 Offer', hired: '已錄取', rejected_by_manager: '主管婉拒', withdrawn: '已退出',
}
const editableStatuses: MatchStatus[] = ['recommended', 'shortlisted', 'contacted', 'interview', 'offered', 'hired', 'withdrawn']

watch(() => props.jobs, jobs => {
  if (jobs.length && !jobs.some(job => job.id === selectedJobId.value)) selectedJobId.value = jobs[0].id
}, { immediate: true })
watch(selectedJobId, () => loadOverview(), { immediate: true })

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '發生未預期錯誤'
}

async function loadOverview() {
  const requestId = ++overviewRequestSequence
  const jobId = selectedJobId.value
  if (!jobId) {
    overview.value = null
    readiness.value = null
    criteria.value = null
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  overview.value = null
  readiness.value = null
  criteria.value = null
  try {
    const [overviewResult, readinessResult, criteriaResult] = await Promise.all([
      matchingReportsApi.candidateOverview(jobId),
      matchingReportsApi.readiness(jobId),
      matchingReportsApi.matchingCriteria(jobId),
    ])
    if (requestId !== overviewRequestSequence || selectedJobId.value !== jobId) return
    overview.value = overviewResult
    readiness.value = readinessResult
    criteria.value = criteriaResult
    requiredSkillsText.value = criteriaResult.required_skills.join('、')
    preferredSkillsText.value = criteriaResult.preferred_skills.join('、')
  } catch (cause) {
    if (requestId === overviewRequestSequence) error.value = message(cause)
  } finally {
    if (requestId === overviewRequestSequence) loading.value = false
  }
}

function clearResultFilters() {
  talentSearch.value = ''
  minDisplayScore.value = 0
  onlyPassed.value = false
}

function skills(value: string) {
  return [...new Set(value.split(/[,，、\n]/).map(item => item.trim()).filter(Boolean))]
}

function nullableNumber(value: number | null | string) {
  return value === null || value === '' ? null : Number(value)
}

async function saveCriteria() {
  if (!props.canConfigure || !selectedJobId.value || !criteria.value) return
  savingCriteria.value = true
  error.value = ''
  try {
    const payload: MatchingCriteria = {
      ...criteria.value,
      required_skills: skills(requiredSkillsText.value),
      preferred_skills: skills(preferredSkillsText.value),
      min_years: nullableNumber(criteria.value.min_years),
      salary_min: nullableNumber(criteria.value.salary_min),
      salary_max: nullableNumber(criteria.value.salary_max),
      education_req: criteria.value.education_req?.trim() || null,
      work_city: criteria.value.work_city.trim(),
    }
    criteria.value = await matchingReportsApi.updateMatchingCriteria(selectedJobId.value, payload)
    await loadOverview()
    showCriteria.value = false
  } catch (cause) {
    error.value = message(cause)
  } finally {
    savingCriteria.value = false
  }
}

async function rematch() {
  if (!props.canConfigure || !selectedJobId.value) return
  recalculating.value = true
  error.value = ''
  try {
    await matchingReportsApi.rematch(selectedJobId.value)
    await loadOverview()
  } catch (cause) {
    error.value = message(cause)
  } finally {
    recalculating.value = false
  }
}

async function updateStatus(match: MatchDto | null, event: Event) {
  if (!match) return
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

async function reject(match: MatchDto | null) {
  if (!match) return
  const reason = window.prompt(`請輸入拒絕「${match.candidate.name}」的理由`)
  if (reason === null) return
  if (!reason.trim()) {
    error.value = '主管婉拒時必須填寫理由'
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

function values(items: unknown[] | undefined) {
  return (items || []).map(String).filter(Boolean).join('、')
}

function resultLabel(item: CandidateMatchOverviewItem) {
  if (!item.match) return '尚未計算'
  if (!item.match.gate_passed) return '未通過必要條件'
  return `排名 #${item.match.rank ?? '—'}`
}

const gateLabels: Record<string, string> = {
  required_skills: '缺少必要技能', minimum_years: '年資未達門檻', education: '學歷未達門檻',
  location: '期望工作地點不符', blacklisted: '人才已列入黑名單', consent_withdrawn: '人才已撤回同意',
  candidate_deleted: '人才已刪除',
}

function gateReasons(match: MatchDto) {
  const misses = (match.score_breakdown.gate?.miss || []) as unknown[]
  return misses.map(value => gateLabels[String(value)] || String(value)).join('、')
}
</script>

<template>
  <section class="matching-view">
    <header class="match-hero">
      <div><p>MATCHING EXPLAINABILITY</p><h1>職缺 × 每位人才媒合程度</h1><span>選擇一項職缺，即可逐人查看 0–100% 分數、未計算狀態，以及每一項評分依據。</span></div>
      <strong>逐人透明呈現<small>每一分都有依據</small></strong>
    </header>

    <div class="match-formula" aria-label="目前職缺的媒合權重">
      <article v-for="item in formulaParts" :key="item.key"><b>{{ item.percent === null ? '—' : `${item.percent}%` }}</b><span>{{ item.label }}</span></article>
    </div>

    <div class="gate-explainer panel">
      <div><strong>「必要條件」是什麼？</strong><span>HR 指定的硬性門檻，例如必要技能、最低年資、學歷與地點。未通過時仍顯示原始適配分數，並清楚標示缺少哪一項，不再全部變成 0.0%。</span></div>
      <button v-if="props.canConfigure" class="button secondary" @click="showCriteria = !showCriteria">{{ showCriteria ? '收合條件' : '設定 HR 媒合條件' }}</button>
    </div>

    <form v-if="props.canConfigure && showCriteria && criteria" class="criteria-panel panel" @submit.prevent="saveCriteria">
      <header><div><strong>HR 媒合條件</strong><span>儲存後系統會立即用新條件重新計算全部人才。</span></div></header>
      <div class="criteria-grid">
        <label class="wide">必要技能（逗號分隔）<input v-model="requiredSkillsText" placeholder="例如：Python、SQL"><small>少一項即標示為未通過；仍保留參考分數。</small></label>
        <label class="wide">加分技能（逗號分隔）<input v-model="preferredSkillsText" placeholder="例如：FastAPI、Git"></label>
        <label>最低年資<input v-model.number="criteria.min_years" type="number" min="0" max="80" step="0.5"></label>
        <label>最低學歷<input v-model="criteria.education_req" placeholder="例如：大學"></label>
        <label>工作地點<input v-model="criteria.work_city" required></label>
        <label>薪資下限<input v-model.number="criteria.salary_min" type="number" min="0"></label>
        <label>薪資上限<input v-model.number="criteria.salary_max" type="number" min="0"></label>
      </div>
      <div class="hard-gates">
        <label><input v-model="criteria.require_skills" type="checkbox">技能列為必要條件</label>
        <label><input v-model="criteria.require_years" type="checkbox">年資列為必要條件</label>
        <label><input v-model="criteria.require_education" type="checkbox">學歷列為必要條件</label>
        <label><input v-model="criteria.require_location" type="checkbox">地點列為必要條件</label>
      </div>
      <footer><button type="button" class="button secondary" @click="showCriteria = false">取消</button><button class="button primary" :disabled="savingCriteria">{{ savingCriteria ? '儲存並計算中…' : '儲存條件並重新媒合' }}</button></footer>
    </form>

    <div class="match-toolbar panel">
      <label>選擇職缺<select v-model="selectedJobId"><option :value="null" disabled>請選擇</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}</option></select></label>
      <span>{{ selectedJob ? `${selectedJob.work_city} · ${selectedJob.skills?.join('、') || '尚未設定技能'}` : '尚未選擇職缺' }}</span>
      <button v-if="props.canConfigure" class="button primary" :disabled="!selectedJobId || recalculating" @click="rematch">{{ recalculating ? '計算中…' : overview?.computed_count ? '重新計算全部人才' : '計算全部人才' }}</button>
    </div>
    <div class="result-filters panel">
      <label>搜尋人才<input v-model="talentSearch" placeholder="姓名、編號或職稱"></label>
      <label>最低媒合分數<select v-model.number="minDisplayScore"><option :value="0">不限</option><option :value="50">50% 以上</option><option :value="75">75% 以上</option><option :value="90">90% 以上</option></select></label>
      <label class="check"><input v-model="onlyPassed" type="checkbox">只顯示通過必要條件</label>
      <span>顯示 {{ people.length }} / {{ allPeople.length }} 人</span>
    </div>
    <div v-if="error" class="match-error">{{ error }}</div>

    <div v-if="overview" class="people-summary panel">
      <div><span>人才庫總數</span><strong>{{ overview.total_candidates }}</strong></div>
      <div><span>已計算</span><strong>{{ overview.computed_count }}</strong></div>
      <div><span>尚未計算</span><strong>{{ overview.uncomputed_count }}</strong></div>
      <div><span>通過必要條件（全數）</span><strong>{{ eligibleTotalCount }}</strong></div>
    </div>

    <div v-if="readiness && overview?.computed_count" class="readiness panel">
      <div><span>試行狀態</span><strong>{{ readiness.pilot_status === 'ready_for_weight_tuning' ? '可調整權重' : readiness.pilot_status === 'ready_for_shadow_pilot' ? '可進行影子試行' : '需要更多人才' }}</strong></div>
      <div><span>資料完整度</span><strong>{{ Math.round(readiness.metrics.data_completeness * 100) }}%</strong></div>
      <div><span>可媒合比例</span><strong>{{ Math.round(readiness.metrics.eligibility_rate * 100) }}%</strong></div>
      <div><span>人工回饋</span><strong>{{ readiness.metrics.labeled_outcomes }} 筆</strong></div>
    </div>

    <div v-if="loading" class="match-empty panel"><span class="spinner"></span><strong>讀取每位人才的媒合狀態…</strong></div>
    <div v-else-if="!jobs.length" class="match-empty panel"><strong>尚無職缺</strong><p>請先建立職缺並設定技能與條件。</p></div>
    <div v-else-if="overview && overview.total_candidates === 0" class="match-empty panel"><strong>人才庫目前沒有資料</strong><p>新增人才後，即可在這裡逐人計算媒合程度。</p></div>
    <div v-else-if="overview && !people.length" class="match-empty panel"><strong>沒有符合目前篩選條件的人才</strong><p>請降低最低分數、取消必要條件篩選，或更換搜尋字詞。</p><button class="button secondary" type="button" @click="clearResultFilters">清除篩選</button></div>
    <div v-else-if="overview" class="match-list">
      <article v-for="item in people" :key="item.candidate.id" class="panel match-card" :class="{ pending: !item.match }">
        <header>
          <div class="candidate"><span>{{ item.candidate.name.slice(0, 1) }}</span><div><h2>{{ item.candidate.name }}</h2><p>{{ item.candidate.code }} · {{ item.candidate.current_title || '尚未填寫職稱' }} · {{ item.candidate.total_years ?? '—' }} 年</p></div></div>
          <div v-if="item.match" class="score" :class="{ failed: !item.match.gate_passed }"><strong>{{ item.match.total_score.toFixed(1) }}<b>%</b></strong><small>{{ resultLabel(item) }}</small></div>
          <div v-else class="score uncomputed"><strong>—</strong><small>尚未計算</small></div>
        </header>

        <div v-if="item.match" class="score-grid">
          <div v-for="(label, key) in componentLabels" :key="key">
            <span><b>{{ label }}</b><em>{{ Math.round((part(item.match, key).score || 0) * 100) }}%</em></span>
            <i><u :style="{ width: `${Math.round((part(item.match, key).score || 0) * 100)}%` }"></u></i>
            <small v-if="part(item.match, key).hit?.length" class="hit">命中：{{ values(part(item.match, key).hit) }}</small>
            <small v-if="part(item.match, key).miss?.length" class="miss">缺口：{{ values(part(item.match, key).miss) }}</small>
          </div>
        </div>
        <div v-if="item.match && !item.match.gate_passed" class="gate-warning"><strong>參考分數 {{ item.match.total_score.toFixed(1) }}%，但未通過必要條件</strong><span>{{ gateReasons(item.match) }}</span></div>
        <div v-else-if="!item.match" class="pending-message"><b>等待第一次計算</b><span>按上方「計算全部人才」後，這裡會顯示百分比與技能、年資、薪資、學歷、地點等評分依據。</span></div>

        <div v-if="item.match?.feedback_reason" class="feedback"><strong>主管婉拒理由</strong>{{ item.match.feedback_reason }}</div>
        <footer>
          <div><strong>{{ item.candidate.email || '未填寫 Email' }}</strong><small>{{ item.candidate.phone || '未填寫聯絡電話' }}</small></div>
          <template v-if="item.match">
            <select :value="item.match.status" :disabled="item.match.status === 'rejected_by_manager'" @change="updateStatus(item.match, $event)">
              <option v-if="item.match.status === 'ineligible'" value="ineligible" disabled>未通過必要條件</option>
              <option v-for="status in editableStatuses" :key="status" :value="status">{{ statusLabels[status] }}</option>
              <option v-if="item.match.status === 'rejected_by_manager'" value="rejected_by_manager">主管婉拒</option>
            </select>
            <button class="button danger" :disabled="item.match.status === 'rejected_by_manager'" @click="reject(item.match)">主管婉拒</button>
          </template>
          <span v-else class="pending-badge">未計算</span>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.match-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:12px;padding:27px 30px;border-radius:20px;background:linear-gradient(120deg,#102f47,#146b71 58%,#52a98f);color:#fff;box-shadow:0 17px 40px rgba(20,74,75,.14)}.match-hero p{margin:0;color:#f5ca77;font-size:8px;font-weight:800;letter-spacing:1.3px}.match-hero h1{margin:7px 0;font-size:25px}.match-hero span{font-size:9px;color:rgba(255,255,255,.72)}.match-hero>strong{flex:0 0 auto;padding:14px 17px;border:1px solid rgba(255,255,255,.28);border-radius:14px;background:rgba(255,255,255,.1);font-size:12px}.match-hero>strong small{display:block;margin-top:4px;color:rgba(255,255,255,.65);font-size:8px}
.match-formula{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:13px}.match-formula article{display:flex;align-items:center;gap:8px;padding:11px;border:1px solid #deebe7;border-radius:11px;background:#fff}.match-formula b{color:#16776b;font-size:13px}.match-formula span{color:#72847f;font-size:8px}
.gate-explainer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 17px;margin-bottom:13px;border-color:#ecd9ac;background:#fffaf0}.gate-explainer div{display:flex;flex-direction:column;gap:4px}.gate-explainer strong{font-size:11px;color:#705120}.gate-explainer span{font-size:9px;color:#806e4f;line-height:1.6}.criteria-panel{padding:18px;margin-bottom:14px;border-color:#cde2dc}.criteria-panel header strong,.criteria-panel header span{display:block}.criteria-panel header strong{font-size:14px}.criteria-panel header span{font-size:9px;color:#71827d;margin-top:4px}.criteria-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}.criteria-grid .wide{grid-column:span 3}.criteria-grid label{font-size:9px;color:#61736e}.criteria-grid input{display:block;width:100%;height:38px;margin-top:5px;border:1px solid #d7e3df;border-radius:8px;padding:0 10px}.criteria-grid small{display:block;margin-top:4px;color:#9a6c3f}.hard-gates{display:flex;flex-wrap:wrap;gap:17px;margin:15px 0;padding:12px;border-radius:9px;background:#f2f8f6}.hard-gates label{font-size:9px;color:#365f58}.hard-gates input{margin-right:5px}.criteria-panel footer{display:flex;justify-content:flex-end;gap:8px}.result-filters{display:flex;align-items:end;gap:12px;padding:12px 14px;margin-bottom:14px}.result-filters label{font-size:8px;color:#657872}.result-filters input:not([type=checkbox]),.result-filters select{display:block;height:36px;margin-top:4px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 9px}.result-filters .check{display:flex;align-items:center;gap:5px;height:36px}.result-filters>span{margin-left:auto;font-size:9px;color:#54736d}
.match-toolbar{display:flex;align-items:end;gap:14px;padding:14px;margin-bottom:14px}.match-toolbar label{font-size:9px;color:#627570}.match-toolbar select{display:block;margin-top:5px;height:38px;min-width:310px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 10px}.match-toolbar>span{flex:1;color:#758581;font-size:9px}.match-error{padding:11px 14px;background:#fff0ef;color:#943f3a;border-radius:8px;margin-bottom:12px;font-size:10px}
.people-summary,.readiness{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:14px;margin-bottom:14px}.people-summary{background:#eef8f4;border-color:#d5e9e2}.readiness{background:#fffaf1;border-color:#eadfc8}.people-summary div,.readiness div{padding:8px 10px;border-right:1px solid #d9e9e3}.people-summary div:last-child,.readiness div:last-child{border:0}.people-summary span,.people-summary strong,.readiness span,.readiness strong{display:block}.people-summary span,.readiness span{font-size:8px;color:#71827d}.people-summary strong,.readiness strong{font-size:15px;margin-top:3px;color:#276d64}
.match-empty{text-align:center;padding:70px 20px}.match-empty strong,.match-empty p{display:block;font-size:12px}.match-empty p{font-size:9px;color:#758581}.match-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.match-card{padding:18px}.match-card.pending{border-style:dashed;background:linear-gradient(145deg,#fff,#fbfcfc)}.match-card header{display:flex;justify-content:space-between;align-items:center}.candidate{display:flex;align-items:center;gap:11px}.candidate>span{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:#dfeeea;color:#286e66;font-weight:700}.candidate h2{font-size:14px;margin:0}.candidate p{font-size:8px;color:#7d8d89;margin:4px 0}.score{text-align:right;color:#216b63}.score.failed{color:#a55049}.score.uncomputed{color:#98a6a2}.score strong,.score small{display:block}.score strong{font-size:27px}.score strong b{font-size:12px;margin-left:2px}.score small{font-size:8px}
.score-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:18px 0}.score-grid>div{background:#f7f9f8;border-radius:8px;padding:10px}.score-grid span{display:flex;justify-content:space-between;font-size:9px}.score-grid em{font-style:normal;color:#47726b}.score-grid i{display:block;height:4px;background:#dfe8e5;border-radius:4px;margin:7px 0}.score-grid u{display:block;height:100%;background:#3e8c80;border-radius:4px;text-decoration:none}.score-grid small{display:block;font-size:7px;line-height:1.5}.hit{color:#39806b}.miss{color:#a65a52}.pending-message{margin:18px 0;padding:18px;border-radius:10px;background:#f4f7f6;text-align:center;color:#768783}.pending-message b,.pending-message span{display:block}.pending-message b{font-size:11px;color:#566c66}.pending-message span{margin-top:6px;font-size:8px;line-height:1.6}.feedback{padding:9px;background:#fff3e9;color:#855b37;border-radius:7px;font-size:9px;margin-bottom:12px}.feedback strong{display:block;margin-bottom:3px}
.gate-warning{margin:-4px 0 14px;padding:10px 12px;border-left:3px solid #d68850;background:#fff5ec;color:#8a5135;border-radius:7px}.gate-warning strong,.gate-warning span{display:block;font-size:9px}.gate-warning span{margin-top:3px;font-size:8px}
.match-card footer{border-top:1px solid #edf1f0;padding-top:12px;display:flex;align-items:center;gap:8px}.match-card footer>div{flex:1}.match-card footer strong,.match-card footer small{display:block;font-size:9px}.match-card footer small{font-size:8px;color:#81908d;margin-top:3px}.match-card footer select{height:37px;border:1px solid #dce5e2;border-radius:8px;background:#fff;font-size:9px;padding:0 8px}.pending-badge{padding:7px 11px;border-radius:99px;background:#edf1f0;color:#6d7c78;font-size:8px}
@media(max-width:1050px){.match-list{grid-template-columns:1fr}.match-toolbar,.result-filters{align-items:stretch;flex-direction:column}.match-toolbar select{width:100%;min-width:0}.result-filters>span{margin-left:0}.people-summary,.readiness{grid-template-columns:1fr 1fr}.match-formula{grid-template-columns:repeat(3,1fr)}.criteria-grid{grid-template-columns:1fr 1fr}.criteria-grid .wide{grid-column:span 2}}@media(max-width:650px){.match-hero,.gate-explainer{align-items:flex-start;flex-direction:column;padding:22px 19px}.match-formula{grid-template-columns:repeat(2,1fr)}.criteria-grid{grid-template-columns:1fr}.criteria-grid .wide{grid-column:span 1}}
</style>
