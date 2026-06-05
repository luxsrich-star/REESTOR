import { springs } from './springs'

export const pageEnter = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: springs.smooth,
}

export const pageSlideForward = {
  initial: { opacity: 0, x: 40 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -40 },
  transition: springs.default,
}

export const staggerContainer = {
  animate: {
    transition: { staggerChildren: 0.06, delayChildren: 0.1 },
  },
}

export const staggerItem = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
}
