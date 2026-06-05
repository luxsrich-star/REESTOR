import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function SplashScreen() {
  const navigate = useNavigate()

  useEffect(() => {
    const timer = setTimeout(() => navigate('/dashboard'), 3200)
    return () => clearTimeout(timer)
  }, [navigate])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      style={{
        height: '100vh',
        background: '#070810',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 24,
      }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.75, filter: 'blur(12px)' }}
        animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
        transition={{ duration: 0.7, delay: 0.2 }}
        style={{ color: '#fff', fontSize: 64, fontWeight: 700, letterSpacing: '-0.02em' }}
      >
        R
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4 }}
        style={{ width: 280, height: 3, background: 'rgba(255,255,255,0.1)', borderRadius: 2 }}
      >
        <motion.div
          initial={{ width: '0%' }}
          animate={{ width: '100%' }}
          transition={{ duration: 2.5, ease: [0.4, 0, 0.2, 1] }}
          style={{ height: '100%', background: '#3D6FFF', borderRadius: 2 }}
        />
      </motion.div>
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4 }}
        style={{ color: 'rgba(255,255,255,0.5)', fontSize: 13 }}
      >
        Загрузка приложения...
      </motion.p>
    </motion.div>
  )
}
