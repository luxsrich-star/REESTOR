import { motion } from 'framer-motion'
import { pageEnter } from '@/shared/animations/pageTransitions'

export default function TemplatesPage() {
  return (
    <motion.div {...pageEnter} style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h1>Templates</h1>
    </motion.div>
  )
}
