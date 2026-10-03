<script setup lang="ts">
const { prefs, save } = useWorkbench()
const { text } = useUiLocale()
const labels = { pages: ['页面与操作', 'Pages & actions'], models: ['模型', 'Models'], providers: ['提供商', 'Providers'], users: ['用户', 'Users'] } as const
const valid = computed(() => { const chars = Object.values(prefs.value.prefixes); return chars.every(v => v.length === 1 && !/\s/.test(v)) && new Set(chars).size === chars.length })
</script>
<template>
  <div class="max-w-xl space-y-5">
    <h1 class="text-2xl font-bold">{{ text('工作台偏好', 'Workbench preferences') }}</h1>
    <UCard class="space-y-4">
      <div class="font-medium">{{ text('二级管理操作', 'Secondary management views') }}</div>
      <USelect v-model="prefs.detailMode" :items="[{ label: text('右侧抽屉', 'Right drawer'), value: 'drawer' }, { label: text('整页', 'Full page'), value: 'page' }]" class="w-full" />
    </UCard>
    <UCard class="space-y-4">
      <div class="font-medium">{{ text('命令面板前缀', 'Command prefixes') }}</div>
      <div v-for="(pair, category) in labels" :key="category" class="flex items-center gap-4">
        <label class="w-36">{{ text(pair[0], pair[1]) }}</label>
        <UInput v-model="prefs.prefixes[category]" maxlength="1" class="w-20" />
      </div>
      <UAlert v-if="!valid" color="error" :title="text('前缀必须是互不重复的单个非空字符', 'Prefixes must be distinct, non-whitespace characters')" />
    </UCard>
    <UButton :disabled="!valid" :label="text('保存偏好', 'Save preferences')" @click="save" />
  </div>
</template>
