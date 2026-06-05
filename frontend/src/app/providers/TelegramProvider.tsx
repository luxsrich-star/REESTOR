import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import WebApp from '@twa-dev/sdk'

interface TelegramUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  language_code?: string
}

interface TelegramContextValue {
  user: TelegramUser | null
  isReady: boolean
  initData: string
}

const TelegramContext = createContext<TelegramContextValue>({
  user: null,
  isReady: false,
  initData: '',
})

export function TelegramProvider({ children }: { children: ReactNode }) {
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    WebApp.ready()
    setIsReady(true)
  }, [])

  const user = WebApp.initDataUnsafe?.user as TelegramUser | null

  return (
    <TelegramContext.Provider value={{ user, isReady, initData: WebApp.initData }}>
      {children}
    </TelegramContext.Provider>
  )
}

export const useTelegram = () => useContext(TelegramContext)
