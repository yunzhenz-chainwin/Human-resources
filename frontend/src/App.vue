<script setup lang="ts">
const modules = ['人才資料庫', '履歷自動匯入', '職缺需求管理', '智慧配對引擎']
</script>

<template>
  <main class="shell">
    <p class="eyebrow">TalentHub · Phase 1</p>
    <h1>企業人才庫與智慧媒合系統</h1>
    <p class="intro">系統骨架已啟動。接下來將依序完成登入、角色權限與組織管理。</p>
    <section class="grid" aria-label="核心模組">
      <article v-for="module in modules" :key="module">{{ module }}</article>
    </section>
  </main>
</template>

