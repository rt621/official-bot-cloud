<template>
  <main class="login-shell">
    <section class="brand-panel" aria-label="平台介绍">
      <div class="brand-topline">
        <div class="brand-symbol">云</div>
        <div class="brand-wordmark"><strong>官机云</strong><span>OFFICIAL BOT CLOUD</span></div>
      </div>

      <div class="brand-copy">
        <div class="brand-kicker"><i></i> 稳定 · 安全 · 易管理</div>
        <h1>让机器人<br /><span>专注连接每一刻</span></h1>
        <p>一个清晰可靠的云端工作台，轻松管理你的 QQ 官方机器人与服务状态。</p>
      </div>

      <div class="feature-list">
        <div class="feature-item"><span class="feature-icon">↗</span><div><strong>运行状态，一目了然</strong><small>在线情况与实例管理集中呈现</small></div></div>
        <div class="feature-item"><span class="feature-icon">◇</span><div><strong>安全托管，安心使用</strong><small>凭证加密保存，账号独立管理</small></div></div>
      </div>
      <div class="brand-footer"><span>云端运行 · 随时掌握</span><span class="footer-line"></span></div>
      <div class="decor decor-one"></div><div class="decor decor-two"></div>
    </section>

    <section class="form-panel">
      <div class="mobile-brand"><span class="brand-symbol">云</span><strong>官机云</strong></div>
      <el-card class="login-card" shadow="never">
        <div class="form-heading">
          <div class="form-eyebrow">欢迎回来</div>
          <h2>登录你的工作台</h2>
          <p>使用你的平台账号继续管理机器人</p>
        </div>
        <el-tabs v-model="tab" class="auth-tabs">
          <el-tab-pane label="登录" name="login">
            <el-form class="auth-form" @submit.prevent="doLogin">
              <el-form-item label="用户名">
                <el-input v-model="form.username" placeholder="输入用户名" size="large" autocomplete="username" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="form.password" type="password" placeholder="输入密码" size="large"
                  autocomplete="current-password" show-password />
              </el-form-item>
              <el-button type="primary" size="large" class="submit-button" :loading="busy" native-type="submit">
                登录 <span class="button-arrow">→</span>
              </el-button>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="注册" name="register">
            <el-form class="auth-form register-form" @submit.prevent="doRegister">
              <el-form-item label="用户名">
                <el-input v-model="form.username" placeholder="至少 3 个字符" size="large" autocomplete="username" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="form.password" type="password" placeholder="至少 6 个字符" size="large"
                  autocomplete="new-password" show-password />
              </el-form-item>
              <el-form-item label="邮箱地址">
                <el-input v-model="form.email" type="email" placeholder="用于接收注册验证码" size="large" autocomplete="email"
                  :disabled="regMode === 'closed'" />
              </el-form-item>
              <el-form-item label="邮箱验证码">
                <div class="code-row">
                  <el-input v-model="form.email_code" placeholder="输入 6 位验证码" size="large" inputmode="numeric"
                    maxlength="6" autocomplete="one-time-code" :disabled="regMode === 'closed'" />
                  <el-button class="code-button" size="large" :loading="sendingCode"
                    :disabled="regMode === 'closed' || cooldown > 0" @click="sendEmailCode">
                    {{ cooldown > 0 ? `${cooldown}s 后重发` : '发送验证码' }}
                  </el-button>
                </div>
                <div v-if="codeNotice" class="field-hint success-hint">{{ codeNotice }}</div>
              </el-form-item>
              <el-form-item v-if="regMode === 'invite'" label="邀请码">
                <el-input v-model="form.invite_code" placeholder="向平台管理员获取" size="large" autocomplete="off" />
              </el-form-item>
              <el-alert v-if="regMode === 'closed'" title="平台暂未开放注册，请联系管理员开通账号"
                type="warning" show-icon :closable="false" class="form-alert" />
              <div v-if="regMode !== 'closed' && turnstileEnabled" class="turnstile-panel">
                <div ref="turnstileContainer" class="turnstile-container"></div>
                <div v-if="turnstileLoading" class="field-hint">正在加载人机验证…</div>
                <div v-if="turnstileError" class="field-hint error-hint">{{ turnstileError }}</div>
              </div>
              <el-button type="primary" size="large" class="submit-button" :loading="busy" native-type="submit"
                :disabled="regMode === 'closed'">
                创建账号 <span class="button-arrow">→</span>
              </el-button>
            </el-form>
          </el-tab-pane>
        </el-tabs>
        <el-alert v-if="error" :title="error" type="error" show-icon class="form-alert" />
        <div class="form-footnote"><span class="secure-mark">✓</span> 你的账号信息将受到安全保护</div>
      </el-card>
      <div class="copyright">© {{ new Date().getFullYear() }} 官机云平台</div>
    </section>
  </main>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { http, errText } from '../api'

const TURNSTILE_SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
let turnstileScriptPromise

const router = useRouter()
const tab = ref('login')
const busy = ref(false)
const sendingCode = ref(false)
const error = ref('')
const codeNotice = ref('')
const cooldown = ref(0)
const form = reactive({ username: '', password: '', email: '', email_code: '', invite_code: '' })
const regMode = ref('open')
const turnstileEnabled = ref(false)
const turnstileSiteKey = ref('')
const turnstileToken = ref('')
const turnstileLoading = ref(false)
const turnstileError = ref('')
const turnstileContainer = ref(null)
const turnstileWidgetId = ref(null)
let cooldownTimer
let turnstileMountRequest = 0

onMounted(async () => {
  try {
    const data = (await http.get('/auth/registration-mode')).data || {}
    regMode.value = data.mode || 'open'
    turnstileEnabled.value = data.turnstile_enabled === true
    turnstileSiteKey.value = data.turnstile_site_key || ''
    if (turnstileEnabled.value && !turnstileSiteKey.value) {
      turnstileError.value = '人机验证配置不可用，请联系管理员。'
    }
  } catch {
    // 获取失败按开放处理，注册时后端会再校验
  }
})

watch(tab, async (value) => {
  error.value = ''
  if (value === 'register') {
    await nextTick()
    mountTurnstile()
  } else {
    destroyTurnstile()
  }
})

watch([turnstileEnabled, turnstileSiteKey, regMode], async () => {
  if (tab.value === 'register') {
    await nextTick()
    mountTurnstile()
  }
})

onBeforeUnmount(() => {
  clearInterval(cooldownTimer)
  destroyTurnstile()
})

function saveAndGo(data) {
  localStorage.setItem('token', data.token)
  localStorage.setItem('username', data.username)
  router.push('/instances')
}

async function doLogin() {
  busy.value = true
  error.value = ''
  try {
    saveAndGo((await http.post('/auth/login', {
      username: form.username,
      password: form.password,
    })).data)
  } catch (e) {
    error.value = errText(e)
  } finally {
    busy.value = false
  }
}

function validEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

async function sendEmailCode() {
  const email = form.email.trim().toLowerCase()
  error.value = ''
  codeNotice.value = ''
  if (!validEmail(email)) {
    error.value = '请输入正确的邮箱地址'
    return
  }

  sendingCode.value = true
  try {
    const data = (await http.post('/auth/email-code', {
      email,
      turnstile_token: turnstileToken.value,
    })).data || {}
    form.email = email
    startCooldown(data.cooldown_seconds || 60)
    codeNotice.value = '验证码已发送，请检查邮箱（10 分钟内有效）'
    if (turnstileEnabled.value) resetTurnstile()
  } catch (e) {
    error.value = errText(e)
  } finally {
    sendingCode.value = false
  }
}

function startCooldown(seconds) {
  clearInterval(cooldownTimer)
  cooldown.value = Math.max(1, Number(seconds) || 60)
  cooldownTimer = setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) {
      cooldown.value = 0
      clearInterval(cooldownTimer)
    }
  }, 1000)
}

async function doRegister() {
  error.value = ''
  codeNotice.value = ''
  const email = form.email.trim().toLowerCase()
  if (!validEmail(email)) {
    error.value = '请输入正确的邮箱地址'
    return
  }
  if (!/^\d{6}$/.test(form.email_code.trim())) {
    error.value = '请输入 6 位邮箱验证码'
    return
  }
  if (turnstileEnabled.value && !turnstileToken.value) {
    error.value = turnstileError.value || '请先完成人机验证'
    return
  }

  busy.value = true
  try {
    saveAndGo((await http.post('/auth/register', {
      username: form.username,
      password: form.password,
      email,
      email_code: form.email_code.trim(),
      turnstile_token: turnstileToken.value,
      invite_code: form.invite_code,
    })).data)
  } catch (e) {
    error.value = errText(e)
    if (turnstileEnabled.value) resetTurnstile()
  } finally {
    busy.value = false
  }
}

function loadTurnstileScript() {
  if (window.turnstile?.render) return Promise.resolve(window.turnstile)
  if (turnstileScriptPromise) return turnstileScriptPromise

  turnstileScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-turnstile-api]')
    const script = existing || document.createElement('script')
    let settled = false
    const finish = (callback, value) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      callback(value)
    }
    const onLoad = () => {
      if (window.turnstile?.render) finish(resolve, window.turnstile)
      else finish(reject, new Error('Turnstile 脚本未提供组件'))
    }
    const onError = () => finish(reject, new Error('Turnstile 脚本加载失败'))
    const timeout = setTimeout(onError, 10000)
    script.addEventListener('load', onLoad, { once: true })
    script.addEventListener('error', onError, { once: true })
    if (!existing) {
      script.src = TURNSTILE_SCRIPT_URL
      script.async = true
      script.defer = true
      script.dataset.turnstileApi = 'true'
      document.head.appendChild(script)
    }
  }).catch((err) => {
    turnstileScriptPromise = undefined
    throw err
  })

  return turnstileScriptPromise
}

async function mountTurnstile() {
  destroyTurnstile()
  const request = turnstileMountRequest
  if (tab.value !== 'register' || regMode.value === 'closed' || !turnstileEnabled.value) return
  if (!turnstileSiteKey.value) {
    turnstileError.value = '人机验证配置不可用，请联系管理员。'
    return
  }
  turnstileLoading.value = true
  turnstileError.value = ''
  try {
    const turnstile = await loadTurnstileScript()
    if (request !== turnstileMountRequest || !turnstileContainer.value) return
    turnstileWidgetId.value = turnstile.render(turnstileContainer.value, {
      sitekey: turnstileSiteKey.value,
      callback: (token) => {
        turnstileToken.value = token
        turnstileError.value = ''
      },
      'expired-callback': () => {
        turnstileToken.value = ''
        turnstileError.value = '人机验证已过期，请重新验证。'
      },
      'error-callback': () => {
        turnstileToken.value = ''
        turnstileError.value = '人机验证加载失败，请刷新页面重试。'
      },
    })
  } catch (err) {
    if (request === turnstileMountRequest) {
      turnstileError.value = err.message || '人机验证不可用，请刷新页面重试。'
    }
  } finally {
    if (request === turnstileMountRequest) turnstileLoading.value = false
  }
}

function resetTurnstile() {
  turnstileToken.value = ''
  if (turnstileWidgetId.value !== null && window.turnstile?.reset) {
    window.turnstile.reset(turnstileWidgetId.value)
  }
}

function destroyTurnstile() {
  turnstileMountRequest += 1
  turnstileToken.value = ''
  turnstileLoading.value = false
  if (turnstileWidgetId.value !== null && window.turnstile?.remove) {
    window.turnstile.remove(turnstileWidgetId.value)
  }
  turnstileWidgetId.value = null
}
</script>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(360px, .92fr) minmax(480px, 1.08fr);
  background: #f5f7fb;
  color: #26364d;
}
.brand-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 44px clamp(34px, 6vw, 92px) 34px;
  overflow: hidden;
  color: #fff;
  background: linear-gradient(150deg, #183f77 0%, #1d5da4 54%, #327dc2 100%);
  box-sizing: border-box;
}
.brand-topline, .brand-wordmark { display: flex; }
.brand-topline { position: relative; z-index: 1; align-items: center; gap: 12px; }
.brand-symbol { width: 42px; height: 42px; display: grid; place-items: center; border: 1px solid rgba(255,255,255,.3); border-radius: 13px; background: rgba(255,255,255,.13); color: #fff; font-size: 20px; font-weight: 700; box-shadow: 0 8px 20px rgba(8,33,69,.14); }
.brand-wordmark { flex-direction: column; gap: 3px; }
.brand-wordmark strong { font-size: 16px; letter-spacing: .8px; }
.brand-wordmark span { color: rgba(222,238,255,.68); font-size: 9px; letter-spacing: 1.65px; }
.brand-copy { position: relative; z-index: 1; max-width: 470px; margin: auto 0; padding: 44px 0 52px; }
.brand-kicker { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid rgba(224,240,255,.2); border-radius: 99px; background: rgba(238,247,255,.09); color: #d5eaff; font-size: 12px; letter-spacing: .3px; }
.brand-kicker i { width: 6px; height: 6px; border-radius: 50%; background: #7de0bd; box-shadow: 0 0 0 4px rgba(125,224,189,.12); }
.brand-copy h1 { margin: 26px 0 17px; font-size: clamp(36px, 4.2vw, 56px); line-height: 1.23; letter-spacing: -1.7px; font-weight: 650; }
.brand-copy h1 span { color: #a9d6ff; }
.brand-copy p { max-width: 395px; margin: 0; color: rgba(231,242,255,.76); font-size: 15px; line-height: 1.9; }
.feature-list { position: relative; z-index: 1; display: grid; gap: 18px; margin-bottom: 45px; }
.feature-item { display: flex; align-items: center; gap: 13px; }
.feature-icon { width: 36px; height: 36px; display: grid; place-items: center; border: 1px solid rgba(222,240,255,.2); border-radius: 11px; background: rgba(230,244,255,.1); color: #d8ebff; font-size: 19px; }
.feature-item div { display: flex; flex-direction: column; gap: 4px; }
.feature-item strong { font-size: 13px; font-weight: 600; }
.feature-item small { color: rgba(222,238,255,.65); font-size: 11px; }
.brand-footer { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; color: rgba(222,238,255,.58); font-size: 11px; letter-spacing: .4px; }
.footer-line { width: 38px; height: 1px; background: rgba(222,238,255,.42); }
.decor { position: absolute; pointer-events: none; border: 1px solid rgba(215,237,255,.11); border-radius: 50%; }
.decor-one { width: 460px; height: 460px; right: -235px; top: 14%; box-shadow: 0 0 0 44px rgba(215,237,255,.025), 0 0 0 92px rgba(215,237,255,.02); }
.decor-two { width: 250px; height: 250px; right: 10%; bottom: -160px; border-color: rgba(215,237,255,.09); }
.form-panel { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 44px clamp(28px, 7vw, 100px) 24px; box-sizing: border-box; }
.login-card { width: min(100%, 430px); padding: 8px 4px 0; border: 0; border-radius: 16px; background: transparent; }
.form-heading { margin-bottom: 27px; }
.form-eyebrow { margin-bottom: 9px; color: #427dd0; font-size: 12px; font-weight: 650; letter-spacing: .8px; }
.form-heading h2 { margin: 0; color: #24344a; font-size: 27px; font-weight: 680; letter-spacing: -.5px; }
.form-heading p { margin: 9px 0 0; color: #8c99aa; font-size: 13px; }
.auth-tabs :deep(.el-tabs__header) { margin-bottom: 24px; }
.auth-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; background: #e6ebf2; }
.auth-tabs :deep(.el-tabs__item) { height: 43px; color: #8a97a9; font-size: 14px; }
.auth-tabs :deep(.el-tabs__item.is-active) { color: #3478d4; font-weight: 650; }
.auth-tabs :deep(.el-tabs__active-bar) { height: 2px; border-radius: 2px; background: #3478d4; }
.auth-form :deep(.el-form-item) { margin-bottom: 19px; }
.auth-form :deep(.el-form-item__label) { height: auto; margin-bottom: 7px; color: #53627a; font-size: 12px; line-height: 1.3; font-weight: 600; }
.auth-form :deep(.el-input__wrapper) { min-height: 44px; padding: 1px 13px; border-radius: 9px; background: #fff; box-shadow: 0 0 0 1px #e2e8f0 inset; transition: box-shadow .16s ease; }
.auth-form :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px #c9d7e9 inset; }
.auth-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px #6e9fe2 inset, 0 0 0 3px rgba(69,126,211,.09); }
.auth-form :deep(.el-input__inner) { color: #2c3b52; font-size: 13px; }
.auth-form :deep(.el-input__inner::placeholder) { color: #aab4c2; }
.submit-button { width: 100%; height: 47px; margin-top: 6px; border: 0; border-radius: 9px; background: linear-gradient(100deg, #3478d4, #2867bf); box-shadow: 0 8px 17px rgba(49,112,203,.2); font-size: 14px; font-weight: 600; letter-spacing: .3px; }
.submit-button:hover { background: linear-gradient(100deg, #4287e2, #3474c9); box-shadow: 0 10px 20px rgba(49,112,203,.25); }
.button-arrow { float: right; margin-right: 3px; font-size: 17px; font-weight: 400; }
.code-row { display: flex; width: 100%; gap: 9px; }
.code-row :deep(.el-input) { flex: 1; min-width: 0; }
.code-button { flex: 0 0 126px; border-radius: 9px; color: #3677ca; border-color: #d8e5f7; background: #f7faff; font-size: 12px; }
.code-button:hover { color: #2866b8; border-color: #a9c6eb; background: #edf5ff; }
.form-alert { margin: 0 0 13px; }
.turnstile-panel { margin: 0 0 14px; min-height: 66px; }
.turnstile-container { min-height: 65px; display: flex; justify-content: center; }
.field-hint { color: #909399; font-size: 12px; line-height: 18px; margin-top: 5px; }
.success-hint { color: #399268; }
.error-hint { color: #d95c63; }
.form-footnote { display: flex; align-items: center; justify-content: center; gap: 7px; margin-top: 22px; color: #9aa5b4; font-size: 11px; }
.secure-mark { width: 15px; height: 15px; display: grid; place-items: center; border-radius: 50%; color: #4b9d77; background: #e7f5ee; font-size: 10px; font-weight: 700; }
.copyright { margin-top: 27px; color: #a7b0bd; font-size: 10px; letter-spacing: .3px; }
.mobile-brand { display: none; }
@media (max-width: 900px) {
  .login-shell { grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); }
  .brand-panel { padding-right: 35px; padding-left: 35px; }
  .form-panel { padding-right: 42px; padding-left: 42px; }
}
@media (max-width: 720px) {
  .login-shell { display: block; min-height: 100vh; padding: 0 20px 22px; background: linear-gradient(180deg, #1e5a99 0, #1e5a99 220px, #f5f7fb 220px); }
  .brand-panel { display: none; }
  .form-panel { min-height: 100vh; justify-content: flex-start; padding: 26px 0 10px; }
  .mobile-brand { display: flex; align-items: center; gap: 10px; width: min(100%, 430px); margin: 0 auto 22px; color: #fff; font-size: 15px; letter-spacing: .4px; }
  .mobile-brand .brand-symbol { width: 35px; height: 35px; border-radius: 11px; font-size: 17px; }
  .login-card { padding: 26px 24px 20px; border: 1px solid #edf0f5; border-radius: 15px; background: #fff; box-shadow: 0 15px 38px rgba(27,56,95,.12); }
  .form-heading { margin-bottom: 22px; }
  .form-heading h2 { font-size: 24px; }
  .copyright { margin-top: 18px; color: #9ba6b4; }
}
@media (max-width: 420px) {
  .login-shell { padding-right: 14px; padding-left: 14px; }
  .login-card { padding: 23px 18px 18px; }
  .form-heading h2 { font-size: 22px; }
  .code-button { flex-basis: 112px; padding-right: 9px; padding-left: 9px; }
  .auth-tabs :deep(.el-tabs__header) { margin-bottom: 20px; }
}
</style>
