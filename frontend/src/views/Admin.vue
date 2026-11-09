<template>
  <div class="page">
    <el-header class="header">
      <el-button link @click="$router.push('/instances')">← 返回我的面板</el-button>
      <span class="title">平台管理后台</span>
    </el-header>

    <el-main v-if="checked">
      <!-- 非管理员拒绝访问 -->
      <el-result v-if="!isAdmin" icon="warning" title="无权访问"
        sub-title="这个页面只对平台管理员开放。" />

      <div v-else class="admin-layout">
        <el-card class="nav-card">
          <template #header><b>后台导航</b></template>
          <el-select v-model="section" class="mobile-section-select" aria-label="后台栏目">
            <el-option v-for="m in menus" :key="m.key" :label="`${m.icon} ${m.label}`" :value="m.key" />
          </el-select>
          <div class="wl-menu">
            <div v-for="m in menus" :key="m.key"
              :class="['wl-item', section === m.key ? 'active' : '']" @click="section = m.key">
              {{ m.icon }} {{ m.label }}
            </div>
          </div>
        </el-card>

        <div class="admin-content">
          <el-alert v-if="maintenance" title="维护模式已开启：所有机器人已停止运行，用户暂时无法启动实例。"
            type="error" show-icon :closable="false" style="margin-bottom: 16px" />

          <!-- 概览 -->
          <section v-show="section === 'overview'">
            <el-row :gutter="16">
              <el-col :xs="24" :sm="12" :md="8" v-for="c in overviewCards" :key="c.label" style="margin-bottom: 16px">
                <el-card shadow="never">
                  <div style="color: #909399; font-size: 13px">{{ c.label }}</div>
                  <div style="font-size: 26px; font-weight: 600; margin-top: 4px">{{ c.value }}</div>
                </el-card>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :xs="24" :sm="24" :md="12">
                <el-card header="今日消息量 Top 10">
                  <el-table :data="rankToday" size="small">
                    <el-table-column type="index" width="46" />
                    <el-table-column prop="name" label="机器人" min-width="110" />
                    <el-table-column prop="username" label="用户" min-width="90" />
                    <el-table-column prop="msgs" label="消息数" width="90" />
                  </el-table>
                </el-card>
              </el-col>
              <el-col :xs="24" :sm="24" :md="12">
                <el-card header="近 7 天消息量 Top 10">
                  <el-table :data="rank7" size="small">
                    <el-table-column type="index" width="46" />
                    <el-table-column prop="name" label="机器人" min-width="110" />
                    <el-table-column prop="username" label="用户" min-width="90" />
                    <el-table-column prop="msgs" label="消息数" width="90" />
                  </el-table>
                </el-card>
              </el-col>
            </el-row>
          </section>

          <!-- 用户管理 -->
          <section v-show="section === 'users'">
            <div class="users-heading">
              <div>
                <h2>用户管理</h2>
                <p>管理账号状态、服务有效期及平台权限</p>
              </div>
              <el-input v-model="userQuery" placeholder="搜索用户名" class="user-search" clearable @keyup.enter="loadUsers">
                <template #append><el-button @click="loadUsers">搜索</el-button></template>
              </el-input>
            </div>
            <el-card class="users-card" shadow="never">
              <el-table :data="users" v-loading="usersLoading" class="users-table" row-class-name="user-row">
                <el-table-column prop="id" label="#" width="64" />
                <el-table-column label="账号" min-width="180">
                  <template #default="{ row }">
                    <div class="account-cell">
                      <span class="account-avatar">{{ row.username.slice(0, 1).toUpperCase() }}</span>
                      <div class="account-copy">
                        <strong>{{ row.username }}</strong>
                        <small>用户 ID {{ row.id }}</small>
                      </div>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="角色" width="108">
                  <template #default="{ row }">
                    <el-tag v-if="row.is_admin" type="danger" effect="light" round size="small">管理员</el-tag>
                    <span v-else class="muted-text">普通用户</span>
                  </template>
                </el-table-column>
                <el-table-column label="账号状态" width="112">
                  <template #default="{ row }">
                    <el-tag v-if="row.disabled" type="warning" effect="light" round size="small">手动停用</el-tag>
                    <el-tag v-else-if="row.expired" type="danger" effect="light" round size="small">已到期</el-tag>
                    <el-tag v-else type="success" effect="light" round size="small">正常</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="服务有效期" min-width="190">
                  <template #default="{ row }">
                    <div class="expiry-cell">
                      <el-tag v-if="!row.expires_at" type="info" effect="plain" round size="small">永久有效</el-tag>
                      <template v-else>
                        <el-tag v-if="row.expired" type="danger" effect="light" round size="small">已到期</el-tag>
                        <span :class="row.expired ? 'expired-time' : 'expiry-time'">{{ fmtTime(row.expires_at) }}</span>
                      </template>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="机器人" width="96" align="center">
                  <template #default="{ row }"><span class="count-pill">{{ row.instance_count }}</span></template>
                </el-table-column>
                <el-table-column label="最近登录" min-width="156">
                  <template #default="{ row }">{{ fmtTime(row.last_login_at) }}</template>
                </el-table-column>
                <el-table-column label="注册时间" min-width="156">
                  <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="92" fixed="right" align="center">
                  <template #default="{ row }">
                    <el-dropdown trigger="click" @command="(cmd) => runUserAction(cmd, row)">
                      <el-button class="more-button" circle plain aria-label="用户操作">
                        <el-icon><MoreFilled /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="expiry">设置有效期</el-dropdown-item>
                          <el-dropdown-item :command="row.disabled ? 'enable' : 'disable'" :disabled="row.id === me.id">
                            {{ row.disabled ? '启用账号' : '手动停用' }}
                          </el-dropdown-item>
                          <el-dropdown-item command="password">重置密码</el-dropdown-item>
                          <el-dropdown-item command="admin" :disabled="row.id === me.id">
                            {{ row.is_admin ? '撤销管理员' : '设为管理员' }}
                          </el-dropdown-item>
                          <el-dropdown-item command="logins">登录记录</el-dropdown-item>
                          <el-dropdown-item command="delete" divided :disabled="row.id === me.id" class="danger-action">删除用户</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </template>
                </el-table-column>
              </el-table>
              <div class="table-foot">
                <span>共 {{ users.length }} 个用户</span>
                <span>账号到期后机器人会暂停，数据保留至续期或删除</span>
              </div>
            </el-card>
          </section>

          <!-- 实例管理 -->
          <section v-show="section === 'instances'">
            <el-card>
              <el-table :data="instances" v-loading="instLoading" size="small">
                <el-table-column prop="id" label="ID" width="52" />
                <el-table-column prop="name" label="机器人" min-width="120" />
                <el-table-column prop="appid" label="AppID" width="120" />
                <el-table-column prop="username" label="所属用户" min-width="100" />
                <el-table-column label="状态" width="96">
                  <template #default="{ row }">
                    <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="groups_count" label="群数" width="64" />
                <el-table-column prop="today_msgs" label="今日消息" width="88" />
                <el-table-column label="注册时间" width="160">
                  <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="110" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" @click="$router.push(`/instances/${row.id}`)">打开详情</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </section>

          <!-- 审计日志 -->
          <section v-show="section === 'audit'">
            <el-card>
              <div class="admin-filter-row">
                <el-input v-model="auditFilter.action" placeholder="操作类型，如 user." class="filter-action" clearable />
                <el-input v-model="auditFilter.q" placeholder="详情关键词" class="filter-query" clearable />
                <el-button type="primary" @click="auditPage = 1; loadAudit()">查询</el-button>
              </div>
              <el-table :data="auditItems" v-loading="auditLoading" size="small">
                <el-table-column label="时间" width="160">
                  <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column prop="username" label="操作人" width="110">
                  <template #default="{ row }">{{ row.username || row.user_id || '系统' }}</template>
                </el-table-column>
                <el-table-column prop="action" label="操作" width="150" />
                <el-table-column prop="detail" label="详情" min-width="260" show-overflow-tooltip />
              </el-table>
              <div style="margin-top: 12px; display: flex; justify-content: flex-end">
                <el-pagination layout="prev, pager, next, total" :total="auditTotal"
                  :page-size="auditFilter.page_size" :current-page="auditFilter.page"
                  @current-change="(p) => { auditFilter.page = p; loadAudit() }" />
              </div>
            </el-card>
          </section>

          <!-- 运行日志 -->
          <section v-show="section === 'runlogs'">
            <el-card>
              <div class="admin-filter-row">
                <el-select v-model="runlogFilter.instance_id" placeholder="全部机器人" class="filter-instance" clearable>
                  <el-option v-for="i in instances" :key="i.id" :label="`${i.name}（${i.username}）`" :value="i.id" />
                </el-select>
                <el-select v-model="runlogFilter.level" placeholder="全部级别" class="filter-level" clearable>
                  <el-option label="info" value="info" /><el-option label="warn" value="warn" /><el-option label="error" value="error" />
                </el-select>
                <el-input v-model="runlogFilter.q" placeholder="内容关键词" class="filter-query" clearable />
                <el-button type="primary" @click="runlogPage = 1; loadRunlogs()">查询</el-button>
              </div>
              <el-table :data="runlogItems" v-loading="runlogLoading" size="small">
                <el-table-column label="时间" width="160">
                  <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column prop="instance_name" label="机器人" width="130" />
                <el-table-column label="级别" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'" size="small">{{ row.level }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="message" label="内容" min-width="320" show-overflow-tooltip />
              </el-table>
              <div style="margin-top: 12px; display: flex; justify-content: flex-end">
                <el-pagination layout="prev, pager, next, total" :total="runlogTotal"
                  :page-size="runlogFilter.page_size" :current-page="runlogFilter.page"
                  @current-change="(p) => { runlogFilter.page = p; loadRunlogs() }" />
              </div>
            </el-card>
          </section>

          <!-- 邀请码 -->
          <section v-show="section === 'invites'">
            <el-card>
              <div class="admin-filter-row">
                <el-input-number v-model="inviteCount" :min="1" :max="50" />
                <el-button type="primary" @click="genInvites">生成邀请码</el-button>
                <span style="color: #909399; align-self: center">注册模式为「需要邀请码」时，新用户注册必须提交未使用的邀请码。</span>
              </div>
              <el-table :data="invites" v-loading="inviteLoading" size="small">
                <el-table-column prop="code" label="邀请码" width="150" />
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <el-tag v-if="row.used" type="info" size="small">已使用</el-tag>
                    <el-tag v-else type="success" size="small">未使用</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="used_by" label="使用者" width="110" />
                <el-table-column label="使用时间" width="160">
                  <template #default="{ row }">{{ fmtTime(row.used_at) }}</template>
                </el-table-column>
                <el-table-column label="生成时间" width="160">
                  <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="150">
                  <template #default="{ row }">
                    <el-button size="small" @click="copyCode(row.code)">复制</el-button>
                    <el-button size="small" type="danger" :disabled="row.used" @click="delInvite(row)">作废</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </section>

          <!-- 系统设置 -->
          <section v-show="section === 'settings'">
            <el-card header="注册与配额" style="margin-bottom: 16px">
              <el-form label-width="150" style="max-width: 560px">
                <el-form-item label="注册模式">
                  <el-radio-group v-model="settingsForm.registration_mode">
                    <el-radio value="closed">关闭注册</el-radio>
                    <el-radio value="open">开放注册</el-radio>
                    <el-radio value="invite">需要邀请码</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="每用户实例数上限">
                  <el-input-number v-model="settingsForm.max_instances_per_user" :min="1" :max="1000" />
                  <span style="color: #909399; margin-left: 8px">管理员不受限</span>
                </el-form-item>
              </el-form>
            </el-card>
            <el-card header="平台公告" style="margin-bottom: 16px">
              <el-input v-model="settingsForm.announcement" type="textarea" :rows="3"
                placeholder="写公告内容后保存，所有用户打开面板就能看到；留空即清除公告。" style="max-width: 560px" />
            </el-card>
            <el-card header="维护模式">
              <div style="display: flex; align-items: center; gap: 16px">
                <el-switch :model-value="maintenance" size="large" @change="toggleMaintenance" />
                <span style="color: #909399; font-size: 13px">
                  开启后立即停止全部机器人运行，用户无法启动实例；关闭后按各实例原开关状态恢复。
                </span>
              </div>
            </el-card>
            <el-button type="primary" style="margin-top: 16px" :loading="settingsSaving" @click="saveSettings">保存设置</el-button>
          </section>

          <!-- 注册与支付运营 -->
          <section v-show="section === 'service'" class="service-page">
            <div class="users-heading"><div><h2>注册与支付</h2><p>邮件验证、人机验证与在线支付配置</p></div></div>
            <el-card header="SMTP 邮件服务" shadow="never" class="service-card">
              <el-form label-position="top" class="service-grid">
                <el-form-item label="SMTP 主机"><el-input v-model="serviceForm.mail_host" placeholder="smtp.example.com" /></el-form-item>
                <el-form-item label="端口"><el-input-number v-model="serviceForm.mail_port" :min="1" :max="65535" /></el-form-item>
                <el-form-item label="用户名"><el-input v-model="serviceForm.mail_user" autocomplete="off" /></el-form-item>
                <el-form-item label="发件人"><el-input v-model="serviceForm.mail_sender" placeholder="留空时使用 SMTP 用户名" /></el-form-item>
                <el-form-item label="密码"><el-input v-model="serviceForm.mail_password" type="password" show-password autocomplete="new-password" :placeholder="serviceMeta.mail_password_masked ? `已配置（${serviceMeta.mail_password_masked}），留空不修改` : '输入 SMTP 密码'" /></el-form-item>
                <el-form-item label="连接安全"><el-switch v-model="serviceForm.mail_starttls" active-text="启用 STARTTLS" /></el-form-item>
              </el-form>
              <div class="service-actions"><el-input v-model="smtpTestEmail" placeholder="测试收件邮箱" type="email" class="smtp-recipient" /><el-button :loading="smtpTesting" @click="sendSmtpTest">发送测试邮件</el-button></div>
            </el-card>
            <el-card header="Cloudflare Turnstile" shadow="never" class="service-card">
              <el-form label-position="top" class="service-grid">
                <el-form-item label="启用验证"><el-switch v-model="serviceForm.turnstile_enabled" /></el-form-item>
                <el-form-item label="Site key"><el-input v-model="serviceForm.turnstile_site_key" /></el-form-item>
                <el-form-item label="Secret key"><el-input v-model="serviceForm.turnstile_secret" type="password" show-password autocomplete="new-password" :placeholder="serviceMeta.turnstile_secret_masked ? `已配置（${serviceMeta.turnstile_secret_masked}），留空不修改` : '输入 Secret key'" /></el-form-item>
              </el-form>
            </el-card>
            <el-card header="易支付网关" shadow="never" class="service-card">
              <el-form label-position="top" class="service-grid">
                <el-form-item label="启用支付"><el-switch v-model="serviceForm.epay_enabled" /></el-form-item>
                <el-form-item label="网关地址"><el-input v-model="serviceForm.epay_gateway" placeholder="https://pay.example.com/submit.php" /></el-form-item>
                <el-form-item label="商户 PID"><el-input v-model="serviceForm.epay_pid" /></el-form-item>
                <el-form-item label="商户密钥"><el-input v-model="serviceForm.epay_secret" type="password" show-password autocomplete="new-password" :placeholder="serviceMeta.epay_secret_masked ? `已配置（${serviceMeta.epay_secret_masked}），留空不修改` : '输入商户密钥'" /></el-form-item>
                <el-form-item label="异步通知 URL"><el-input v-model="serviceForm.epay_notify_url" /></el-form-item>
                <el-form-item label="同步返回 URL"><el-input v-model="serviceForm.epay_return_url" /></el-form-item>
              </el-form>
            </el-card>
            <div class="service-save"><el-button type="primary" :loading="serviceSaving" @click="saveServiceSettings">保存注册与支付设置</el-button></div>
            <div class="users-heading payment-heading"><div><h2>套餐管理</h2><p>设置可购买的服务时长与价格</p></div><el-button type="primary" @click="openPlanEditor()">新增套餐</el-button></div>
            <el-card shadow="never" class="service-card">
              <el-table :data="plans" v-loading="plansLoading" size="small">
                <el-table-column prop="id" label="ID" width="70" /><el-table-column prop="name" label="套餐名称" min-width="160" />
                <el-table-column label="时长" width="120"><template #default="{ row }">{{ row.duration_days }} 天</template></el-table-column>
                <el-table-column label="价格" width="120"><template #default="{ row }">{{ money(row.price_cents) }}</template></el-table-column>
                <el-table-column label="状态" width="100"><template #default="{ row }"><el-switch :model-value="row.enabled" @change="(v) => togglePlan(row, v)" /></template></el-table-column>
                <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openPlanEditor(row)">编辑</el-button><el-button link type="danger" @click="deletePlan(row)">删除</el-button></template></el-table-column>
              </el-table>
            </el-card>
            <div class="users-heading payment-heading"><div><h2>支付订单</h2><p>查询近期支付记录</p></div></div>
            <el-card shadow="never" class="service-card">
              <div class="order-filters"><el-input v-model="orderFilter.q" placeholder="订单号或套餐名称" clearable @keyup.enter="searchOrders" /><el-select v-model="orderFilter.status" placeholder="全部状态" clearable><el-option label="待支付" value="pending" /><el-option label="已支付" value="paid" /></el-select><el-input-number v-model="orderFilter.user_id" :min="1" :controls="false" placeholder="用户 ID" /><el-button type="primary" @click="searchOrders">查询</el-button></div>
              <el-table :data="orders" v-loading="ordersLoading" size="small">
                <el-table-column prop="out_trade_no" label="订单号" min-width="210" show-overflow-tooltip /><el-table-column label="用户" min-width="130"><template #default="{ row }">{{ row.username || `#${row.user_id}` }}</template></el-table-column>
                <el-table-column prop="plan_name" label="套餐" min-width="120" /><el-table-column label="金额" width="100"><template #default="{ row }">{{ money(row.amount_cents) }}</template></el-table-column>
                <el-table-column label="状态" width="92"><template #default="{ row }"><el-tag :type="row.status === 'paid' ? 'success' : 'warning'" size="small">{{ row.status === 'paid' ? '已支付' : row.status }}</el-tag></template></el-table-column>
                <el-table-column label="创建时间" min-width="160"><template #default="{ row }">{{ fmtTime(row.created_at) }}</template></el-table-column><el-table-column label="支付时间" min-width="160"><template #default="{ row }">{{ fmtTime(row.paid_at) }}</template></el-table-column>
              </el-table>
              <div class="pagination-row"><el-pagination layout="prev, pager, next, total" :total="orderTotal" :page-size="orderFilter.page_size" :current-page="orderFilter.page" @current-change="(p) => { orderFilter.page = p; loadOrders() }" /></div>
            </el-card>
          </section>
        </div>
      </div>
    </el-main>

    <!-- 用户有效期弹窗 -->
    <el-dialog v-model="expiryDlg.visible" :title="`设置有效期：${expiryDlg.username}`" width="min(480px, calc(100vw - 24px))">
      <el-form label-position="top">
        <el-form-item label="直接设置到期时间">
          <el-date-picker v-model="expiryDlg.expiresAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="选择到期日期和时间" style="width: 100%" />
        </el-form-item>
        <el-form-item label="快速延长">
          <el-button @click="extendExpiry(7)">+7 天</el-button>
          <el-button @click="extendExpiry(30)">+30 天</el-button>
          <el-button @click="extendExpiry(90)">+90 天</el-button>
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" title="到期后用户无法登录，名下机器人将自动停止；数据会保留，续期后按原启用状态恢复。设为永久可取消到期限制。" />
      <template #footer>
        <el-button @click="expiryDlg.visible = false">取消</el-button>
        <el-button @click="setExpiry({ permanent: true })">设为永久</el-button>
        <el-button type="primary" :disabled="!expiryDlg.expiresAt" :loading="expiryDlg.saving"
          @click="setExpiry({ expires_at: expiryDlg.expiresAt })">保存到期时间</el-button>
      </template>
    </el-dialog>

    <!-- 登录记录弹窗 -->
    <el-dialog v-model="loginDlg.visible" :title="`登录记录：${loginDlg.username}`" width="min(520px, calc(100vw - 24px))">
      <el-table :data="loginDlg.items" size="small" v-loading="loginDlg.loading">
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" />
      </el-table>
      <div style="margin-top: 12px; display: flex; justify-content: flex-end">
        <el-pagination layout="prev, pager, next, total" :total="loginDlg.total" :page-size="20"
          :current-page="loginDlg.page" @current-change="(p) => { loginDlg.page = p; loadLogins() }" />
      </div>
    </el-dialog>

    <el-dialog v-model="planDlg.visible" :title="planDlg.id ? '编辑套餐' : '新增套餐'" width="min(480px, calc(100vw - 24px))">
      <el-form label-position="top">
        <el-form-item label="套餐名称"><el-input v-model="planDlg.name" maxlength="64" /></el-form-item>
        <el-form-item label="服务时长（天）"><el-input-number v-model="planDlg.duration_days" :min="1" :max="36500" /></el-form-item>
        <el-form-item label="价格（元）"><el-input-number v-model="planDlg.price_yuan" :min="0" :precision="2" :step="1" /></el-form-item>
        <el-form-item label="上架"><el-switch v-model="planDlg.enabled" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="planDlg.visible = false">取消</el-button><el-button type="primary" :loading="planDlg.saving" @click="savePlan">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
import { http, errText } from '../api'

const menus = [
  { key: 'overview', icon: '📊', label: '平台概览' },
  { key: 'users', icon: '👥', label: '用户管理' },
  { key: 'instances', icon: '🤖', label: '全部机器人' },
  { key: 'audit', icon: '🧾', label: '审计日志' },
  { key: 'runlogs', icon: '📜', label: '运行日志' },
  { key: 'invites', icon: '🎟️', label: '邀请码' },
  { key: 'settings', icon: '⚙️', label: '系统设置' },
  { key: 'service', icon: '💳', label: '注册与支付' },
]
const section = ref('overview')

const checked = ref(false)
const isAdmin = ref(false)
const me = ref({})
const maintenance = ref(false)

const fmtTime = (t) => {
  if (!t) return '—'
  const s = typeof t === 'string' ? t : String(t)
  return s.includes('T') ? s.replace('T', ' ').slice(0, 19) : s.slice(0, 19)
}

const STATUS = {
  online: ['success', '在线'],
  connecting: ['warning', '连接中'],
  offline: ['info', '离线'],
  error: ['danger', '异常'],
  disabled: ['info', '已停用'],
}
const statusType = (s) => (STATUS[s] || STATUS.offline)[0]
const statusText = (s) => (STATUS[s] || STATUS.offline)[1]

// ---------- 概览 ----------
const overview = ref({})
const rankToday = ref([])
const rank7 = ref([])
const overviewCards = computed(() => [
  { label: '注册用户', value: overview.value.users_total ?? '—' },
  { label: '今日新增用户', value: overview.value.users_today ?? '—' },
  { label: '受限用户', value: overview.value.users_disabled ?? '—' },
  { label: '机器人总数', value: overview.value.instances_total ?? '—' },
  { label: '在线机器人', value: overview.value.instances_online ?? '—' },
  { label: '今日平台消息量', value: overview.value.msgs_today ?? '—' },
])

async function loadOverview() {
  try {
    const [ov, r1, r7] = await Promise.all([
      http.get('/admin/stats/overview'),
      http.get('/admin/stats/ranking', { params: { days: 1 } }),
      http.get('/admin/stats/ranking', { params: { days: 7 } }),
    ])
    overview.value = ov.data
    rankToday.value = r1.data.items
    rank7.value = r7.data.items
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

// ---------- 用户 ----------
const users = ref([])
const usersLoading = ref(false)
const userQuery = ref('')
const loginDlg = reactive({ visible: false, username: '', items: [], total: 0, page: 1, userId: 0 })
const expiryDlg = reactive({ visible: false, username: '', userId: 0, expiresAt: '', saving: false })

function editExpiry(row) {
  expiryDlg.userId = row.id
  expiryDlg.username = row.username
  expiryDlg.expiresAt = row.expires_at ? (() => {
    const d = new Date(row.expires_at)
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
    return d.toISOString().slice(0, 19)
  })() : ''
  expiryDlg.visible = true
}

async function setExpiry(payload) {
  expiryDlg.saving = true
  try {
    const body = payload.expires_at
      ? { expires_at: new Date(payload.expires_at).toISOString() }
      : payload
    await http.post(`/admin/users/${expiryDlg.userId}/expiry`, body)
    expiryDlg.visible = false
    ElMessage.success(payload.permanent ? '已设为永久有效' : '有效期已更新')
    await loadUsers()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    expiryDlg.saving = false
  }
}

async function extendExpiry(days) {
  expiryDlg.saving = true
  try {
    await http.post(`/admin/users/${expiryDlg.userId}/expiry`, { extend_days: days })
    expiryDlg.visible = false
    ElMessage.success(`已延长 ${days} 天`)
    await loadUsers()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    expiryDlg.saving = false
  }
}

async function loadUsers() {
  usersLoading.value = true
  try {
    const r = await http.get('/admin/users', { params: { q: userQuery.value } })
    users.value = r.data.items
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    usersLoading.value = false
  }
}

async function runUserAction(command, row) {
  if (command === 'expiry') return editExpiry(row)
  if (command === 'enable' || command === 'disable') return toggleDisable(row)
  if (command === 'password') return resetPwd(row)
  if (command === 'admin') return toggleAdmin(row)
  if (command === 'logins') return showLogins(row)
  if (command === 'delete') return delUser(row)
}

async function toggleDisable(row) {
  const action = row.disabled ? 'enable' : 'disable'
  try {
    if (action === 'disable') {
      await ElMessageBox.confirm(
        `停用后「${row.username}」将无法登录，其名下机器人会立即停止运行。确定停用？`,
        '停用用户', { type: 'warning' }
      )
    }
    await http.post(`/admin/users/${row.id}/${action}`)
    ElMessage.success(action === 'disable' ? '已停用' : '已启用')
    loadUsers()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') ElMessage.error(errText(e))
  }
}

async function resetPwd(row) {
  try {
    await ElMessageBox.confirm(`确定重置「${row.username}」的密码？将生成一个新密码。`, '重置密码', { type: 'warning' })
  } catch { return }
  try {
    const r = await http.post(`/admin/users/${row.id}/reset-password`)
    ElMessageBox.alert(`新密码：${r.data.new_password}（只显示这一次，请复制发给用户）`, '密码已重置')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function toggleAdmin(row) {
  const target = !row.is_admin
  try {
    await ElMessageBox.confirm(`确定把「${row.username}」${target ? '设为' : '撤销'}平台管理员？`, '修改管理员', { type: 'warning' })
  } catch { return }
  try {
    await http.post(`/admin/users/${row.id}/set-admin`, { is_admin: target })
    ElMessage.success('已修改')
    loadUsers()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function delUser(row) {
  try {
    await ElMessageBox.prompt(
      `危险操作：将删除「${row.username}」及其名下全部机器人、配置与统计数据，不可恢复。请输入用户名确认。`,
      '删除用户', { type: 'error', confirmButtonText: '永久删除', confirmButtonClass: 'el-button--danger' }
    ).then(({ value }) => {
      if (value !== row.username) throw new Error('用户名不匹配')
    })
  } catch (e) {
    if (e?.message === '用户名不匹配') ElMessage.warning('用户名不匹配，已取消')
    return
  }
  try {
    await http.delete(`/admin/users/${row.id}`)
    ElMessage.success('已删除')
    loadUsers()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function showLogins(row) {
  loginDlg.visible = true
  loginDlg.username = row.username
  loginDlg.userId = row.id
  loginDlg.page = 1
  loadLogins()
}

async function loadLogins() {
  loginDlg.loading = true
  try {
    const r = await http.get(`/admin/users/${loginDlg.userId}/logins`, { params: { page: loginDlg.page, page_size: 20 } })
    loginDlg.items = r.data.items
    loginDlg.total = r.data.total
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    loginDlg.loading = false
  }
}

// ---------- 实例 ----------
const instances = ref([])
const instLoading = ref(false)

async function loadInstances() {
  instLoading.value = true
  try {
    instances.value = (await http.get('/admin/instances')).data.items
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    instLoading.value = false
  }
}

// ---------- 审计 / 运行日志 ----------
const auditItems = ref([])
const auditTotal = ref(0)
const auditLoading = ref(false)
const auditFilter = reactive({ action: '', q: '', page: 1, page_size: 20 })

async function loadAudit() {
  auditLoading.value = true
  try {
    const r = await http.get('/admin/audit-logs', {
      params: { action: auditFilter.action, q: auditFilter.q, page: auditFilter.page, page_size: auditFilter.page_size },
    })
    auditItems.value = r.data.items
    auditTotal.value = r.data.total
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    auditLoading.value = false
  }
}

const runlogItems = ref([])
const runlogTotal = ref(0)
const runlogLoading = ref(false)
const runlogFilter = reactive({ instance_id: null, level: '', q: '', page: 1, page_size: 30 })

async function loadRunlogs() {
  runlogLoading.value = true
  try {
    const r = await http.get('/admin/runtime-logs', {
      params: {
        instance_id: runlogFilter.instance_id || undefined,
        level: runlogFilter.level, q: runlogFilter.q,
        page: runlogFilter.page, page_size: runlogFilter.page_size,
      },
    })
    runlogItems.value = r.data.items
    runlogTotal.value = r.data.total
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    runlogLoading.value = false
  }
}

// ---------- 邀请码 ----------
const invites = ref([])
const inviteLoading = ref(false)
const inviteCount = ref(5)

async function loadInvites() {
  inviteLoading.value = true
  try {
    invites.value = (await http.get('/admin/invites')).data.items
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    inviteLoading.value = false
  }
}

async function genInvites() {
  try {
    const r = await http.post('/admin/invites', { count: inviteCount.value })
    await loadInvites()
    ElMessageBox.alert(r.data.items.join('\n'), `已生成 ${r.data.items.length} 个邀请码`, { customStyle: { whiteSpace: 'pre-line' } })
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function copyCode(code) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function delInvite(row) {
  try {
    await http.delete(`/admin/invites/${row.id}`)
    ElMessage.success('已作废')
    loadInvites()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

// ---------- 系统设置 ----------
const settingsForm = reactive({ registration_mode: 'open', max_instances_per_user: 3, announcement: '' })
const settingsSaving = ref(false)

async function loadSettings() {
  try {
    const r = await http.get('/admin/settings')
    settingsForm.registration_mode = r.data.registration_mode
    settingsForm.max_instances_per_user = r.data.max_instances_per_user || 3
    settingsForm.announcement = r.data.announcement || ''
    maintenance.value = !!r.data.maintenance_mode
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function saveSettings() {
  settingsSaving.value = true
  try {
    await http.put('/admin/settings', {
      registration_mode: settingsForm.registration_mode,
      max_instances_per_user: settingsForm.max_instances_per_user,
      announcement: settingsForm.announcement,
    })
    ElMessage.success('设置已保存，即时生效')
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    settingsSaving.value = false
  }
}

// ---------- 注册安全 / 支付运营 ----------
const serviceForm = reactive({ mail_host: '', mail_port: 587, mail_user: '', mail_password: '', mail_sender: '', mail_starttls: true, turnstile_enabled: false, turnstile_site_key: '', turnstile_secret: '', epay_enabled: false, epay_gateway: '', epay_pid: '', epay_secret: '', epay_notify_url: '', epay_return_url: '' })
const serviceMeta = reactive({})
const serviceSaving = ref(false)
const smtpTestEmail = ref('')
const smtpTesting = ref(false)
const plans = ref([])
const plansLoading = ref(false)
const planDlg = reactive({ visible: false, saving: false, id: null, name: '', duration_days: 30, price_yuan: 0, enabled: true })
const orders = ref([])
const ordersLoading = ref(false)
const orderTotal = ref(0)
const orderFilter = reactive({ q: '', status: '', user_id: null, page: 1, page_size: 20 })
const money = (cents) => `¥${(Number(cents || 0) / 100).toFixed(2)}`

async function loadServiceSettings() {
  try {
    const { data } = await http.get('/admin/service-settings')
    for (const key of Object.keys(serviceForm)) serviceForm[key] = data[key] ?? serviceForm[key]
    Object.assign(serviceMeta, data)
  } catch (e) { ElMessage.error(errText(e)) }
}

async function saveServiceSettings() {
  serviceSaving.value = true
  try {
    const body = { ...serviceForm }
    for (const key of ['mail_password', 'turnstile_secret', 'epay_secret']) if (!body[key]) delete body[key]
    const { data } = await http.put('/admin/service-settings', body)
    Object.assign(serviceMeta, data)
    serviceForm.mail_password = ''
    serviceForm.turnstile_secret = ''
    serviceForm.epay_secret = ''
    ElMessage.success('注册与支付设置已保存')
  } catch (e) { ElMessage.error(errText(e)) } finally { serviceSaving.value = false }
}

async function sendSmtpTest() {
  if (!smtpTestEmail.value.trim()) return ElMessage.warning('请填写测试收件邮箱')
  smtpTesting.value = true
  try {
    await http.post('/admin/service-settings/smtp-test', { to_email: smtpTestEmail.value.trim() })
    ElMessage.success('测试邮件已发送')
  } catch (e) { ElMessage.error(errText(e)) } finally { smtpTesting.value = false }
}

async function loadPlans() {
  plansLoading.value = true
  try { plans.value = (await http.get('/admin/payment/plans')).data.items } catch (e) { ElMessage.error(errText(e)) } finally { plansLoading.value = false }
}

function openPlanEditor(row) {
  Object.assign(planDlg, row ? { id: row.id, name: row.name, duration_days: row.duration_days, price_yuan: row.price_cents / 100, enabled: row.enabled } : { id: null, name: '', duration_days: 30, price_yuan: 0, enabled: true })
  planDlg.visible = true
}

async function savePlan() {
  if (!planDlg.name.trim()) return ElMessage.warning('请填写套餐名称')
  planDlg.saving = true
  const body = { name: planDlg.name.trim(), duration_days: planDlg.duration_days, price_cents: Math.round(Number(planDlg.price_yuan) * 100), enabled: planDlg.enabled }
  try {
    if (planDlg.id) await http.put(`/admin/payment/plans/${planDlg.id}`, body)
    else await http.post('/admin/payment/plans', body)
    planDlg.visible = false
    ElMessage.success('套餐已保存')
    await loadPlans()
  } catch (e) { ElMessage.error(errText(e)) } finally { planDlg.saving = false }
}

async function togglePlan(row, enabled) {
  try { await http.post(`/admin/payment/plans/${row.id}/enabled`, { enabled }); row.enabled = enabled; ElMessage.success(enabled ? '套餐已启用' : '套餐已停用') }
  catch (e) { ElMessage.error(errText(e)); await loadPlans() }
}

async function deletePlan(row) {
  try { await ElMessageBox.confirm(`确定删除套餐「${row.name}」？`, '删除套餐', { type: 'warning' }) } catch { return }
  try { await http.delete(`/admin/payment/plans/${row.id}`); ElMessage.success('套餐已删除'); await loadPlans() } catch (e) { ElMessage.error(errText(e)) }
}

function searchOrders() { orderFilter.page = 1; loadOrders() }

async function loadOrders() {
  ordersLoading.value = true
  try {
    const { data } = await http.get('/admin/payment/orders', { params: { q: orderFilter.q, status: orderFilter.status, user_id: orderFilter.user_id || undefined, page: orderFilter.page, page_size: orderFilter.page_size } })
    orders.value = data.items
    orderTotal.value = data.total
  } catch (e) { ElMessage.error(errText(e)) } finally { ordersLoading.value = false }
}

async function toggleMaintenance() {
  const next = !maintenance.value
  try {
    await ElMessageBox.confirm(
      next
        ? '开启后所有机器人立即停止运行，用户无法启动实例。确定开启维护模式？'
        : '关闭维护模式后将按各实例原开关状态自动恢复运行。确定关闭？',
      '维护模式', { type: 'warning' }
    )
  } catch { return }
  try {
    const r = await http.post('/admin/maintenance', { on: next })
    maintenance.value = r.data.on
    ElMessage.success(next ? `维护模式已开启（停止 ${r.data.affected} 个实例）` : `维护模式已关闭（恢复 ${r.data.affected} 个实例）`)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

onMounted(async () => {
  try {
    const r = await http.get('/auth/me')
    me.value = r.data
    isAdmin.value = !!r.data.is_admin
  } catch (e) {
    ElMessage.error(errText(e))
  }
  checked.value = true
  if (isAdmin.value) {
    loadOverview()
    loadUsers()
    loadInstances()
    loadAudit()
    loadRunlogs()
    loadInvites()
    loadSettings()
    loadServiceSettings()
    loadPlans()
    loadOrders()
  }
})
</script>

<style scoped>
.page { min-height: 100vh; min-width: 0; }
.header {
  min-height: 56px;
  padding: 8px 16px;
  gap: 10px;
  flex-wrap: wrap;
  display: flex;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.title { font-weight: 600; margin-left: 12px; }
.el-main { width: 100%; min-width: 0; }
.admin-layout { display: flex; gap: 16px; align-items: flex-start; min-width: 0; }
.admin-layout > .nav-card { width: 150px; flex: 0 0 150px; position: sticky; top: 8px; }
.admin-content { flex: 1; min-width: 0; }
.mobile-section-select { display: none; }
.admin-filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
.filter-action { width: 180px; }
.filter-query { width: 200px; }
.filter-instance { width: 200px; }
.filter-level { width: 120px; }
.nav-card :deep(.el-card__header) { padding: 10px 12px; font-size: 14px; }
.wl-menu { display: flex; flex-direction: column; gap: 4px; }
.wl-item {
  padding: 9px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #303133;
  transition: background 0.15s;
}
.wl-item:hover { background: #f5f7fa; }
.wl-item.active { background: #ecf5ff; color: #409eff; font-weight: 600; }

.users-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin: 2px 0 18px;
}
.users-heading h2 { margin: 0; color: #303133; font-size: 20px; font-weight: 650; }
.users-heading p { margin: 5px 0 0; color: #909399; font-size: 13px; }
.user-search { width: min(340px, 40vw); }
.users-card { border: 1px solid #ebeef5; border-radius: 8px; }
.users-table :deep(th.el-table__cell) {
  background: #f7f9fc;
  color: #697586;
  font-size: 12px;
  font-weight: 600;
  height: 44px;
}
.users-table :deep(td.el-table__cell) { height: 58px; }
.users-table :deep(.el-table__inner-wrapper::before) { display: none; }
.account-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.account-avatar {
  width: 34px; height: 34px; flex: 0 0 34px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 9px; background: #eef5ff; color: #3a78c2;
  font-size: 14px; font-weight: 700;
}
.account-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.account-copy strong { color: #303133; font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.account-copy small { color: #a3aab5; font-size: 11px; }
.muted-text { color: #909399; font-size: 12px; }
.expiry-cell { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.expiry-time, .expired-time { color: #606266; font-size: 12px; font-variant-numeric: tabular-nums; }
.expired-time { color: #c45656; }
.count-pill {
  display: inline-flex; min-width: 26px; height: 24px; padding: 0 8px;
  align-items: center; justify-content: center; border-radius: 12px;
  background: #f0f2f5; color: #606266; font-size: 12px; font-weight: 600;
}
.more-button { width: 30px; height: 30px; border-color: #e4e7ed; color: #606266; }
.more-button:hover { color: #409eff; border-color: #b3d8ff; background: #f4f9ff; }
.danger-action { color: #f56c6c !important; }
.table-foot {
  display: flex; justify-content: space-between; gap: 12px;
  padding: 13px 4px 1px; color: #a0a6b0; font-size: 12px;
  border-top: 1px solid #f2f3f5;
}
.service-page { display: flex; flex-direction: column; gap: 14px; }
.service-card { border: 1px solid #ebeef5; border-radius: 6px; }
.service-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.service-grid :deep(.el-form-item) { margin-bottom: 12px; }
.service-actions, .service-save, .pagination-row { display: flex; justify-content: flex-end; gap: 10px; }
.smtp-recipient { width: min(300px, 100%); }
.payment-heading { margin: 14px 0 0; }
.order-filters { display: grid; grid-template-columns: minmax(180px, 1fr) 150px 120px auto; gap: 10px; margin-bottom: 14px; }
.pagination-row { margin-top: 14px; }
@media (max-width: 760px) {
  .el-main { padding: 14px 12px; }
  .admin-layout { flex-direction: column; gap: 12px; }
  .admin-layout > .nav-card { position: static; width: 100%; flex: 0 0 auto; padding: 12px; }
  .admin-layout > .nav-card :deep(.el-card__body) { padding: 0; }
  .admin-layout > .nav-card :deep(.el-card__header) { display: none; }
  .mobile-section-select { display: block; width: 100%; }
  .admin-layout > .nav-card .wl-menu { display: none; }
  .admin-content { width: 100%; min-width: 0; }
  .admin-content :deep(.el-table) { max-width: 100%; }
  .admin-content :deep(.el-dialog) { width: calc(100vw - 24px) !important; max-width: 640px; }
  .admin-content :deep(.el-dialog__body) { max-height: calc(100dvh - 170px); overflow: auto; }
  .admin-content :deep(.el-form:not(.el-form--label-top) .el-form-item) { display: block; }
  .admin-content :deep(.el-form:not(.el-form--label-top) .el-form-item__label) { display: block; text-align: left; }
  .admin-content :deep(.el-form:not(.el-form--label-top) .el-form-item__content) { margin-left: 0 !important; }
  .admin-content :deep(.el-form-item__content > .el-input),
  .admin-content :deep(.el-form-item__content > .el-select),
  .admin-content :deep(.el-form-item__content > .el-date-editor),
  .admin-content :deep(.el-form-item__content > .el-input-number) { max-width: 100%; }
  .admin-content :deep(.el-row) { row-gap: 4px; }
  .users-heading { align-items: flex-start; flex-direction: column; }
  .user-search { width: 100%; }
  .users-card { overflow-x: auto; }
  .users-table { min-width: 1060px; }
  .table-foot { flex-direction: column; }
  .admin-filter-row { align-items: stretch; }
  .filter-action, .filter-query, .filter-instance, .filter-level { width: calc(50% - 6px); min-width: 0; }
  .service-grid { grid-template-columns: 1fr; }
  .service-actions { align-items: stretch; flex-direction: column; }
  .smtp-recipient { width: 100%; }
  .order-filters { grid-template-columns: 1fr 1fr; }
  .pagination-row { overflow-x: auto; justify-content: flex-start; }
  .users-heading p { max-width: 100%; }
}
@media (max-width: 420px) {
  .header { gap: 6px; padding: 8px 10px; }
  .header > .el-button { padding: 0; font-size: 12px; }
  .title { margin-left: 4px; font-size: 14px; }
  .admin-content > section > .el-row { row-gap: 0; }
  .admin-filter-row, .order-filters { grid-template-columns: 1fr; }
  .admin-filter-row { flex-direction: column; }
  .filter-action, .filter-query, .filter-instance, .filter-level { width: 100%; }
  .admin-content :deep(.el-pagination) { justify-content: flex-start; }
  .admin-content :deep(.el-pagination__total) { display: none; }
  .service-page .users-heading { gap: 10px; }
}
.service-page { display: flex; flex-direction: column; gap: 14px; }
.service-card { border: 1px solid #ebeef5; border-radius: 6px; }
.service-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.service-grid :deep(.el-form-item) { margin-bottom: 12px; }
.service-actions, .service-save, .pagination-row { display: flex; justify-content: flex-end; gap: 10px; }
.smtp-recipient { width: min(300px, 100%); }
.payment-heading { margin: 14px 0 0; }
.order-filters { display: grid; grid-template-columns: minmax(180px, 1fr) 150px 120px auto; gap: 10px; margin-bottom: 14px; }
.pagination-row { margin-top: 14px; }
@media (max-width: 760px) {
  .service-grid { grid-template-columns: 1fr; }
  .service-actions { align-items: stretch; flex-direction: column; }
  .smtp-recipient { width: 100%; }
  .order-filters { grid-template-columns: 1fr 1fr; }
}
</style>
