<script setup lang="ts">
const props = defineProps<{ fields: { key: string, label: string }[], modelValue: Record<string, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string>] }>()
const available = computed(() => props.fields.filter(field => !(field.key in props.modelValue)).map(field => ({ label: field.label, onSelect: () => emit('update:modelValue', { ...props.modelValue, [field.key]: '' }) })))
function update(key: string, value: string) { emit('update:modelValue', { ...props.modelValue, [key]: value }) }
function remove(key: string) { const next = { ...props.modelValue }; delete next[key]; emit('update:modelValue', next) }
</script>
<template>
  <div class="flex flex-wrap items-center gap-2">
    <div v-for="field in fields.filter(item => item.key in modelValue)" :key="field.key" class="flex items-center gap-2 rounded border border-default p-1">
      <label class="text-xs text-muted">{{ field.label }}</label>
      <UInput :model-value="modelValue[field.key]" size="sm" class="w-28" @update:model-value="update(field.key, String($event))" />
      <UButton size="xs" variant="ghost" color="neutral" icon="i-lucide-x" :aria-label="`Remove ${field.label}`" @click="remove(field.key)" />
    </div>
    <UDropdownMenu v-if="available.length" :items="available"><UButton icon="i-lucide-plus" size="sm" variant="outline" color="neutral" aria-label="Add condition" /></UDropdownMenu>
  </div>
</template>
