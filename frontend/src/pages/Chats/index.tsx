import { motion } from 'framer-motion'
import { pageEnter } from '@/shared/animations/pageTransitions'

export default function ChatsPage() {
  return (
    <motion.div {...pageEnter} style={{ padding: 24, color: 'var(--text-primary)' }}>
      <h1>Chats</h1>
    </motion.div>
  )
}
