import axios from 'axios'
import i18n from '../i18n'

// 创建axios实例
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001',
  timeout: 600000, // 10分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 返回拦截器可复用的本地化错误文案（i18n 键缺失时回退到默认文案）
const translateApiError = (key, fallback) => {
  try {
    const translated = i18n.global.t(key)
    return translated && translated !== key ? translated : fallback
  } catch {
    return fallback
  }
}

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
    
    // 处理超时：转换为用户可读、可翻译的提示（调用方通过 err.message 展示）
    if (error.code === 'ECONNABORTED' && error.message?.includes('timeout')) {
      console.error('Request timeout')
      error.message = translateApiError('api.requestTimeout', 'Request timed out. Please try again later.')
    }
    
    // 处理网络错误：同样转换为可翻译的用户提示
    if (error.message === 'Network Error') {
      console.error('Network error - please check your connection')
      error.message = translateApiError('api.networkError', 'Network error. Please check your connection and retry.')
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
