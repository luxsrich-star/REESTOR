import { motion } from 'framer-motion'
import { pageEnter } from '@/shared/animations/pageTransitions'

export default function TasksPage() {
  return (
    <motion.div {...pageEnter} style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h1>Tasks</h1>
    </motion.div>
  )
}
