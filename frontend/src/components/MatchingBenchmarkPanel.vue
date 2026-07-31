<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { authSession } from '../services/auth'
import {
  matchingBenchmarkApi,
  type BenchmarkReason,
  type BenchmarkReport,
  type BenchmarkSuite,
  type BenchmarkVerdict,
  type BlindBenchmarkCase,
} from '../services/matchingBenchmarkApi'

type RatingDraft = {
  verdict: BenchmarkVerdict
  reasons: BenchmarkReason[]
  note: string
  priority_rank: number | null
}

const suites = ref<BenchmarkSuite[]>([])
const selectedSuiteKey = ref('')
const selectedJobKey = ref('all')
const cases = ref<BlindBenchmarkCase[]>([])
const report = ref<BenchmarkReport | null>(null)
const loading = ref(false)
const savingKey = ref('')
const revealing = ref(false)
const error = ref('')
const notice = ref('')
const drafts = reactive<Record<string, RatingDraft>>({})

const verdictOptions: Array<{ value: BenchmarkVerdict; label: string }> = [
  { value: 'interview', label: '適合面試' },
  { value: 'consider', label: '可考慮' },
  { value: 'reject', label: '不適合' },
  { value: 'insufficient_data', label: '資料不足' },
]
const reasonOptions: Array<{ value: BenchmarkReason; label: string }> = [
  { value: 'strong_evidence', label: '能力證據明確' },
  { value: 'transferable_experience', label: '具可轉移經驗' },
  { value: 'skill_gap', label: '技能有缺口' },
  { value: 'experience_gap', label: '年資不足' },
  { value: 'role_relevance', label: '職務關聯性' },
  { value: 'salary_mismatch', label: '薪資不符' },
  { value: 'location_mismatch', label: '地點不符' },
  { value: 'education_gap', label: '學歷條件' },
  { value: 'missing_information', label: '資訊不足' },
  { value: 'other', label: '其他' },
]
const metricLabels: Record<string, string> = {
  top5_overlap_hr: 'HR 前五名重疊率',
  top5_overlap_manager: '主管前五名重疊率',
  top5_false_negative_hr: 'HR 前五名漏選率',
  top5_false_negative_manager: '主管前五名漏選率',
  gate_miss_hr: 'HR 正向人選閘門錯失率',
  gate_miss_manager: '主管正向人選閘門錯失率',
  gate_miss_any_role: '任一角色正向的閘門錯失率',
  role_agreement: 'HR／主管一致率',
  data_completeness: '履歷資料完整度',
}

const selectedSuite = computed(() => suites.value.find(item => item.key === selectedSuiteKey.value))
const jobKeys = computed(() => [...new Set(cases.value.map(item => item.job_key))])
const visibleCases = computed(() => cases.value.filter(
  item => selectedJobKey.value === 'all' || item.job_key === selectedJobKey.value,
))
const canReveal = computed(() => authSession.state.user?.role === 'hr' && selectedSuite.value?.status === 'blind')

function initializeDrafts(items: BlindBenchmarkCase[]) {
  for (const item of items) {
    const rating = item.my_rating
    drafts[item.case_key] = {
      verdict: rating?.verdict || 'consider',
      reasons: rating?.reasons ? [...rating.reasons] : [],
      note: rating?.note || '',
      priority_rank: rating?.priority_rank ?? null,
    }
  }
}

async function loadSuites() {
  loading.value = true
  error.value = ''
  try {
    suites.value = await matchingBenchmarkApi.suites()
    if (!selectedSuiteKey.value && suites.value.length) selectedSuiteKey.value = suites.value[0].key
    if (selectedSuiteKey.value) await loadSuite()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法讀取媒合基準'
  } finally {
    loading.value = false
  }
}

async function loadSuite() {
  if (!selectedSuiteKey.value) return
  error.value = ''
  notice.value = ''
  const suite = suites.value.find(item => item.key === selectedSuiteKey.value)
  if (suite?.status === 'revealed') {
    report.value = await matchingBenchmarkApi.report(selectedSuiteKey.value)
    cases.value = []
    return
  }
  const payload = await matchingBenchmarkApi.cases(selectedSuiteKey.value)
  cases.value = payload.cases
  if (selectedJobKey.value === 'all' && payload.cases.length) {
    selectedJobKey.value = payload.cases[0].job_key
  }
  report.value = null
  initializeDrafts(payload.cases)
  const index = suites.value.findIndex(item => item.key === payload.suite.key)
  if (index >= 0) suites.value[index] = payload.suite
}

async function save(item: BlindBenchmarkCase) {
  const draft = drafts[item.case_key]
  if (!draft.reasons.length) {
    error.value = '請至少選擇一個判斷原因。'
    return
  }
  if (draft.verdict === 'insufficient_data' && !draft.reasons.includes('missing_information')) {
    error.value = '選擇「資料不足」時，原因必須包含「資訊不足」。'
    return
  }
  savingKey.value = item.case_key
  error.value = ''
  notice.value = ''
  try {
    item.my_rating = await matchingBenchmarkApi.saveRating(selectedSuiteKey.value, item.case_key, {
      verdict: draft.verdict,
      reasons: draft.reasons,
      note: draft.note || null,
      priority_rank: draft.priority_rank,
    })
    notice.value = `${item.case_key} 已儲存；畫面仍不會顯示系統分數。`
    const refreshed = await matchingBenchmarkApi.cases(selectedSuiteKey.value)
    const index = suites.value.findIndex(suite => suite.key === refreshed.suite.key)
    if (index >= 0) suites.value[index] = refreshed.suite
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '儲存評分失敗'
  } finally {
    savingKey.value = ''
  }
}

async function reveal() {
  if (!selectedSuiteKey.value || !canReveal.value) return
  revealing.value = true
  error.value = ''
  try {
    const suite = await matchingBenchmarkApi.reveal(selectedSuiteKey.value)
    const index = suites.value.findIndex(item => item.key === suite.key)
    if (index >= 0) suites.value[index] = suite
    report.value = await matchingBenchmarkApi.report(selectedSuiteKey.value)
    cases.value = []
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '揭盲失敗'
  } finally {
    revealing.value = false
  }
}

function formatSalary(minimum: number | null, maximum: number | null) {
  if (minimum === null && maximum === null) return '未提供'
  return `${minimum?.toLocaleString() || '—'}～${maximum?.toLocaleString() || '—'}`
}

function metricValue(value: number | null, unit: string) {
  if (value === null) return '未知'
  return unit === 'percent' ? `${value}%` : value.toFixed(1)
}

onMounted(loadSuites)
</script>

<template>
  <section class="benchmark-panel">
    <header class="hero">
      <div>
        <span class="eyebrow">SMALL-SAMPLE BENCHMARK</span>
        <h1>媒合盲評基準</h1>
        <p>HR 與主管先獨立判斷合成履歷；完成後才揭露系統分數，避免分數影響人工判斷。</p>
      </div>
      <div class="hero-actions">
        <select v-model="selectedSuiteKey" :disabled="loading" @change="loadSuite">
          <option v-for="suite in suites" :key="suite.key" :value="suite.key">{{ suite.title }}</option>
        </select>
        <button v-if="canReveal" class="primary" :disabled="revealing" @click="reveal">
          {{ revealing ? '揭盲中…' : '完成後揭盲' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="message error">{{ error }}</p>
    <p v-if="notice" class="message success">{{ notice }}</p>
    <p v-if="loading" class="empty">正在載入基準資料…</p>

    <template v-if="selectedSuite && selectedSuite.status === 'blind'">
      <div class="progress-grid">
        <article v-for="progress in selectedSuite.progress" :key="progress.role">
          <span>{{ progress.role === 'hr' ? 'HR' : '部門主管' }}</span>
          <strong>{{ progress.completed }}/{{ progress.total }}</strong>
          <small>{{ progress.complete_reviewer_count ? '已有人完成全數評分' : '尚未完成' }}</small>
        </article>
        <article class="blind-note">
          <span>目前階段</span>
          <strong>盲評中</strong>
          <small>系統分數、閘門與標準答案均隱藏</small>
        </article>
      </div>

      <nav class="job-filter">
        <button :class="{ active: selectedJobKey === 'all' }" @click="selectedJobKey = 'all'">全部</button>
        <button v-for="key in jobKeys" :key="key" :class="{ active: selectedJobKey === key }" @click="selectedJobKey = key">{{ key }}</button>
      </nav>

      <div class="case-list">
        <article v-for="item in visibleCases" :key="item.case_key" class="case-card">
          <header>
            <div><span>{{ item.case_key }}</span><h2>{{ item.job_profile.title }}</h2></div>
            <b :class="{ saved: item.my_rating }">{{ item.my_rating ? '已評分' : '待評分' }}</b>
          </header>
          <div class="comparison">
            <section>
              <h3>職缺條件</h3>
              <dl>
                <div><dt>必要技能</dt><dd>{{ item.job_profile.required_skills.join('、') }}</dd></div>
                <div><dt>加分技能</dt><dd>{{ item.job_profile.preferred_skills.join('、') }}</dd></div>
                <div><dt>年資／地點</dt><dd>{{ item.job_profile.min_years }} 年／{{ item.job_profile.work_city }}</dd></div>
                <div><dt>薪資</dt><dd>{{ formatSalary(item.job_profile.salary_min, item.job_profile.salary_max) }}</dd></div>
              </dl>
            </section>
            <section>
              <h3>合成履歷（無個資）</h3>
              <dl>
                <div><dt>目前職務</dt><dd>{{ item.candidate_profile.current_title || '未提供' }}</dd></div>
                <div><dt>技能</dt><dd>{{ item.candidate_profile.skills.join('、') || '未提供' }}</dd></div>
                <div><dt>年資／地點</dt><dd>{{ item.candidate_profile.total_years ?? '未提供' }} 年／{{ item.candidate_profile.expected_cities?.join('、') || '未提供' }}</dd></div>
                <div><dt>期望薪資</dt><dd>{{ formatSalary(item.candidate_profile.expected_salary_min, item.candidate_profile.expected_salary_max) }}</dd></div>
              </dl>
            </section>
          </div>
          <div class="rating-form">
            <label>人工判斷<select v-model="drafts[item.case_key].verdict"><option v-for="option in verdictOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label>優先序（選填）<input v-model.number="drafts[item.case_key].priority_rank" type="number" min="1" max="10" placeholder="1–10"></label>
            <fieldset><legend>判斷原因（至少一項）</legend><label v-for="reason in reasonOptions" :key="reason.value"><input v-model="drafts[item.case_key].reasons" type="checkbox" :value="reason.value">{{ reason.label }}</label></fieldset>
            <label class="note">補充說明（選填）<textarea v-model="drafts[item.case_key].note" rows="2" maxlength="1000"></textarea></label>
            <button class="primary" :disabled="savingKey === item.case_key" @click="save(item)">{{ savingKey === item.case_key ? '儲存中…' : '儲存這一題' }}</button>
          </div>
        </article>
      </div>
    </template>

    <template v-if="report">
      <div class="warning-list"><p v-for="warning in report.warnings" :key="warning">{{ warning }}</p></div>
      <div class="metric-grid">
        <article v-for="(metric, key) in report.metrics" :key="key">
          <span>{{ metricLabels[key] || key }}</span>
          <strong :class="{ unknown: metric.value === null }">{{ metricValue(metric.value, metric.unit) }}</strong>
          <small>{{ metric.explanation }}</small>
        </article>
      </div>
      <div class="result-table">
        <table>
          <thead><tr><th>案例</th><th>情境</th><th>系統分數</th><th>閘門</th><th>HR</th><th>主管</th><th>設計標籤</th></tr></thead>
          <tbody><tr v-for="item in report.cases" :key="item.case_key"><td>{{ item.case_key }}</td><td>{{ item.scenario }}</td><td>{{ item.system_score }}</td><td>{{ item.system_gate_passed ? '通過' : `未通過：${item.system_gate_misses.join('、')}` }}</td><td>{{ item.hr_verdict || '未知' }}</td><td>{{ item.manager_verdict || '未知' }}</td><td>{{ item.expected_verdict }}</td></tr></tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.benchmark-panel{display:flex;flex-direction:column;gap:16px}.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding:22px;border:1px solid #dce8e4;border-radius:16px;background:linear-gradient(135deg,#f4fbf8,#fffaf0)}.hero h1{margin:4px 0 6px;font-size:24px;color:#123f39}.hero p{margin:0;color:#607872;font-size:13px}.eyebrow{color:#18816f;font-size:10px;letter-spacing:.14em;font-weight:700}.hero-actions{display:flex;gap:8px}.hero select,.rating-form select,.rating-form input,.rating-form textarea{border:1px solid #cfded9;border-radius:8px;background:#fff;padding:9px;color:#294b45}.primary{border:0;border-radius:8px;background:#0e7d6c;color:#fff;padding:10px 15px;font-weight:700;cursor:pointer}.primary:disabled{opacity:.55;cursor:wait}.message{margin:0;padding:11px 14px;border-radius:9px;font-size:12px}.message.error{background:#fff0ef;color:#963d36}.message.success{background:#edf9f3;color:#27725e}.empty{text-align:center;color:#70827e;padding:30px}.progress-grid,.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.progress-grid article,.metric-grid article{padding:16px;border:1px solid #dce8e4;border-radius:12px;background:#fff}.progress-grid span,.progress-grid strong,.progress-grid small,.metric-grid span,.metric-grid strong,.metric-grid small{display:block}.progress-grid strong,.metric-grid strong{font-size:22px;margin:5px 0;color:#145c51}.progress-grid small,.metric-grid small{font-size:10px;color:#738681;line-height:1.45}.blind-note{background:#fffaf0!important}.job-filter{display:flex;gap:7px;flex-wrap:wrap}.job-filter button{border:1px solid #d7e4e0;border-radius:999px;background:#fff;padding:7px 13px;color:#46625c}.job-filter button.active{background:#185f54;color:#fff;border-color:#185f54}.case-list{display:flex;flex-direction:column;gap:14px}.case-card{border:1px solid #dce7e3;border-radius:14px;background:#fff;overflow:hidden}.case-card>header{display:flex;justify-content:space-between;align-items:center;padding:15px 18px;border-bottom:1px solid #edf2f0}.case-card header span{font-size:10px;color:#758984}.case-card h2{font-size:16px;margin:3px 0 0;color:#173f39}.case-card header b{font-size:10px;background:#f3f5f4;color:#788682;border-radius:999px;padding:6px 10px}.case-card header b.saved{background:#e6f5ef;color:#176853}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:16px 18px}.comparison section{background:#f8fbfa;border-radius:10px;padding:13px}.comparison h3{margin:0 0 9px;font-size:12px;color:#1c5e53}.comparison dl{margin:0}.comparison dl div{display:grid;grid-template-columns:85px 1fr;gap:8px;padding:5px 0}.comparison dt{font-size:10px;color:#788984}.comparison dd{margin:0;font-size:11px;color:#2d4d47}.rating-form{display:grid;grid-template-columns:1fr 180px;gap:12px;padding:16px 18px;background:#fbf7ee}.rating-form>label{font-size:10px;color:#5f736e}.rating-form select,.rating-form input,.rating-form textarea{display:block;width:100%;box-sizing:border-box;margin-top:5px}.rating-form fieldset{grid-column:1/-1;border:0;padding:0;margin:0}.rating-form legend{font-size:10px;color:#5f736e;margin-bottom:6px}.rating-form fieldset label{display:inline-flex;align-items:center;gap:4px;margin:4px 14px 4px 0;font-size:10px}.rating-form fieldset input{width:auto;margin:0}.rating-form .note{grid-column:1/-1}.rating-form button{justify-self:end;grid-column:1/-1}.warning-list{border:1px solid #ecd79e;background:#fff9e9;border-radius:12px;padding:11px 16px}.warning-list p{margin:5px 0;color:#785f27;font-size:11px}.metric-grid strong.unknown{color:#8b9794}.result-table{overflow:auto;border:1px solid #dce8e4;border-radius:12px;background:#fff}.result-table table{width:100%;border-collapse:collapse;min-width:900px}.result-table th,.result-table td{text-align:left;padding:10px;border-bottom:1px solid #edf2f0;font-size:10px}.result-table th{background:#f4f8f6;color:#526963}@media(max-width:900px){.hero{flex-direction:column}.progress-grid,.metric-grid,.comparison{grid-template-columns:1fr}.rating-form{grid-template-columns:1fr}.hero-actions{width:100%;flex-direction:column}.hero select{width:100%}}
</style>
