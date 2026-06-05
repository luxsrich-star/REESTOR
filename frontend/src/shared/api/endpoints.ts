export const ENDPOINTS = {
  AUTH: {
    TELEGRAM: '/auth/telegram',
    REFRESH: '/auth/refresh',
    LOGOUT: '/auth/logout',
  },
  ACCOUNTS: {
    LIST: '/accounts',
    SEND_CODE: '/accounts/send-code',
    VERIFY_CODE: '/accounts/verify-code',
    VERIFY_2FA: '/accounts/verify-2fa',
    BY_ID: (id: string) => `/accounts/${id}`,
    SYNC: (id: string) => `/accounts/${id}/sync`,
  },
  CHATS: {
    LIST: '/chats',
    BY_ID: (id: string) => `/chats/${id}`,
    FAVORITE: (id: string) => `/chats/${id}/favorite`,
  },
  TEMPLATES: {
    LIST: '/templates',
    CREATE: '/templates',
    BY_ID: (id: string) => `/templates/${id}`,
    DUPLICATE: (id: string) => `/templates/${id}/duplicate`,
  },
  TASKS: {
    LIST: '/tasks',
    CREATE: '/tasks',
    BY_ID: (id: string) => `/tasks/${id}`,
    PAUSE: (id: string) => `/tasks/${id}/pause`,
    RESUME: (id: string) => `/tasks/${id}/resume`,
    RUN: (id: string) => `/tasks/${id}/run`,
    LOGS: (id: string) => `/tasks/${id}/logs`,
  },
  ANALYTICS: {
    OVERVIEW: '/analytics/overview',
    TOP_CHATS: '/analytics/top-chats',
  },
}
