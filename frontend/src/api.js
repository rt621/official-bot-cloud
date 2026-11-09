import axios from 'axios'

export const http = axios.create({ baseURL: '/api' })

http.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg =
      err.response && err.response.data && err.response.data.detail
        ? typeof err.response.data.detail === 'string'
          ? err.response.data.detail
          : JSON.stringify(err.response.data.detail)
        : (err.message || '请求失败')
    err.friendly = msg
    // 登录态失效（token 过期/账号被删）时自动登出回登录页，避免卡在空页面
    if (
      err.response && err.response.status === 401 &&
      !String(err.config?.url || '').includes('/auth/login')
    ) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export function errText(err) {
  return err.friendly || String(err)
}
