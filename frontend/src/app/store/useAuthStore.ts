import { create } from 'zustand'

interface User {
  id: string
  telegramId: number
  firstName: string
  lastName?: string
  username?: string
  photoUrl?: string
  plan: 'free' | 'pro' | 'business'
}

interface AuthStore {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  setAuth: (user: User, token: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  setAuth: (user, accessToken) => set({ user, accessToken, isAuthenticated: true }),
  logout: () => set({ user: null, accessToken: null, isAuthenticated: false }),
}))
