import { motion } from 'framer-motion'
import { pageEnter } from '@/shared/animations/pageTransitions'

export default function DashboardPage() {
  return (
    <motion.div {...pageEnter} style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h1>Dashboard</h1>
    </motion.div>
  )
}
