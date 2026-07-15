<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createApplication, getJob, getJobs } from './api'
import type { ApplicationForm, Job } from './types'

type View = 'home' | 'jobs' | 'detail' | 'apply' | 'success'
type JourneyAction = 'jobs' | 'talent'
type JourneyStepId = 1 | 2 | 3 | 4

interface JourneyStep {
  id: JourneyStepId
  eyebrow: string
  title: string
  description: string
  cta: string
  action: JourneyAction
  x: number
  y: number
  compactX: number
  compactY: number
}

const view = ref<View>('home')
const jobs = ref<Job[]>([])
const selectedJob = ref<Job | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const keyword = ref('')
const resume = ref<File | null>(null)
const submitting = ref(false)
const submitError = ref('')
const fileError = ref('')
const contactError = ref('')
const resultId = ref<number | undefined>()
const fileInput = ref<HTMLInputElement | null>(null)
const MAX_FILE_SIZE = 10 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['pdf', 'doc', 'docx']
const compactJourney = ref(false)
const journeyRoadPath = computed(() => compactJourney.value
  ? 'M 68 70 C 215 32 324 75 282 170 C 240 265 115 225 78 320 C 43 410 185 478 282 430'
  : 'M 92 288 C 160 288 176 112 270 112 C 365 112 372 258 486 258 C 584 258 584 92 680 92')
const journeySteps: JourneyStep[] = [
  {
    id: 1,
    eyebrow: '先找到方向',
    title: '探索機會',
    description: '從職缺、部門與地點開始，看看哪個機會貼近你的下一步。',
    cta: '查看開放職缺',
    action: 'jobs',
    x: 92,
    y: 288,
    compactX: 68,
    compactY: 70,
  },
  {
    id: 2,
    eyebrow: '讓我們認識你',
    title: '留下資料',
    description: '沒有完全吻合的職缺也沒關係，留下基本資料與履歷，加入人才庫。',
    cta: '加入人才庫',
    action: 'talent',
    x: 270,
    y: 112,
    compactX: 282,
    compactY: 170,
  },
  {
    id: 3,
    eyebrow: '由招募團隊接手',
    title: 'HR媒合',
    description: 'HR 會依經歷、技能與職涯期待比對職缺，找到合適機會再與你聯繫。',
    cta: '建立人才資料',
    action: 'talent',
    x: 486,
    y: 258,
    compactX: 78,
    compactY: 320,
  },
  {
    id: 4,
    eyebrow: '一起確認適合度',
    title: '展開對話',
    description: '與 HR 或用人團隊交流工作內容、團隊文化與下一步，雙向確認是否適合。',
    cta: '看看目前機會',
    action: 'jobs',
    x: 680,
    y: 92,
    compactX: 282,
    compactY: 430,
  },
]
const activeJourneyStep = ref<JourneyStepId>(1)
const cities = [
  '台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市', '基隆市', '新竹市',
  '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義市', '嘉義縣', '屏東縣',
  '宜蘭縣', '花蓮縣', '台東縣', '澎湖縣', '金門縣', '連江縣', '遠端工作', '其他／海外',
]
const roleOptions = [
  '軟體／資訊', '產品／專案管理', '設計／使用者體驗', '行銷／公關', '業務／客戶服務',
  '人力資源／行政', '財務／會計', '營運／供應鏈', '工程／製造', '其他',
]
const experienceOptions = [
  { value: 0, label: '尚無正式工作經驗' },
  { value: 1, label: '1 年以下' },
  { value: 2, label: '1–3 年' },
  { value: 4, label: '3–5 年' },
  { value: 7, label: '5–10 年' },
  { value: 12, label: '10 年以上' },
]
const skillOptions = [
  '軟體開發', '資料分析／AI', '專案管理', '產品規劃', 'UI／UX 設計', '數位行銷',
  '業務開發', '客戶服務', '人力資源', '財務會計', '製造工程', '其他',
]

const emptyForm = (jobId: string | number | null = null): ApplicationForm => ({
  job_id: jobId,
  name: '',
  email: '',
  phone: '',
  city: '',
  current_title: '',
  total_years: null,
  skills: '',
  linkedin_url: '',
  portfolio_url: '',
  cover_letter: '',
  consent: false,
  source_platform: 'direct',
})
const form = ref<ApplicationForm>(emptyForm())

const filteredJobs = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return jobs.value
  return jobs.value.filter(job => [job.title, job.department, job.location, job.summary]
    .some(value => value?.toLowerCase().includes(q)))
})
const applyTitle = computed(() => selectedJob.value ? `應徵「${selectedJob.value.title}」` : '加入人才庫')
const activeJourney = computed(() => (
  journeySteps.find(step => step.id === activeJourneyStep.value) ?? journeySteps[0]
))

async function loadJobs() {
  loading.value = true
  error.value = ''
  try { jobs.value = await getJobs() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '目前無法取得職缺。' }
  finally { loading.value = false }
}

function go(next: View) {
  view.value = next
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function openJob(job: Job) {
  selectedJob.value = job
  go('detail')
  detailLoading.value = true
  try { selectedJob.value = await getJob(job.id) }
  catch { /* list data is enough to keep the page usable */ }
  finally { detailLoading.value = false }
}

function startApplication(job: Job | null = null) {
  selectedJob.value = job
  form.value = emptyForm(job?.id ?? null)
  resume.value = null
  submitError.value = ''
  fileError.value = ''
  contactError.value = ''
  if (fileInput.value) fileInput.value.value = ''
  go('apply')
}

function activateJourneyStep(step: JourneyStep) {
  activeJourneyStep.value = step.id
}

function followJourneyAction(step: JourneyStep) {
  if (step.action === 'jobs') {
    go('jobs')
    return
  }
  startApplication(null)
}

function textList(value?: string[] | string): string[] {
  if (!value) return []
  if (Array.isArray(value)) return value
  return value.split(/\r?\n/).map(item => item.replace(/^[-•\s]+/, '').trim()).filter(Boolean)
}

function salary(job: Job): string {
  if (!job.salary_min && !job.salary_max) return '薪資面議'
  const min = job.salary_min?.toLocaleString('zh-TW') || ''
  const max = job.salary_max?.toLocaleString('zh-TW') || ''
  return `${job.salary_currency || 'TWD'} ${min}${min && max ? '–' : ''}${max}`
}

function selectResume(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  fileError.value = ''
  resume.value = null
  if (!file) return
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    fileError.value = '僅接受 PDF、DOC 或 DOCX 檔案。'
    input.value = ''
    return
  }
  if (file.size > MAX_FILE_SIZE) {
    fileError.value = '檔案不可超過 10 MB。'
    input.value = ''
    return
  }
  resume.value = file
}

async function submit() {
  if (submitting.value) return
  contactError.value = ''
  if (!form.value.email && !form.value.phone) {
    contactError.value = 'Email 或手機請至少填寫一項，方便 HR 與你聯絡。'
    return
  }
  submitError.value = ''
  submitting.value = true
  try {
    const response = await createApplication(form.value, resume.value)
    resultId.value = response.application_id || response.candidate_id || response.resume_id
    go('success')
  } catch (cause) {
    submitError.value = cause instanceof Error ? cause.message : '送出失敗，請稍後再試。'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  compactJourney.value = window.matchMedia('(max-width: 600px)').matches
  window.addEventListener('resize', syncJourneyLayout)
  await loadJobs()
  const jobId = new URLSearchParams(window.location.search).get('job_id')
  if (!jobId) return
  const job = jobs.value.find(item => String(item.id) === jobId)
  if (job) startApplication(job)
})

function syncJourneyLayout() {
  compactJourney.value = window.matchMedia('(max-width: 600px)').matches
}

onBeforeUnmount(() => window.removeEventListener('resize', syncJourneyLayout))
</script>

<template>
  <header class="site-header">
    <button class="brand" @click="go('home')" aria-label="回到首頁">
      <span class="brand-mark">T</span>
      <span>TalentBridge<small>CAREERS</small></span>
    </button>
    <nav aria-label="主要導覽">
      <button @click="go('jobs')">查看職缺</button>
      <button class="nav-cta" @click="startApplication(null)">加入人才庫</button>
    </nav>
  </header>

  <main>
    <template v-if="view === 'home'">
      <section class="career-journey" data-testid="career-journey">
        <div class="journey-copy">
          <p class="eyebrow">YOUR JOURNEY</p>
          <h2>從看見機會，到展開對話</h2>
          <p>求職不是一次送出履歷，而是一段逐步找到彼此適合位置的旅程。點選路標，看看每一步會發生什麼。</p>
        </div>

        <div class="journey-map-card">
          <svg
            class="journey-map"
            :viewBox="compactJourney ? '0 0 360 500' : '0 0 760 380'"
            role="img"
            aria-labelledby="journey-map-title journey-map-description"
          >
            <title id="journey-map-title">TalentBridge 求職旅程</title>
            <desc id="journey-map-description">依序經過探索機會、留下資料、HR 媒合與展開對話四個階段。</desc>
            <path class="journey-road-halo" :d="journeyRoadPath" fill="none" />
            <path class="journey-road" :d="journeyRoadPath" fill="none" />
            <path class="journey-centerline" :d="journeyRoadPath" fill="none" />

            <g
              v-for="step in journeySteps"
              :key="step.id"
              class="journey-stop"
              :class="[`stop-${step.id}`, { active: activeJourneyStep === step.id }]"
              :data-testid="`career-journey-stop-${step.id}`"
              :transform="`translate(${compactJourney ? step.compactX : step.x} ${compactJourney ? step.compactY : step.y})`"
              role="button"
              tabindex="0"
              :aria-label="`第 ${step.id} 站：${step.title}`"
              :aria-current="activeJourneyStep === step.id ? 'step' : undefined"
              :aria-pressed="activeJourneyStep === step.id"
              @click="activateJourneyStep(step)"
              @keydown.enter.prevent="activateJourneyStep(step)"
              @keydown.space.prevent="activateJourneyStep(step)"
            >
              <circle class="journey-stop-ring" r="34" />
              <circle class="journey-stop-face" r="25" />
              <text class="journey-stop-number" text-anchor="middle" dominant-baseline="central">{{ step.id }}</text>
              <line class="journey-stop-post" x1="0" y1="34" x2="0" y2="48" />
              <rect class="journey-stop-sign" x="-58" y="46" width="116" height="34" rx="17" />
              <text class="journey-stop-label" y="63" text-anchor="middle" dominant-baseline="central">{{ step.title }}</text>
            </g>
          </svg>

          <article class="journey-detail" aria-live="polite">
            <p class="eyebrow">STEP {{ activeJourney.id }} · {{ activeJourney.eyebrow }}</p>
            <h3>{{ activeJourney.title }}</h3>
            <p>{{ activeJourney.description }}</p>
            <button class="primary" type="button" @click="followJourneyAction(activeJourney)">{{ activeJourney.cta }}</button>
          </article>
        </div>
      </section>
    </template>

    <template v-else-if="view === 'jobs'">
      <section class="page-heading">
        <p class="eyebrow">OPEN POSITIONS</p><h1>目前職缺</h1><p>選擇感興趣的職缺，查看內容並直接應徵。</p>
      </section>
      <section class="jobs-layout">
        <div class="jobs-toolbar">
          <label class="search">搜尋職缺<input v-model="keyword" type="search" placeholder="職稱、部門或地點"></label>
          <button class="secondary" @click="startApplication(null)">沒有合適職缺？加入人才庫</button>
        </div>
        <div v-if="loading" class="state"><span class="spinner"></span><h2>正在取得職缺</h2></div>
        <div v-else-if="error" class="state error"><h2>暫時無法載入</h2><p>{{ error }}</p><button class="secondary" @click="loadJobs">再試一次</button></div>
        <div v-else-if="!filteredJobs.length" class="state"><h2>目前沒有符合的職缺</h2><p>你仍可留下履歷，讓 HR 在有合適機會時聯絡你。</p><button class="primary" @click="startApplication(null)">加入人才庫</button></div>
        <div v-else class="job-list">
          <button v-for="job in filteredJobs" :key="job.id" class="job-card" @click="openJob(job)">
            <div><span class="tag">{{ job.department || '招募中' }}</span><h2>{{ job.title }}</h2><p>{{ job.summary || '點選查看完整職缺內容。' }}</p><div class="meta"><span>{{ job.location || '地點面議' }}</span><span>{{ job.employment_type || '全職' }}</span></div></div>
            <span class="arrow" aria-hidden="true">→</span>
          </button>
        </div>
      </section>
    </template>

    <template v-else-if="view === 'detail' && selectedJob">
      <section class="detail-hero"><button class="back" @click="go('jobs')">← 回到職缺列表</button><span class="tag">{{ selectedJob.department || '招募中' }}</span><h1>{{ selectedJob.title }}</h1><div class="meta"><span>{{ selectedJob.location || '地點面議' }}</span><span>{{ selectedJob.employment_type || '全職' }}</span><span>{{ salary(selectedJob) }}</span></div></section>
      <section class="detail-layout">
        <article class="job-content"><p v-if="detailLoading" class="inline-loading">正在載入完整內容…</p><h2>工作內容</h2><p class="preserve">{{ selectedJob.description || selectedJob.summary || '詳細內容請與招募窗口確認。' }}</p><template v-if="textList(selectedJob.requirements).length"><h2>條件與技能</h2><ul><li v-for="item in textList(selectedJob.requirements)" :key="item">{{ item }}</li></ul></template></article>
        <aside><div class="apply-box"><h2>對這份工作有興趣？</h2><p>不需建立帳號，填寫簡單資料即可；履歷可稍後再提供。</p><button class="primary" @click="startApplication(selectedJob)">立即應徵</button></div></aside>
      </section>
    </template>

    <template v-else-if="view === 'apply'">
      <section class="application-page">
        <button class="back" @click="selectedJob ? go('detail') : go('home')">← 返回</button>
        <div class="application-heading"><p class="eyebrow">TALENT PROFILE</p><h1>{{ applyTitle }}</h1><p>只需姓名、至少一種聯絡方式與同意，其他資料及履歷都可選填。</p><div v-if="selectedJob" class="selected-job"><span>應徵職缺</span><strong>{{ selectedJob.title }}</strong><button type="button" @click="startApplication(null)">改為加入人才庫</button></div></div>
        <form @submit.prevent="submit">
          <section class="form-section"><h2>基本資料</h2><div class="form-grid">
            <label>姓名 *<input v-model.trim="form.name" required maxlength="100" autocomplete="name" placeholder="你的姓名"></label>
            <label>Email（與手機擇一）<input v-model.trim="form.email" type="email" maxlength="255" autocomplete="email" placeholder="name@example.com"></label>
            <label>手機（與 Email 擇一）<input v-model.trim="form.phone" type="tel" minlength="8" maxlength="50" autocomplete="tel" placeholder="09xx-xxx-xxx"></label>
            <label>希望工作地點<select v-model="form.city"><option value="">暫不提供</option><option v-for="city in cities" :key="city" :value="city">{{ city }}</option></select></label>
            <label>職務類別<select v-model="form.current_title"><option value="">暫不提供</option><option v-for="role in roleOptions" :key="role" :value="role">{{ role }}</option></select></label>
            <label>工作年資<select v-model.number="form.total_years"><option :value="null">暫不提供</option><option v-for="item in experienceOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            <label>主要專長<select v-model="form.skills"><option value="">暫不提供</option><option v-for="skill in skillOptions" :key="skill" :value="skill">{{ skill }}</option></select></label>
            <p v-if="contactError" class="field-error form-wide" role="alert">{{ contactError }}</p>
          </div></section>
          <section v-if="selectedJob" class="form-section"><h2>專業連結與補充內容（選填）</h2><div class="form-grid">
            <label>LinkedIn<input v-model.trim="form.linkedin_url" type="url" inputmode="url" maxlength="1000" autocomplete="url" placeholder="https://www.linkedin.com/in/..."></label>
            <label>作品集／個人網站<input v-model.trim="form.portfolio_url" type="url" inputmode="url" maxlength="1000" autocomplete="url" placeholder="https://portfolio.example.com"></label>
            <label class="form-wide">簡短自我介紹<textarea v-model.trim="form.cover_letter" maxlength="10000" rows="4" placeholder="可簡單說明相關經驗或應徵動機，也可以留白。"></textarea></label>
          </div>
          </section>
          <section class="form-section"><h2>履歷檔案（選填）</h2>
            <label class="upload" :class="{ chosen: resume }"><input ref="fileInput" aria-label="履歷檔案" type="file" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" @change="selectResume"><span class="upload-icon">↑</span><b>{{ resume ? resume.name : '有履歷再上傳即可' }}</b><small>可不提供；若上傳，支援 PDF、DOC、DOCX，最大 10 MB</small></label>
            <p v-if="fileError" class="field-error" role="alert">{{ fileError }}</p>
          </section>
          <label class="consent"><input v-model="form.consent" type="checkbox" required><span>我同意 TalentBridge 蒐集與使用上述資料及履歷，作為招募聯繫與人才媒合用途。 *</span></label>
          <div v-if="submitError" class="submit-error" role="alert"><strong>尚未送出</strong><span>{{ submitError }}</span></div>
          <button class="primary submit" :disabled="submitting" type="submit"><span v-if="submitting" class="button-spinner"></span>{{ submitting ? '正在送出…' : (selectedJob ? '送出應徵' : '加入人才庫') }}</button>
          <p class="privacy-note">送出前請確認聯絡資料正確。成功後畫面會顯示完成通知。</p>
        </form>
      </section>
    </template>

    <template v-else-if="view === 'success'">
      <section class="success-page"><div class="success-check">✓</div><p class="eyebrow">RECEIVED</p><h1>{{ selectedJob ? '應徵資料已成功送出' : '已成功加入人才庫' }}</h1><p>{{ selectedJob ? `我們已收到你對「${selectedJob.title}」的應徵。` : '資料已交給 HR，有合適機會時我們會與你聯繫。' }}</p><p v-if="resultId" class="reference">參考編號：{{ resultId }}</p><button class="primary" @click="go('jobs')">查看其他職缺</button><button class="text-button" @click="go('home')">回到首頁</button></section>
    </template>
  </main>

  <footer v-if="view !== 'home'"><div><strong>TalentBridge Careers</strong><p>讓合適的人才，遇見合適的機會。</p></div><a href="mailto:careers@talentbridge.tw">careers@talentbridge.tw</a></footer>
</template>
