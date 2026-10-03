<script setup lang="ts">
type Message = { role: 'user' | 'assistant', content: string }
type ChatModel = { id: string, display_name?: string }
const api = useApi()
const { text } = useUiLocale()
const toast = useToast()
const chatToken = ref('')
const tokenDraft = ref('')
const models = ref<ChatModel[]>([])
const model = ref('')
const messages = ref<Message[]>([])
const input = ref('')
const system = ref('')
const busy = ref(false)
const loadingModels = ref(false)
const usage = ref<{ prompt_tokens: number, completion_tokens: number } | null>(null)
const thread = ref<HTMLElement | null>(null)
let controller: AbortController | null = null
onMounted(() => { chatToken.value = localStorage.getItem('voidswitch.chat_token') || '' })
watch(chatToken, value => {
  if (value) localStorage.setItem('voidswitch.chat_token', value)
  else localStorage.removeItem('voidswitch.chat_token')
  if (import.meta.client) void loadModels()
})
watch(messages, () => nextTick(() => { if (thread.value) thread.value.scrollTop = thread.value.scrollHeight }), { deep: true })
onUnmounted(() => controller?.abort())
async function loadModels() {
  if (!chatToken.value) { models.value = []; model.value = ''; return }
  loadingModels.value = true
  try {
    const response = await fetch(`${api.base}/v1/models`, { headers: { Authorization: `Bearer ${chatToken.value}` }, cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const result = await response.json() as { data: ChatModel[] }
    models.value = result.data || []
    if (!models.value.some(item => item.id === model.value)) model.value = models.value[0]?.id || ''
  } catch (error) { models.value = []; toast.add({ title: String(error), color: 'error' }) }
  finally { loadingModels.value = false }
}
async function createToken() {
  try {
    const result = await api.post<{ token: string }>('/api/me/tokens', { name: 'dashboard-chat' })
    chatToken.value = result.token
    toast.add({ title: text('已创建聊天令牌', 'Chat token created'), color: 'success' })
  } catch (error) { toast.add({ title: String(error), color: 'error' }) }
}
function saveToken() { chatToken.value = tokenDraft.value.trim(); tokenDraft.value = '' }
function stop() { controller?.abort() }
function composerKey(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }
async function send() {
  const content = input.value.trim()
  if (!content || busy.value || !chatToken.value || !model.value) return
  const previous = [...messages.value, { role: 'user' as const, content }]
  messages.value = [...previous, { role: 'assistant', content: '' }]
  input.value = ''
  usage.value = null
  busy.value = true
  controller = new AbortController()
  try {
    const outbound = system.value.trim() ? [{ role: 'system', content: system.value.trim() }, ...previous] : previous
    const response = await fetch(`${api.base}/v1/chat/completions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${chatToken.value}` },
      body: JSON.stringify({ model: model.value, messages: outbound, stream: true, stream_options: { include_usage: true } }),
      signal: controller.signal, cache: 'no-store'
    })
    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.error?.message || error.detail || `HTTP ${response.status}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (!data || data === '[DONE]') continue
          try {
            const event = JSON.parse(data) as { choices?: { delta?: { content?: string } }[], usage?: { prompt_tokens: number, completion_tokens: number } }
            const delta = event.choices?.[0]?.delta?.content
            if (delta) messages.value[messages.value.length - 1]!.content += delta
            if (event.usage) usage.value = event.usage
          } catch { /* ignore malformed keep-alives */ }
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
  } catch (error) {
    if (!controller.signal.aborted) { toast.add({ title: String(error), color: 'error' }); if (!messages.value.at(-1)?.content) messages.value.pop() }
  } finally { busy.value = false; controller = null }
}
</script>
<template>
  <div class="flex h-[calc(100vh-7rem)] min-h-96 flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2"><h1 class="flex-1 text-2xl font-bold">{{ text('聊天', 'Chat') }}</h1><UButton variant="ghost" icon="i-lucide-plus" :label="text('新会话', 'New chat')" @click="messages = []; usage = null" /></div>
    <UCard v-if="!chatToken" class="max-w-xl space-y-3"><h2 class="font-semibold">{{ text('选择聊天令牌', 'Choose a chat token') }}</h2><p class="text-sm text-muted">{{ text('聊天通过个人 Void-Token 调用网关。', 'Chat uses a personal Void-Token to call the gateway.') }}</p><UButton :label="text('创建聊天令牌', 'Create chat token')" @click="createToken" /><form class="flex flex-wrap gap-2" @submit.prevent="saveToken"><UInput v-model="tokenDraft" type="password" :placeholder="text('已有 Void-Token', 'Existing Void-Token')" /><UButton type="submit" variant="outline" :label="text('使用', 'Use token')" /></form></UCard>
    <template v-else>
      <div class="flex flex-wrap items-center gap-2"><USelect v-model="model" value-key="value" :items="models.map(item => ({ label: item.display_name || item.id, value: item.id }))" :loading="loadingModels" :placeholder="text('选择模型', 'Select model')" class="min-w-48 flex-1" /><UButton variant="ghost" icon="i-lucide-refresh-cw" :aria-label="text('刷新模型', 'Refresh models')" @click="loadModels" /><UButton variant="ghost" icon="i-lucide-key-round" :label="text('更换令牌', 'Change token')" @click="chatToken = ''" /></div>
      <UInput v-model="system" :placeholder="text('系统提示（可选）', 'System prompt (optional)')" class="w-full" />
      <div ref="thread" class="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-lg border border-default p-4">
        <div v-for="(message, index) in messages" :key="index" class="max-w-3xl rounded-lg p-3" :class="message.role === 'user' ? 'ml-auto bg-primary/10' : 'bg-elevated'"><div class="mb-1 text-xs font-semibold text-muted">{{ message.role === 'user' ? text('你', 'You') : text('助手', 'Assistant') }}</div><p class="whitespace-pre-wrap break-words">{{ message.content || '…' }}</p></div>
      </div>
      <div v-if="usage" class="text-right text-xs text-muted">{{ usage.prompt_tokens }} + {{ usage.completion_tokens }} tokens</div>
      <form class="flex items-end gap-2" @submit.prevent="send"><UTextarea v-model="input" :placeholder="text('输入消息，Enter 发送', 'Message, Enter to send')" class="min-w-0 flex-1" :rows="2" @keydown="composerKey" /><UButton v-if="busy" type="button" color="error" variant="outline" icon="i-lucide-square" :label="text('停止', 'Stop')" @click="stop" /><UButton v-else type="submit" icon="i-lucide-send" :disabled="!model || !input.trim()" :label="text('发送', 'Send')" /></form>
    </template>
  </div>
</template>
