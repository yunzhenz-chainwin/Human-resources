<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import DistributionCard from './DistributionCard.vue'
import type { RequisitionDto } from '../services/hrApi'
import {
  matchingReportsApi,
  type FunnelReport,
  type SourcesReport,
  type TalentPoolReport,
  type TimeToFillReport,
} from '../services/matchingReportsApi'

const props = defineProps<{ jobs: RequisitionDto[] }>()
const filters = reactive({ from: '', to: '', department_id: '' })
const loading = ref(false)
const error = ref('')
const funnel = ref<FunnelReport>({ total: 0, stages: [] })
const timeToFill = ref<TimeToFillReport>({ filled_count: 0, average_days: 0, items: [] })
const sources = ref<SourcesReport>({ total: 0, items: [] })
const talent = ref<TalentPoolReport>({ total: 0, skills: [], experience: [], cities: [], education: [], monthly_growth: [] })
const departments = computed(() => [...new Set(props.jobs.map(job => job.department_id).filter((id): id is number => id !== null))].sort((a, b) => a - b))
const stageLabels: Record<string, string> = { recommended: '推薦', contacted: '聯繫', interview: '面試', hired: '錄取' }
const sourceLabels: Record<string, string> = { p104: '104 人力銀行', p1111: '1111 人力銀行', referral: '內部推薦', direct: '直接投遞', generic: '一般履歷', career_site: '職涯網站', unknown: '未知來源' }

async function loadReports() {
  if (filters.from && filters.to && filters.from > filters.to) {
    error.value = '開始日期不可晚於結束日期'
    return
  }
  loading.value = true
  error.value = ''
  const requestFilters = {
    from: filters.from || undefined,
    to: filters.to || undefined,
    department_id: filters.department_id ? Number(filters.department_id) : undefined,
  }
  try {
    const [funnelData, fillData, sourceData, talentData] = await Promise.all([
      matchingReportsApi.funnel(requestFilters),
      matchingReportsApi.timeToFill(requestFilters),
      matchingReportsApi.sources(requestFilters),
      matchingReportsApi.talentPool(requestFilters),
    ])
    funnel.value = funnelData
    timeToFill.value = fillData
    sources.value = sourceData
    talent.value = talentData
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '報表讀取失敗'
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(filters, { from: '', to: '', department_id: '' })
  loadReports()
}

function max(items: { count: number }[]) {
  return Math.max(1, ...items.map(item => item.count))
}

function width(count: number, items: { count: number }[]) {
  return `${Math.round(count / max(items) * 100)}%`
}

onMounted(loadReports)
</script>

<template>
  <section class="reports-view">
    <div class="page-heading"><div><h1>數據報表</h1><p>所有指標皆由資料庫即時聚合，不含展示或預填數據。</p></div></div>
    <div class="report-filter panel"><label>開始日期<input v-model="filters.from" type="date"></label><label>結束日期<input v-model="filters.to" type="date"></label><label>部門<select v-model="filters.department_id"><option value="">全部部門</option><option v-for="id in departments" :key="id" :value="id">部門 #{{ id }}</option></select></label><span></span><button class="button secondary" @click="reset">清除</button><button class="button primary" :disabled="loading" @click="loadReports">{{ loading ? '彙整中…' : '套用篩選' }}</button></div>
    <div v-if="error" class="report-error">{{ error }}</div>
    <div class="report-metrics"><article class="panel"><span>期間投遞</span><strong>{{ funnel.total }}</strong><small>有效人才的職缺投遞</small></article><article class="panel"><span>已補齊職缺</span><strong>{{ timeToFill.filled_count }}</strong><small>符合篩選的職缺</small></article><article class="panel"><span>平均補齊天數</span><strong>{{ timeToFill.average_days }}</strong><small>發布至補齊</small></article><article class="panel"><span>人才庫人數</span><strong>{{ talent.total }}</strong><small>已排除軟刪除資料</small></article></div>
    <div class="report-grid">
      <article class="panel report-card funnel-card"><header><h2>招募漏斗</h2><small>各階段為累積人數</small></header><div v-if="funnel.stages.length" class="funnel"><div v-for="stage in funnel.stages" :key="stage.stage" :style="{ width: `${Math.max(28, stage.count / Math.max(1, funnel.total) * 100)}%` }"><span>{{ stageLabels[stage.stage] || stage.stage }}</span><strong>{{ stage.count }}</strong><small>轉換 {{ Math.round(stage.conversion_rate * 100) }}%</small></div></div><div v-else class="report-empty">尚無投遞資料</div></article>
      <article class="panel report-card"><header><h2>來源績效</h2><small>投遞數與錄取率</small></header><div v-if="sources.items.length" class="source-table"><div v-for="item in sources.items" :key="item.source"><span><strong>{{ sourceLabels[item.source] || item.source }}</strong><small>{{ item.hired }} 人錄取</small></span><b>{{ item.total }}</b><em>{{ Math.round(item.hire_rate * 100) }}%</em></div></div><div v-else class="report-empty">尚無來源資料</div></article>
      <article class="panel report-card wide"><header><h2>職缺補齊天數</h2><small>依補齊時間由新到舊</small></header><div v-if="timeToFill.items.length" class="fill-table"><div v-for="item in timeToFill.items" :key="item.requisition_id"><span><strong>{{ item.title }}</strong><small>{{ item.req_no }} · {{ item.department_id ? `部門 #${item.department_id}` : '未設定部門' }}</small></span><b>{{ item.days }} 天</b></div></div><div v-else class="report-empty">期間內沒有已補齊職缺</div></article>
      <DistributionCard title="技能 Top" :items="talent.skills" />
      <DistributionCard title="城市分佈" :items="talent.cities" />
      <DistributionCard title="年資分佈" :items="talent.experience" />
      <DistributionCard title="學歷分佈" :items="talent.education" />
      <article class="panel report-card wide"><header><h2>人才庫月增量</h2><small>依入庫月份</small></header><div v-if="talent.monthly_growth.length" class="bars horizontal"><div v-for="item in talent.monthly_growth" :key="item.month"><span>{{ item.month }}</span><i><u :style="{ width: width(item.count, talent.monthly_growth) }"></u></i><b>{{ item.count }}</b></div></div><div v-else class="report-empty">尚無人才入庫資料</div></article>
    </div>
  </section>
</template>

<style scoped>
.report-filter{display:flex;align-items:end;gap:10px;padding:14px;margin-bottom:14px}.report-filter label{font-size:9px;color:#627570}.report-filter input,.report-filter select{display:block;height:38px;margin-top:5px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 10px;color:#354e49}.report-filter>span{flex:1}.report-error{padding:11px 14px;background:#fff0ef;color:#943f3a;border-radius:8px;margin-bottom:12px;font-size:10px}.report-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.report-metrics article{padding:17px}.report-metrics span,.report-metrics small,.report-metrics strong{display:block}.report-metrics span{font-size:9px;color:#758581}.report-metrics strong{font-size:27px;margin:5px 0}.report-metrics small{font-size:8px;color:#899692}.report-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.report-card{padding:17px}.report-card.wide{grid-column:1/-1}.report-card header{display:flex;justify-content:space-between;border-bottom:1px solid #edf1f0;padding-bottom:11px;margin-bottom:14px}.report-card h2{font-size:13px;margin:0}.report-card header small{font-size:8px;color:#81908d}.report-empty{text-align:center;color:#82908d;font-size:9px;padding:35px}.funnel{display:flex;flex-direction:column;align-items:center;gap:5px}.funnel>div{background:linear-gradient(90deg,#dceee9,#edf6f3);padding:9px 13px;display:flex;justify-content:center;gap:12px;clip-path:polygon(4% 0,96% 0,100% 100%,0 100%);font-size:9px}.funnel strong{font-size:13px}.funnel small{color:#66807a}.source-table>div,.fill-table>div{display:flex;align-items:center;border-bottom:1px solid #edf1f0;padding:10px 2px}.source-table span,.fill-table span{flex:1}.source-table strong,.source-table small,.fill-table strong,.fill-table small{display:block;font-size:9px}.source-table small,.fill-table small{font-size:8px;color:#83928e;margin-top:3px}.source-table b{width:50px;text-align:center}.source-table em{width:50px;text-align:right;font-style:normal;color:#28745f}.fill-table b{font-size:10px}.bars>div{display:grid;grid-template-columns:100px 1fr 35px;align-items:center;gap:9px;margin:9px 0}.bars span,.bars b{font-size:8px}.bars b{text-align:right}.bars i{height:7px;background:#e8efed;border-radius:6px;overflow:hidden}.bars u{display:block;height:100%;background:#4b9389;border-radius:6px;text-decoration:none}.bars.horizontal{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0 24px}@media(max-width:900px){.report-metrics{grid-template-columns:1fr 1fr}.report-grid{grid-template-columns:1fr}.report-card.wide{grid-column:auto}.report-filter{align-items:stretch;flex-direction:column}.report-filter input,.report-filter select{width:100%}}
</style>
