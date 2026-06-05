import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

const SplashScreen = lazy(() => import('@/pages/SplashScreen'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Accounts = lazy(() => import('@/pages/Accounts'))
const Chats = lazy(() => import('@/pages/Chats'))
const Tasks = lazy(() => import('@/pages/Tasks'))
const Analytics = lazy(() => import('@/pages/Analytics'))
const Profile = lazy(() => import('@/pages/Profile'))
const Templates = lazy(() => import('@/pages/Templates'))

export function AppRouter() {
  return (
    <Suspense fallback={null}>
      <Routes>
        <Route path="/" element={<SplashScreen />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/chats" element={<Chats />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
