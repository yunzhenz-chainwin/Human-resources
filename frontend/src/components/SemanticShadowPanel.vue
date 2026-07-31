<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  semanticShadowApi,
  type SemanticShadowComparison,
} from '../services/semanticShadowApi'

const props = defineProps<{ matchId: number }>()

const comparison = ref<SemanticShadowComparison | null>(null)
const acknowledged = ref(false)
const loading = ref(false)
const generating = ref(false)
const error = ref('')

const shadow = computed(() => comparison.value?.latest_shadow || null)
const sourceLabel = computed(() => (
  shadow.value?.source === 'gemini' ? 'Gemini 語意分析' : '規則式安全降級'
))

function dateTime(value: string) {
  return new Intl.DateTimeFormat('zh-TW', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

async function load() {
  if (!props.matchId) return
  loading.value = true
  error.value = ''
  comparison.value = null
  try {
    comparison.value = await semanticShadowApi.comparison(props.matchId)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '無法讀取影子評分'
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (!acknowledged.value || generating.value) return
  generating.value = true
  error.value = ''
  try {
    await semanticShadowApi.generate(props.matchId)
    acknowledged.value = false
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '影子評分產生失敗'
  } finally {
    generating.value = false
  }
}

watch(() => props.matchId, load)
onMounted(load)
</script>

<template>
  <section class="semantic-shadow-panel" aria-labelledby="semantic-shadow-title">
    <header>
      <div>
        <span class="experiment-badge">實驗功能</span>
        <h3 id="semantic-shadow-title">語意影子比較</h3>
      </div>
      <span v-if="comparison" class="history-count">已產生 {{ comparison.evaluation_count }} 次</span>
    </header>

    <p class="decision-warning">
      <strong>不可作為錄取或淘汰依據。</strong>
      影子分數不會改變正式分數、必要條件、排序或招募狀態。
    </p>

    <p v-if="loading" class="panel-state">正在讀取比較資料…</p>
    <p v-else-if="error" class="panel-error" role="alert">{{ error }}</p>

    <div v-if="comparison" class="score-comparison">
      <article>
        <span>正式媒合</span>
        <strong>{{ comparison.formal.total_score.toFixed(1) }}</strong>
        <small>
          {{ comparison.formal.gate_passed ? '通過必要條件' : '未通過必要條件' }}
          · 排名 {{ comparison.formal.rank || '—' }}
        </small>
      </article>
      <span class="compare-mark" aria-hidden="true">並列比較</span>
      <article class="shadow-score">
        <span>影子語意分數</span>
        <strong>{{ shadow ? shadow.semantic_score.toFixed(1) : '—' }}</strong>
        <small>{{ shadow ? sourceLabel : '尚未人工產生' }}</small>
      </article>
    </div>

    <template v-if="shadow">
      <div class="shadow-meta">
        <span>{{ sourceLabel }}</span>
        <span>{{ shadow.model_name }}</span>
        <span>{{ shadow.total_tokens.toLocaleString() }} tokens</span>
        <span>{{ dateTime(shadow.generated_at) }}</span>
      </div>
      <p v-if="shadow.generation_status === 'fallback'" class="fallback-note">
        Gemini 無法完成分析，本次顯示清楚標記的規則式降級結果（{{ shadow.error_code }}）。
      </p>

      <details v-if="shadow.synonym_evidence.length || shadow.transferable_experience_evidence.length">
        <summary>查看語意符合證據</summary>
        <ul class="evidence-list">
          <li v-for="item in shadow.synonym_evidence" :key="`${item.required_skill}-${item.candidate_skill}`">
            <strong>{{ item.candidate_skill }} → {{ item.required_skill }}</strong>
            <span>{{ item.rationale }}</span>
          </li>
          <li v-for="item in shadow.transferable_experience_evidence" :key="`${item.experience}-${item.target_requirement}`">
            <strong>{{ item.experience }} → {{ item.target_requirement }}</strong>
            <span>{{ item.rationale }}</span>
          </li>
        </ul>
      </details>

      <details v-if="shadow.concerns.length || shadow.insufficient_data.length">
        <summary>查看疑慮與資料不足</summary>
        <ul class="finding-list">
          <li v-for="item in shadow.concerns" :key="`concern-${item}`">疑慮：{{ item }}</li>
          <li v-for="item in shadow.insufficient_data" :key="`missing-${item}`">資料不足：{{ item }}</li>
        </ul>
      </details>

      <details v-if="shadow.interview_questions.length">
        <summary>針對缺口的面試確認題</summary>
        <ol class="question-list">
          <li v-for="item in shadow.interview_questions" :key="`${item.gap}-${item.question}`">
            <strong>{{ item.gap }}</strong>
            <span>{{ item.question }}</span>
            <small>{{ item.reason }}</small>
          </li>
        </ol>
      </details>
    </template>

    <footer>
      <label :for="`semantic-shadow-opt-in-${matchId}`">
        <input
          :id="`semantic-shadow-opt-in-${matchId}`"
          v-model="acknowledged"
          type="checkbox"
          :disabled="generating"
        >
        我了解這是實驗結果，不會用來自動錄取或淘汰
      </label>
      <button
        type="button"
        :disabled="!acknowledged || generating"
        @click="generate"
      >
        {{ generating ? '正在產生…' : shadow ? '重新產生影子評分' : '人工產生影子評分' }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.semantic-shadow-panel{display:grid;gap:14px;padding:16px;border:1px solid #d7e5e1;border-radius:14px;background:#fbfdfc;color:#173f39}.semantic-shadow-panel>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.semantic-shadow-panel h3{display:inline;margin:0 0 0 8px;font-size:16px}.experiment-badge{display:inline-flex;padding:4px 8px;border-radius:999px;background:#fff0cf;color:#815c12;font-size:11px;font-weight:800}.history-count{color:#60766f;font-size:12px}.decision-warning{margin:0;padding:10px 12px;border-left:4px solid #d69f31;border-radius:8px;background:#fff8e8;color:#655125;font-size:12px;line-height:1.6}.decision-warning strong{display:block;color:#795710}.score-comparison{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:10px}.score-comparison article{display:grid;gap:3px;padding:12px;border:1px solid #dce8e5;border-radius:10px;background:#fff}.score-comparison article>span,.score-comparison small{color:#60766f;font-size:11px}.score-comparison strong{font-size:24px;color:#0a6f64}.score-comparison .shadow-score{border-style:dashed;background:#fffbf1}.compare-mark{font-size:10px;color:#71847f}.shadow-meta{display:flex;flex-wrap:wrap;gap:6px}.shadow-meta span{padding:4px 7px;border-radius:999px;background:#edf5f2;color:#47635d;font-size:10px}.fallback-note,.panel-error{margin:0;padding:9px 11px;border-radius:8px;background:#fff1ef;color:#99443d;font-size:12px}.panel-state{margin:0;color:#60766f;font-size:12px}.semantic-shadow-panel details{border-top:1px solid #e3ece9;padding-top:10px}.semantic-shadow-panel summary{cursor:pointer;color:#226b60;font-size:12px;font-weight:800}.evidence-list,.finding-list,.question-list{display:grid;gap:8px;margin:10px 0 0;padding-left:20px}.evidence-list li,.question-list li{display:grid;gap:3px}.evidence-list strong,.question-list strong{font-size:12px}.evidence-list span,.finding-list li,.question-list span,.question-list small{font-size:11px;line-height:1.55;color:#536d67}.semantic-shadow-panel>footer{display:grid;gap:10px;padding-top:2px}.semantic-shadow-panel>footer label{display:flex;align-items:flex-start;gap:8px;color:#536d67;font-size:11px;line-height:1.45}.semantic-shadow-panel>footer input{margin-top:2px}.semantic-shadow-panel button{min-height:40px;border:0;border-radius:9px;background:#0b8174;color:#fff;font-size:12px;font-weight:800;cursor:pointer}.semantic-shadow-panel button:disabled{background:#cbd9d5;cursor:not-allowed}@media(max-width:620px){.score-comparison{grid-template-columns:1fr}.compare-mark{text-align:center}.semantic-shadow-panel>header{align-items:flex-start;flex-direction:column}}
</style>
