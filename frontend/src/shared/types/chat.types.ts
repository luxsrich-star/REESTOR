export interface Chat {
  id: string
  accountId: string
  telegramChatId: number
  title: string
  type: 'personal' | 'group' | 'supergroup' | 'channel'
  username?: string
  photoUrl?: string
  membersCount?: number
  isFavorite: boolean
  lastMessageAt?: string
}
