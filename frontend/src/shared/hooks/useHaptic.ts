import WebApp from '@twa-dev/sdk'

export function useHaptic() {
  const impact = (style: 'light' | 'medium' | 'heavy' = 'light') => {
    WebApp.HapticFeedback.impactOccurred(style)
  }
  const notification = (type: 'error' | 'success' | 'warning') => {
    WebApp.HapticFeedback.notificationOccurred(type)
  }
  return { impact, notification }
}
