<script setup lang="ts">
import { computed } from 'vue'
import type { Distribution } from '../services/matchingReportsApi'

const props = defineProps<{ title: string; items: Distribution[] }>()
const maximum = computed(() => Math.max(1, ...props.items.map(item => item.count)))
</script>

<template>
  <article class="panel report-card">
    <header><h2>{{ title }}</h2><small>資料庫有效人才</small></header>
    <div v-if="items.length" class="bars"><div v-for="item in items" :key="item.label"><span>{{ item.label }}</span><i><u :style="{ width: `${Math.round(item.count / maximum * 100)}%` }"></u></i><b>{{ item.count }}</b></div></div>
    <div v-else class="report-empty">尚無資料</div>
  </article>
</template>

<style scoped>
.report-card{padding:17px}.report-card header{display:flex;justify-content:space-between;border-bottom:1px solid #edf1f0;padding-bottom:11px;margin-bottom:14px}.report-card h2{font-size:13px;margin:0}.report-card header small{font-size:8px;color:#81908d}.report-empty{text-align:center;color:#82908d;font-size:9px;padding:35px}.bars>div{display:grid;grid-template-columns:100px 1fr 35px;align-items:center;gap:9px;margin:9px 0}.bars span,.bars b{font-size:8px}.bars b{text-align:right}.bars i{height:7px;background:#e8efed;border-radius:6px;overflow:hidden}.bars u{display:block;height:100%;background:#4b9389;border-radius:6px;text-decoration:none}
</style>
