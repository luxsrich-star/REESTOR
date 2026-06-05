export interface Account {
  id: string
  userId: string
  phone: string
  telegramUserId?: number
  firstName?: string
  lastName?: string
  username?: string
  photoUrl?: string
  status: 'pending' | 'active' | 'error' | 'paused'
  errorMessage?: string
  chatsCount: number
  lastSyncedAt?: string
  createdAt: string
  updatedAt: string
}
