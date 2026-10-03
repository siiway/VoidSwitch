<script setup lang="ts">
const error = ref('')
onMounted(async () => {
  const params = new URLSearchParams(location.hash.slice(1))
  const token = params.get('access_token')
  error.value = params.get('error') || (token ? '' : 'missing_token')
  if (!token) return
  localStorage.setItem('voidswitch.token', token)
  history.replaceState(null, '', location.pathname + location.search)
  await useSession().refresh()
  await navigateTo('/dashboard', { replace: true })
})
</script>
<template><div class="grid min-h-screen place-items-center"><UAlert v-if="error" color="error" :title="error" /><span v-else>登录中…</span></div></template>
