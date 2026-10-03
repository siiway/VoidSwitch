<script setup lang="ts">
import type { DrawerEntry } from '../composables/useDrawers'
defineProps<{ entry: DrawerEntry }>()
const { text } = useUiLocale()
</script>
<template>
  <div v-if="entry.kind === 'provider'" class="space-y-4"><ProviderEditor :id="entry.id" /></div>
  <div v-else-if="entry.kind === 'model'" class="space-y-4"><ModelDetail :id="entry.id!" /></div>
  <div v-else-if="entry.kind === 'route'" class="space-y-4"><RouteEditor :id="entry.id!" /></div>
  <UAlert v-else color="warning" :title="text('此操作仍在迁移中', 'This action is being migrated')" />
</template>
