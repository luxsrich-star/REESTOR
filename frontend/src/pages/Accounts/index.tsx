import { motion } from 'framer-motion'
import { pageEnter } from '@/shared/animations/pageTransitions'

export default function AccountsPage() {
  return (
    <motion.div {...pageEnter} style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h1>Accounts</h1>
    </motion.div>
  )
}
