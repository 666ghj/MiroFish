import axios from 'axios'
import i18n from '../i18n'

// 创建axios实例
const service = axios.create({
  // UXE fork: default to same-origin. The previous default
  // ('http://localhost:5001') is resolved by the BROWSER, so opening the UI
  // from any machine other than the server hit that machine's own port 5001
  // and failed. Every request path already starts with '/api', which Vite's
  // dev proxy (vite.config.js) — or any reverse proxy — forwards to the
  // backend. Consequence: only the frontend port needs to be exposed.
  // Set VITE_API_BASE_URL only to target a backend on a different origin.
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    config.headers['Accept-Language'] = i18n.global.locale.value
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器（容错重试机制）
service.interceptors.response.use(
  response => {
    const res = response.data
    
    // 如果返回的状态码不是success，则抛出错误
    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      return Promise.reject(new Error(res.error || res.message || 'Error'))
    }
    
    return res
  },
  error => {
    console.error('Response error:', error)
    const apiError = error.response?.data?.error || error.response?.data?.message
    
    // 处理超时
    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timeout')
    }
    
    // 处理网络错误
    if (error.message === 'Network Error') {
      console.error('Network error - please check your connection')
    }

    // Axios rejects non-2xx responses before the success interceptor can
    // surface the backend's safe, actionable error message.
    if (typeof apiError === 'string' && apiError) {
      error.message = apiError
    }
    
    return Promise.reject(error)
  }
)

export default service
