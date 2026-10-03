<script setup lang="ts">
const api = useApi()
const { isStaff } = useSession()
const { text } = useUiLocale()
const { data, status, error, refresh } = await useAsyncData('dashboard', () => isStaff.value ? api.get<Record<string, unknown>>('/api/admin/stats') : api.get<Record<string, unknown>>('/api/me/usage'))
</script>
<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between"><h1 class="text-2xl font-bold">{{ text('仪表盘', 'Dashboard') }}</h1><UButton variant="outline" icon="i-lucide-refresh-cw" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <UCard v-for="(value, key) in data" :key="key"><div class="text-sm text-muted">{{ key }}</div><div class="mt-2 text-2xl font-semibold">{{ typeof value === 'object' ? '—' : value }}</div></UCard>
    </div>
  </div>
</template>
