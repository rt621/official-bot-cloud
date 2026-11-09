<template>
  <div class="page">
    <el-container>
      <el-header class="header">
        <div class="brand-lockup">
          <span class="brand-mark">云</span>
          <div><span class="title">官机云</span><span class="brand-caption">机器人托管平台</span></div>
        </div>
        <span class="header-spacer"></span>
        <el-button v-if="isAdmin" size="small" type="warning" plain class="admin-button" @click="$router.push('/admin')">平台管理</el-button>
        <span class="username-chip">{{ username }}</span>
        <el-button link class="logout-button" @click="logout">退出登录</el-button>
      </el-header>
      <el-main>
        <el-alert v-if="announcement" :title="'平台公告：' + announcement" type="warning"
          show-icon :closable="false" style="margin-bottom: 16px" />
        <section class="subscription" v-loading="accountLoading || plansLoading">
          <div class="subscription-head">
            <div class="subscription-title-wrap">
              <span class="subscription-icon">✦</span>
              <div>
                <div class="section-title">账号套餐</div>
                <div class="section-sub">当前有效期：<strong :class="accountExpired ? 'expired' : ''">{{ expiryText }}</strong></div>
              </div>
            </div>
            <el-button v-if="order" size="small" plain :loading="orderLoading" @click="refreshOrder">刷新订单</el-button>
          </div>
          <div v-if="order" class="order-state">
            <div><span class="muted">最近订单</span> <strong>{{ order.out_trade_no }}</strong></div>
            <div class="order-details">
              <el-tag :type="orderTagType(order.status)" size="small">{{ orderStatusText(order.status) }}</el-tag>
              <span v-if="order.amount != null" class="muted">{{ formatPrice(order.amount) }}</span>
              <el-button v-if="orderPayUrl" link type="primary" @click="openPayUrl">继续支付</el-button>
            </div>
          </div>
          <el-empty v-if="!plansLoading && !plans.length" description="暂无可购买套餐" :image-size="56" />
          <div v-else class="plan-grid">
            <el-card v-for="plan in plans" :key="plan.id" class="plan-card" shadow="never">
              <div class="plan-name">{{ plan.name || plan.title || '服务套餐' }}</div>
              <div class="plan-price">¥{{ formatPrice(plan.price ?? plan.amount ?? 0) }}<span v-if="plan.duration_days"> / {{ plan.duration_days }} 天</span></div>
              <div class="plan-description">{{ plan.description || plan.desc || plan.duration || '购买后自动延长账号有效期' }}</div>
              <el-button type="primary" :loading="creatingPlan === plan.id" :disabled="!!creatingPlan" @click="createOrder(plan)">去支付</el-button>
            </el-card>
          </div>
        </section>
        <div class="page-head">
          <div class="page-heading-copy">
            <div class="eyebrow">运行总览</div>
            <div class="page-title">我的机器人</div>
            <div class="page-sub">查看在线状态，并管理你的 QQ 官方机器人实例</div>
          </div>
          <div class="page-head-actions">
            <span class="refresh-note" :class="{ refreshing }"><i class="refresh-dot"></i>{{ refreshLabel }}</span>
            <el-button type="primary" class="bind-button" @click="bindVisible = true">
              <el-icon style="margin-right: 6px"><Plus /></el-icon>绑定机器人
            </el-button>
          </div>
        </div>

        <div v-if="initialLoading && !items.length" class="bot-grid bot-grid-loading">
          <el-card v-for="n in 2" :key="n" class="bot-card skeleton-card" shadow="never">
            <el-skeleton :rows="3" animated />
          </el-card>
        </div>
        <div v-else-if="!items.length" class="empty-wrap">
          <el-empty description="还没有绑定机器人">
            <el-button type="primary" @click="bindVisible = true">绑定第一个机器人</el-button>
          </el-empty>
        </div>

        <div v-else class="bot-grid">
          <el-card v-for="row in items" :key="row.id" class="bot-card" shadow="hover">
            <div class="bot-top">
              <div class="bot-avatar" :class="'av-' + row.status">🤖</div>
              <div class="bot-id">
                <div class="bot-name">
                  {{ row.name || row.appid }}
                  <span class="status-line" :class="'st-' + row.status">
                    <i class="dot"></i>{{ statusText(row.status) }}
                  </span>
                </div>
                <div class="bot-appid">AppID {{ row.appid }}</div>
              </div>
            </div>
            <div class="bot-meta">
              <div class="meta-row"><span class="meta-label">详情</span><span class="meta-val">{{ row.status_detail || '—' }}</span></div>
              <div class="meta-row"><span class="meta-label">最后在线</span><span class="meta-val">{{ fmtTime(row.last_online_at) }}</span></div>
            </div>
            <div class="bot-actions">
              <el-button size="small" type="primary" @click="$router.push(`/instances/${row.id}`)">管理</el-button>
              <el-button size="small" type="success" plain :disabled="row.status === 'online'" @click="act(row, 'start')">启动</el-button>
              <el-button size="small" type="warning" plain @click="act(row, 'stop')">停止</el-button>
              <el-button size="small" plain @click="act(row, 'restart')">重启</el-button>
              <el-button size="small" plain @click="openCred(row)">改凭证</el-button>
              <el-popconfirm title="确定解绑该机器人？实例配置将全部删除。" width="240" @confirm="unbind(row)">
                <template #reference>
                  <el-button size="small" type="danger" plain>解绑</el-button>
                </template>
              </el-popconfirm>
            </div>
          </el-card>
        </div>
      </el-main>
    </el-container>

    <el-dialog v-model="credVisible" title="更新机器人凭证" width="min(480px, calc(100vw - 28px))">
      <el-form label-width="110">
        <el-form-item label="AppID">
          <el-input v-model="credForm.appid" placeholder="开放平台机器人 AppID（一般不用改）" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input v-model="credForm.app_secret" type="password" show-password placeholder="开放平台当前的 AppSecret" />
        </el-form-item>
        <el-form-item label="备注名称">
          <el-input v-model="credForm.name" placeholder="选填" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false"
        title="到 q.qq.com → 机器人管理 → 开发设置，复制 AppID 和 AppSecret 填到这里。保存时平台先向官方校验，通过后自动重连；改 AppID 等于换绑到另一台机器人，原有配置保留。" />
      <template #footer>
        <el-button @click="credVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="doUpdateCred">校验并保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bindVisible" title="绑定机器人" width="min(480px, calc(100vw - 28px))">
      <el-form label-width="110">
        <el-form-item label="AppID">
          <el-input v-model="bind.appid" placeholder="开放平台机器人 AppID" />
        </el-form-item>
        <el-form-item label="AppSecret">
          <el-input v-model="bind.app_secret" type="password" show-password placeholder="开放平台机器人 AppSecret" />
        </el-form-item>
        <el-form-item label="备注名称">
          <el-input v-model="bind.name" placeholder="选填" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" title="凭证仅用于连接你的机器人，平台加密存储且页面不回显。" />
      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="doBind">校验并绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { http, errText } from '../api'

const router = useRouter()
const items = ref([])
const initialLoading = ref(true)
const refreshing = ref(false)
const lastUpdatedAt = ref(null)
const refreshFailed = ref(false)
const busy = ref(false)
const bindVisible = ref(false)
const username = localStorage.getItem('username') || ''
const isAdmin = ref(false)
const announcement = ref('')
const accountLoading = ref(false)
const plansLoading = ref(false)
const orderLoading = ref(false)
const creatingPlan = ref(null)
const account = ref(null)
const plans = ref([])
const order = ref(null)
const orderPayUrl = ref('')
const bind = reactive({ appid: '', app_secret: '', name: '' })
let timer = null
let orderTimer = null
let listRequestInFlight = false
let pageActive = true

const refreshLabel = computed(() => {
  if (refreshing.value) return '正在同步状态'
  if (refreshFailed.value) return '同步失败，将自动重试'
  if (!lastUpdatedAt.value) return '连接中'
  return `最近更新 ${lastUpdatedAt.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
})

const accountExpired = computed(() => account.value?.expires_at && new Date(account.value.expires_at) <= new Date())
const expiryText = computed(() => !account.value ? '读取中' : account.value.expires_at ? fmtTime(account.value.expires_at) : '永久有效')

const STATUS = {
  online: ['success', '在线'],
  connecting: ['warning', '连接中'],
  offline: ['info', '离线'],
  error: ['danger', '异常'],
  disabled: ['info', '已停用'],
}
function statusText(s) { return (STATUS[s] || STATUS.offline)[1] }
function fmtTime(t) { return t ? t.replace('T', ' ').slice(0, 19) : '—' }
function formatPrice(value) {
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toFixed(2) : String(value)
}
function unwrapList(data) { return Array.isArray(data) ? data : data?.items || data?.plans || [] }
function orderStatusText(status) {
  return ({ pending: '待支付', unpaid: '待支付', paid: '已支付', success: '已支付', completed: '已完成', failed: '支付失败', cancelled: '已取消', expired: '已过期' })[String(status || '').toLowerCase()] || status || '处理中'
}
function orderTagType(status) {
  const value = String(status || '').toLowerCase()
  return ['paid', 'success', 'completed'].includes(value) ? 'success' : ['failed', 'cancelled', 'expired'].includes(value) ? 'danger' : 'warning'
}

async function loadSubscription() {
  accountLoading.value = plansLoading.value = true
  const results = await Promise.allSettled([http.get('/auth/me'), http.get('/payment/plans')])
  if (results[0].status === 'fulfilled') account.value = results[0].value.data
  else ElMessage.error(errText(results[0].reason))
  if (results[1].status === 'fulfilled') plans.value = unwrapList(results[1].value.data)
  else ElMessage.error(errText(results[1].reason))
  accountLoading.value = plansLoading.value = false
}

async function createOrder(plan) {
  creatingPlan.value = plan.id
  try {
    const response = await http.post('/payment/orders', { plan_id: plan.id })
    order.value = response.data.order || response.data
    orderPayUrl.value = order.value.pay_url || order.value.payment_url || order.value.checkout_url || order.value.pay_link || ''
    if (orderPayUrl.value) window.open(orderPayUrl.value, '_blank', 'noopener,noreferrer')
    ElMessage.success(orderPayUrl.value ? '订单已创建，请完成支付' : '订单已创建')
    startOrderPolling()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    creatingPlan.value = null
  }
}

function openPayUrl() {
  if (orderPayUrl.value) window.open(orderPayUrl.value, '_blank', 'noopener,noreferrer')
}

async function refreshOrder() {
  if (!order.value?.out_trade_no) return
  orderLoading.value = true
  try {
    const response = await http.get(`/payment/orders/${encodeURIComponent(order.value.out_trade_no)}`)
    order.value = response.data.order || response.data
    orderPayUrl.value = order.value.pay_url || order.value.payment_url || order.value.checkout_url || order.value.pay_link || orderPayUrl.value
    if (['paid', 'success', 'completed'].includes(String(order.value.status || '').toLowerCase())) {
      clearInterval(orderTimer)
      orderTimer = null
      await loadSubscription()
    }
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    orderLoading.value = false
  }
}

function startOrderPolling() {
  clearInterval(orderTimer)
  refreshOrder()
  orderTimer = setInterval(refreshOrder, 5000)
}

async function load() {
  if (listRequestInFlight) return
  listRequestInFlight = true
  refreshing.value = true
  refreshFailed.value = false
  try {
    const nextItems = (await http.get('/instances')).data.items || []
    const changed = nextItems.length !== items.value.length || nextItems.some((next, index) => {
      const current = items.value[index]
      return !current || ['id', 'appid', 'name', 'enabled', 'status', 'status_detail', 'last_online_at']
        .some((key) => current[key] !== next[key])
    })
    if (changed) items.value = nextItems
    lastUpdatedAt.value = new Date()
  } catch (e) {
    refreshFailed.value = true
    if (!items.value.length) ElMessage.error(errText(e))
  } finally {
    initialLoading.value = false
    refreshing.value = false
    listRequestInFlight = false
  }
}

function scheduleNextRefresh() {
  clearTimeout(timer)
  if (pageActive) timer = setTimeout(refreshInstances, 8000)
}

async function refreshInstances() {
  clearTimeout(timer)
  await load()
  scheduleNextRefresh()
}

async function doBind() {
  busy.value = true
  try {
    await http.post('/instances', bind)
    bindVisible.value = false
    bind.appid = bind.app_secret = bind.name = ''
    ElMessage.success('绑定成功')
    refreshInstances()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

async function act(row, action) {
  try {
    await http.post(`/instances/${row.id}/${action}`)
    ElMessage.success(action === 'stop' ? '已停止' : '指令已执行')
    setTimeout(refreshInstances, 1200)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function unbind(row) {
  try {
    await http.delete(`/instances/${row.id}`)
    ElMessage.success('已解绑')
    refreshInstances()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

const credVisible = ref(false)
const credRow = ref(null)
const credForm = reactive({ appid: '', app_secret: '', name: '' })

function openCred(row) {
  credRow.value = row
  credForm.appid = row.appid
  credForm.app_secret = ''
  credForm.name = row.name || ''
  credVisible.value = true
}

async function doUpdateCred() {
  if (!credForm.appid.trim()) {
    ElMessage.warning('请填写 AppID')
    return
  }
  if (!credForm.app_secret.trim()) {
    ElMessage.warning('请填写 AppSecret')
    return
  }
  busy.value = true
  try {
    const body = {
      appid: credForm.appid.trim(),
      app_secret: credForm.app_secret.trim(),
      name: credForm.name.trim(),
    }
    await http.put(`/instances/${credRow.value.id}/credentials`, body)
    credVisible.value = false
    ElMessage.success('凭证已更新，机器人正在重连')
    setTimeout(refreshInstances, 1500)
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/login')
}

onMounted(() => {
  refreshInstances()
  http.get('/auth/me').then((r) => { isAdmin.value = !!r.data.is_admin; account.value = r.data }).catch(() => {})
  loadSubscription()
  http.get('/announcement').then((r) => { announcement.value = r.data.content || '' }).catch(() => {})
})
onBeforeUnmount(() => {
  pageActive = false
  clearTimeout(timer)
  clearInterval(orderTimer)
})

</script>

<style scoped>
.page { min-height: 100vh; color: #202b3c; background: radial-gradient(ellipse at 12% 0%, rgba(223, 238, 255, .72), transparent 36%), #f4f7fb; }
.header {
  height: 68px;
  padding: 0 max(28px, calc((100vw - 1240px) / 2));
  background: rgba(255, 255, 255, .94);
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e8edf5;
  box-shadow: 0 4px 18px rgba(29, 55, 90, .035);
}
.brand-lockup { display: flex; align-items: center; gap: 11px; }
.brand-mark { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 11px; color: #fff; font-size: 17px; font-weight: 700; background: linear-gradient(145deg, #4388f5, #2864d7); box-shadow: 0 5px 12px rgba(54, 116, 224, .24); }
.brand-lockup > div { display: flex; flex-direction: column; gap: 1px; }
.title { font-weight: 700; font-size: 16px; letter-spacing: .3px; color: #1d2b42; }
.brand-caption { font-size: 11px; color: #9aa7ba; }
.header-spacer { flex: 1; }
.username-chip { margin: 0 18px; padding: 7px 12px; border-radius: 999px; background: #f3f6fb; color: #53627a; font-size: 13px; }
.admin-button { margin-right: 0; }
.logout-button { color: #68768c; }
.el-main { width: min(100%, 1300px); margin: 0 auto; padding: 26px 30px 48px; }

.subscription { margin-bottom: 34px; padding: 22px 24px 24px; background: linear-gradient(135deg, #fff 40%, #f6f9ff); border: 1px solid #e4ebf6; border-radius: 16px; box-shadow: 0 10px 28px rgba(34, 66, 111, .055); }
.subscription-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.subscription-title-wrap { display: flex; align-items: center; gap: 13px; }
.subscription-icon { width: 40px; height: 40px; display: grid; place-items: center; color: #3978e3; background: #eaf2ff; border-radius: 13px; font-size: 21px; }
.section-title { font-size: 17px; font-weight: 700; color: #26354c; }
.section-sub { margin-top: 5px; font-size: 13px; color: #8794a8; }
.section-sub strong { color: #475a75; font-weight: 600; }
.section-sub strong.expired { color: #e05a64; }
.order-state { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 14px; margin-bottom: 16px; background: #f5f8fd; border: 1px solid #e8eef8; border-radius: 10px; font-size: 13px; }
.order-state strong { margin-left: 8px; font-family: Menlo, Consolas, monospace; font-weight: 500; color: #52627b; }
.order-details { display: flex; align-items: center; gap: 12px; }
.muted { color: #929fb2; }
.plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
.plan-card { border-radius: 12px; border-color: #e6ecf5; transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.plan-card:hover { transform: translateY(-2px); border-color: #c8daf8; box-shadow: 0 10px 24px rgba(40, 88, 160, .09); }
.plan-card :deep(.el-card__body) { display: flex; flex-direction: column; align-items: flex-start; min-height: 150px; padding: 17px; }
.plan-name { font-weight: 650; color: #2c3b52; }
.plan-price { margin-top: 10px; color: #3273db; font-size: 25px; font-weight: 700; letter-spacing: -.4px; }
.plan-price span { color: #8e9bb0; font-size: 12px; font-weight: 400; letter-spacing: 0; }
.plan-description { flex: 1; margin: 8px 0 13px; color: #8b98ac; font-size: 12px; }
.plan-card .el-button { align-self: stretch; border-radius: 8px; }

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 20px;
}
.eyebrow { margin-bottom: 5px; color: #5483ce; font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; }
.page-title { font-size: 25px; font-weight: 750; letter-spacing: -.5px; color: #25344b; }
.page-sub { margin-top: 6px; font-size: 13px; color: #8794a8; }
.page-head-actions { display: flex; align-items: center; gap: 15px; }
.refresh-note { display: inline-flex; align-items: center; gap: 7px; color: #98a4b6; font-size: 12px; white-space: nowrap; }
.refresh-dot { width: 7px; height: 7px; border-radius: 50%; background: #70bd8a; }
.refresh-note.refreshing .refresh-dot { background: #e5ae4e; }
.bind-button { height: 40px; padding: 0 18px; border-radius: 9px; box-shadow: 0 5px 12px rgba(54, 116, 224, .16); }

.empty-wrap {
  background: rgba(255, 255, 255, .8);
  border: 1px dashed #d6e0ee;
  border-radius: 14px;
  padding: 48px 0;
}
.bot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(360px, 100%), 1fr));
  gap: 17px;
}
.bot-grid-loading { opacity: .82; }
.skeleton-card { min-height: 174px; border-radius: 14px; border-color: #e7edf5; }
.bot-card { border-radius: 14px; border-color: #e5ebf4; box-shadow: 0 7px 20px rgba(34, 58, 92, .045); transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.bot-card:hover { transform: translateY(-2px); border-color: #d0def2; box-shadow: 0 13px 28px rgba(34, 58, 92, .09); }
.bot-card :deep(.el-card__body) { padding: 19px 20px 15px; }

.bot-top { display: flex; align-items: center; gap: 14px; }
.bot-avatar {
  width: 54px; height: 54px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 26px; border-radius: 12px;
  background: linear-gradient(135deg, #ecf5ff, #f0f5ff);
  border: 1px solid #d9ecff;
}
.av-online { background: linear-gradient(135deg, #e7f9e7, #f0fff4); border-color: #b3e19d; }
.av-error { background: linear-gradient(135deg, #fef0f0, #fff1f0); border-color: #fab6b6; }

.bot-id { min-width: 0; }
.bot-name {
  font-size: 16px; font-weight: 600; color: #303133;
  display: flex; align-items: center; gap: 10px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.status-line { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.st-online { color: #3f9b66; } .st-online .dot { background: #54b879; }
.st-connecting { color: #e6a23c; } .st-connecting .dot { background: #e6a23c; }
.st-offline, .st-disabled { color: #909399; } .st-offline .dot, .st-disabled .dot { background: #c0c4cc; }
.st-error { color: #f56c6c; } .st-error .dot { background: #f56c6c; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(103, 194, 58, 0.5); }
  70% { box-shadow: 0 0 0 6px rgba(103, 194, 58, 0); }
  100% { box-shadow: 0 0 0 0 rgba(103, 194, 58, 0); }
}
.bot-appid { margin-top: 4px; font-size: 12px; color: #909399; font-family: Menlo, Consolas, monospace; }

.bot-meta { margin: 14px 0 4px; padding: 10px 12px; background: #f8fafc; border-radius: 8px; }
.meta-row { display: flex; font-size: 13px; line-height: 1.9; }
.meta-label { width: 68px; flex-shrink: 0; color: #909399; }
.meta-val { color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.bot-actions {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f2f5;
}
.bot-actions .el-button { margin-left: 0; }
@media (max-width: 760px) {
  .header { height: auto; min-height: 62px; padding: 10px 14px; flex-wrap: wrap; gap: 7px; }
  .header-spacer { flex: 1 1 12px; }
  .brand-mark { width: 32px; height: 32px; }
  .brand-caption { display: none; }
  .admin-button { margin-left: auto; }
  .username-chip { max-width: 112px; margin: 0 2px; padding: 6px 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .logout-button { padding: 0 4px; }
  .el-main { padding: 18px 13px 32px; }
  .subscription { padding: 15px; border-radius: 12px; }
  .page-head { align-items: flex-start; flex-direction: column; gap: 16px; }
  .page-head-actions { width: 100%; justify-content: space-between; }
}
@media (max-width: 420px) {
  .header { column-gap: 5px; }
  .brand-lockup { gap: 7px; }
  .title { font-size: 14px; }
  .username-chip { max-width: 82px; font-size: 11px; }
  .admin-button { padding: 7px 9px; }
  .logout-button { font-size: 12px; }
  .page-head-actions { align-items: flex-start; flex-direction: column; }
  .refresh-note { font-size: 11px; }
  .bind-button { width: 100%; }
  .subscription-head, .order-state { align-items: flex-start; flex-direction: column; }
  .order-details { flex-wrap: wrap; }
  .plan-grid { grid-template-columns: 1fr; }
  .bot-name { align-items: flex-start; flex-direction: column; gap: 5px; white-space: normal; }
  .bot-card :deep(.el-card__body) { padding: 16px; }
  .bot-actions { gap: 7px; }
  .bot-actions .el-button { flex: 1 1 auto; }
}
</style>
