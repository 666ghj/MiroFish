import axios from 'axios'
import i18n from '../i18n'

// Create axios instance
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001',
  timeout: 300000, // 5-minute timeout (ontology generation can take a while)
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor
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

// Response interceptor (fault-tolerant retry mechanism)
service.interceptors.response.use(
  response => {
    const res = response.data

    // Throw an error if the response status is not success
    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      return Promise.reject(new Error(res.error || res.message || 'Error'))
    }

    return res
  },
  error => {
    console.error('Response error:', error)
    const apiError = error.response?.data?.error || error.response?.data?.message
    
    // Handle timeouts
    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timeout')
    }

    // Handle network errors
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
