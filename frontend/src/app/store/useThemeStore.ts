import { create } from 'zustand'

type Theme = 'dark' | 'light'

interface ThemeStore {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggle: () => void
}

export const useThemeStore = create<ThemeStore>((set, get) => ({
  theme: 'dark',
  setTheme: (theme) => set({ theme }),
  toggle: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
}))
