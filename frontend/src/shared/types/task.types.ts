import type { Account } from './account.types'
import type { Chat } from './chat.types'
import type { Template } from './template.types'

export interface Task {
  id: string
  userId: string
  accountId: string
  templateId?: string
  title: string
  chatIds: string[]
  schedule: string
  timezone: string
  status: 'active' | 'paused' | 'completed' | 'error'
  runCount: number
  lastRunAt?: string
  nextRunAt?: string
  errorMessage?: string
  mentionBlastConfig?: MentionBlastConfig
  createdAt: string
  updatedAt: string
  account?: Account
  template?: Template
  chats?: Chat[]
}

export interface MentionBlastConfig {
  enabled: boolean
  participantsLimit: number
  editDelaySeconds: number
}

export interface TaskLog {
  id: string
  taskId: string
  status: 'success' | 'error' | 'skipped'
  chatId?: string
  message?: string
  error?: string
  executedAt: string
}
