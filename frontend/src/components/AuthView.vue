<script setup lang="ts">
import { ref } from 'vue'

import { API_BASE, authSession } from '../services/auth'

const emit = defineEmits<{ authenticated: [] }>()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!username.value.trim() || !password.value) return
  loading.value = true
  error.value = ''
  try {
    await authSession.login(username.value.trim(), password.value)
    emit('authenticated')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登入失敗'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-screen">
    <section class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark"><span></span><span></span><span></span></div>
        <div><strong>TalentHub</strong><small>HR 招募管理</small></div>
      </div>
      <div class="auth-copy">
        <p>SECURE WORKSPACE</p>
        <h1>登入 HR 工作台</h1>
        <span>使用管理員建立的公司帳號登入。系統不提供公開註冊。</span>
      </div>
      <div v-if="error" class="auth-error">{{ error }}</div>
      <form @submit.prevent="submit">
        <label>帳號或 Email<input v-model="username" autocomplete="username" autofocus required></label>
        <label>密碼<input v-model="password" type="password" autocomplete="current-password" required></label>
        <button class="button primary" :disabled="loading">{{ loading ? '驗證中…' : '登入工作台' }}</button>
      </form>
      <footer>API：{{ API_BASE }} · Token 僅保存在此分頁工作階段</footer>
    </section>
  </main>
</template>

<style scoped>
.auth-screen{min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 20% 15%,#e2efec 0,transparent 34%),#f5f7f6}.auth-card{width:min(430px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:34px;box-shadow:0 22px 70px rgba(29,70,63,.11)}.auth-brand{display:flex;align-items:center;gap:11px}.auth-brand strong,.auth-brand small{display:block}.auth-brand small{font-size:9px;color:var(--muted)}.auth-copy{margin:34px 0 24px}.auth-copy p{font-size:9px;letter-spacing:1.4px;color:var(--primary);font-weight:700}.auth-copy h1{font-size:25px;margin:7px 0}.auth-copy span{font-size:11px;line-height:1.8;color:var(--muted)}form{display:grid;gap:15px}label{font-size:10px;color:#5d716d}input{display:block;width:100%;height:43px;margin-top:6px;border:1px solid #d8e3e0;border-radius:8px;padding:0 12px;outline:none}input:focus{border-color:#4c958c;box-shadow:0 0 0 3px #e6f1ef}.button{height:43px;margin-top:4px}.auth-error{background:#fff0ef;color:#963e39;border-radius:8px;padding:10px 12px;font-size:10px;margin-bottom:15px}footer{font-size:8px;color:#93a09d;text-align:center;margin-top:23px}
</style>
