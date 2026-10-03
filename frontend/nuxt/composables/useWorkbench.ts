export type PrefixCategory = 'pages' | 'models' | 'providers' | 'users'
export type WorkbenchPrefs = { detailMode: 'drawer' | 'page', prefixes: Record<PrefixCategory, string> }

export const defaultPrefs: WorkbenchPrefs = {
  detailMode: 'drawer',
  prefixes: { pages: '/', models: '!', providers: '@', users: '#' }
}

export function useWorkbench() {
  const { user } = useSession()
  const prefs = useState<WorkbenchPrefs>('workbench-prefs', () => ({ ...defaultPrefs, prefixes: { ...defaultPrefs.prefixes } }))
  const key = computed(() => `vs.workbench.${user.value?.id ?? 'anonymous'}`)
  function load() {
    const raw = localStorage.getItem(key.value)
    if (!raw) { prefs.value = { ...defaultPrefs, prefixes: { ...defaultPrefs.prefixes } }; return }
    try {
      const value = JSON.parse(raw) as WorkbenchPrefs
      const prefixes = { ...defaultPrefs.prefixes, ...value.prefixes }
      const chars = Object.values(prefixes)
      if (chars.some((v) => v.length !== 1 || /\s/.test(v)) || new Set(chars).size !== chars.length) throw new Error('Invalid prefixes')
      prefs.value = { detailMode: value.detailMode === 'page' ? 'page' : 'drawer', prefixes }
    } catch { prefs.value = { ...defaultPrefs, prefixes: { ...defaultPrefs.prefixes } } }
  }
  function save() { localStorage.setItem(key.value, JSON.stringify(prefs.value)) }
  return { prefs, load, save }
}
