export type Locale = 'zh' | 'en'
export function useUiLocale() {
  const locale = useState<Locale>('locale', () => 'zh')
  function load() { locale.value = localStorage.getItem('vs.locale') === 'en' ? 'en' : 'zh' }
  function toggle() { locale.value = locale.value === 'zh' ? 'en' : 'zh'; localStorage.setItem('vs.locale', locale.value) }
  function text(zh: string, en: string) { return locale.value === 'zh' ? zh : en }
  return { locale, load, toggle, text }
}
