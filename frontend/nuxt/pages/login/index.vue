<script setup lang="ts">
import type { AuthConfig } from '../../types'
const { base, post } = useApi()
const { refresh } = useSession()
const { text } = useUiLocale()
const secret = ref('')
const error = ref('')
const busy = ref(false)
const { data: authConfig } = await useAsyncData('auth-config', () => useApi().get<AuthConfig>('/api/auth/config'))
function prismLogin() { location.assign(`${base}/api/auth/login?redirect=1`) }
async function devLogin() {
  busy.value = true
  try {
    const result = await post<{ access_token: string }>('/api/auth/dev-login')
    localStorage.setItem('voidswitch.token', result.access_token)
    await refresh()
    await navigateTo('/dashboard')
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function tokenLogin() {
  busy.value = true
  try {
    const result = await post<{ access_token: string }>('/api/auth/token-login', { token: secret.value })
    localStorage.setItem('voidswitch.token', result.access_token)
    await refresh()
    await navigateTo('/dashboard')
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
</script>
<template>
  <div class="grid min-h-screen place-items-center p-4">
    <UCard class="w-full max-w-sm space-y-4">
      <h1 class="mb-4 text-xl font-bold">VoidSwitch</h1>
      <UButton block :label="text('使用 Prism 登录', 'Sign in with Prism')" @click="prismLogin" />
      <UButton v-if="authConfig?.dev_mode" block variant="outline" :loading="busy" :label="text('开发模式登录', 'Development sign in')" @click="devLogin" />
      <form class="mt-4 space-y-3" @submit.prevent="tokenLogin">
        <UInput v-model="secret" type="password" :placeholder="text('登录令牌', 'Login token')" class="w-full" />
        <UButton type="submit" block color="neutral" variant="outline" :loading="busy" :label="text('令牌登录', 'Sign in with token')" />
      </form>
      <UAlert v-if="error" color="error" :description="error" />
    </UCard>
  </div>
</template>
