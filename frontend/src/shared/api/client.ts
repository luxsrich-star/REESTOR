import axios from 'axios'
import WebApp from '@twa-dev/sdk'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 10000,
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  config.headers['X-Telegram-Init-Data'] = WebApp.initData
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)
