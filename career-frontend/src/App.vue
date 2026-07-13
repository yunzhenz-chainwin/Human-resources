<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApplication, getJob, getJobs } from './api'
import type { ApplicationForm, Job } from './types'

type View = 'home' | 'jobs' | 'detail' | 'apply' | 'success'
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
  await loadJobs()
  const jobId = new URLSearchParams(window.location.search).get('job_id')
  if (!jobId) return
  const job = jobs.value.find(item => String(item.id) === jobId)
  if (job) startApplication(job)
})
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
      <section class="hero">
        <div>
          <p class="eyebrow">TALENTBRIDGE CAREERS</p>
          <h1>找到適合你的<br><em>下一個機會</em></h1>
          <p class="lead">瀏覽目前職缺，或用幾分鐘留下履歷。沒有適合的職缺也沒關係，我們會將你加入人才庫。</p>
          <div class="actions">
            <button class="primary" @click="go('jobs')">查看職缺</button>
            <button class="secondary" @click="startApplication(null)">加入人才庫</button>
          </div>
        </div>
        <div class="hero-card">
          <span>簡單三步驟</span>
          <ol><li>填寫基本資料</li><li>選擇工作偏好</li><li>履歷可選填</li></ol>
          <small>不需註冊或登入</small>
        </div>
      </section>
      <section class="home-jobs">
        <div><p class="eyebrow">OPEN POSITIONS</p><h2>目前開放職缺</h2><p>從合適的職缺開始，讓我們更快認識你。</p></div>
        <button class="primary" @click="go('jobs')">瀏覽全部職缺</button>
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
          <section v-if="selectedJob" class="form-section"><h2>想補充的內容（選填）</h2>
            <label>簡短自我介紹<textarea v-model.trim="form.cover_letter" maxlength="10000" rows="4" placeholder="可簡單說明相關經驗或應徵動機，也可以留白。"></textarea></label>
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

  <footer><div><strong>TalentBridge Careers</strong><p>讓合適的人才，遇見合適的機會。</p></div><a href="mailto:careers@talentbridge.tw">careers@talentbridge.tw</a></footer>
</template>
