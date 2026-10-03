<script setup lang="ts">
const { text } = useUiLocale()
const route = useRoute()
</script>
<template>
  <div class="max-w-2xl space-y-5">
    <UButton to="/providers" icon="i-lucide-arrow-left" variant="ghost" :label="text('返回', 'Back')" />
    <ProviderEditor :id="String(route.params.id)" />
  </div>
</template>