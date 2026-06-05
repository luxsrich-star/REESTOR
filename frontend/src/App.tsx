import { BrowserRouter } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { QueryProvider } from './app/providers/QueryProvider'
import { ThemeProvider } from './app/providers/ThemeProvider'
import { TelegramProvider } from './app/providers/TelegramProvider'
import { AppRouter } from './app/router/routes'

export default function App() {
  return (
    <TelegramProvider>
      <QueryProvider>
        <ThemeProvider>
          <BrowserRouter>
            <AnimatePresence mode="wait">
              <AppRouter />
            </AnimatePresence>
          </BrowserRouter>
        </ThemeProvider>
      </QueryProvider>
    </TelegramProvider>
  )
}
