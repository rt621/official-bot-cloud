<template>
  <div class="page">
    <el-header class="header">
      <el-button link class="back-button" @click="$router.push('/instances')">← 返回列表</el-button>
      <span class="detail-title">{{ inst.name }}（{{ inst.appid }}）</span>
      <el-tag :type="statusType(inst.status)" class="detail-status">{{ statusText(inst.status) }}</el-tag>
      <span class="detail-spacer"></span>
      <span class="detail-status-text">{{ inst.status_detail }}</span>
    </el-header>

    <el-main v-if="loaded">
      <div class="detail-layout">
        <el-card class="detail-nav-card">
          <template #header><b>{{ inst.name || '实例' }}</b></template>
          <div class="wl-menu">
            <div :class="['wl-item', tab === 'home' ? 'active' : '']" @click="tab = 'home'">🧩 功能总览</div>
            <div v-for="group in navGroups" :key="group.title">
              <div class="wl-group">{{ group.title }}</div>
              <div v-for="item in group.items" :key="item.key"
                :class="['wl-item', tab === item.key ? 'active' : '']" @click="tab = item.key">
                {{ item.icon }} {{ item.label }}
              </div>
            </div>
          </div>
          <el-button size="small" style="width: 100%; margin-top: 10px" :loading="groupsRefreshing" @click="refreshGroupNames">
            ⟳ 刷新群名
          </el-button>
        </el-card>

        <div class="detail-content">
        <!-- 功能总览 -->
        <section v-show="tab === 'home'">
          <div v-for="group in navGroups" :key="group.title" style="margin-bottom: 8px">
            <div style="font-weight: 600; margin: 10px 0 12px">{{ group.title }}</div>
            <el-row :gutter="16">
              <el-col :xs="24" :sm="12" :md="8" v-for="item in group.items" :key="item.key" style="margin-bottom: 16px">
                <el-card shadow="hover" style="height: 100%; cursor: pointer" @click="tab = item.key">
                  <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px">
                    <span style="font-size: 26px">{{ item.icon }}</span>
                    <b>{{ item.label }}</b>
                  </div>
                  <div style="color: #909399; font-size: 12px; min-height: 18px">{{ item.desc }}</div>
                  <div style="margin-top: 8px; display: flex; align-items: center">
                    <el-tag v-if="featureStatus[item.key] !== undefined"
                      :type="featureStatus[item.key] ? 'success' : 'danger'" size="small">
                      {{ featureStatus[item.key] ? '启用中' : '已停用' }}
                    </el-tag>
                    <el-button size="small" type="primary" link style="margin-left: auto; padding: 0">打开设置 →</el-button>
                  </div>
                </el-card>
              </el-col>
            </el-row>
          </div>
        </section>
        <!-- 概览与自检 -->
        <!-- 概览 / 自检 -->
        <section v-show="tab === 'overview'">
          <el-card header="实例自检" style="margin-bottom: 16px">
            <el-form inline>
              <el-form-item label="群 openid">
                <el-select v-model="selfcheckGroup" filterable allow-create placeholder="选择已发现的群或直接粘贴" class="mobile-fluid-380">
                  <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="selfchecking" @click="runSelfcheck">开始自检</el-button>
              </el-form-item>
            </el-form>
            <template v-if="selfcheckResult">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="机器人群内角色">{{ roleName(selfcheckResult.bot_state) }}</el-descriptions-item>
                <el-descriptions-item label="消息接收范围">{{ msgMode(selfcheckResult.bot_state) }}</el-descriptions-item>
                <el-descriptions-item label="全员禁言状态">{{ globalMuteText }}</el-descriptions-item>
              </el-descriptions>
              <el-alert v-for="(a, i) in selfcheckResult.advice" :key="i" :title="a" type="warning" show-icon style="margin-top: 8px" />
              <el-alert v-if="!selfcheckResult.advice?.length" title="未发现配置问题" type="success" show-icon style="margin-top: 8px" />
            </template>
          </el-card>
          <el-card header="使用说明">
            <ol style="line-height: 2; color: #606266">
              <li>在 QQ 开放平台把机器人添加到测试群，群主在群设置里开启「获取群内全部消息」和「主动发言」（需要时）。</li>
              <li>需要撤回/禁言/审批能力时，把机器人设为群管理员。</li>
              <li>踢人/黑名单/成员列表接口官方为内邀制，未开通时页面会明确提示。</li>
              <li>管理指令需先在「群管自动化」页把群主的 user_openid 加入管理员名单。</li>
            </ol>
          </el-card>
        </section>

        <!-- 插件市场 -->
        <!-- 插件市场 -->
        <section v-show="tab === 'market'">
          <el-alert type="info" :closable="false" style="margin-bottom: 16px"
            title="预设插件包：一键安装即生成对应的自动化规则或功能开关，装完都能在各页签里继续自定义。" />
          <el-row :gutter="16">
            <el-col :span="8" v-for="p in pluginItems" :key="p.key" style="margin-bottom: 16px">
              <el-card shadow="hover" style="height: 100%">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px">
                  <span style="font-size: 28px">{{ p.icon }}</span>
                  <div>
                    <div style="font-weight: 600">{{ p.name }}</div>
                    <el-tag size="small" type="info">{{ p.category }}</el-tag>
                  </div>
                </div>
                <div style="color: #606266; font-size: 13px; min-height: 60px">{{ p.description }}</div>
                <div style="color: #909399; font-size: 12px; margin: 6px 0">需要：{{ p.needs || '无' }}</div>
                <div style="display: flex; gap: 8px; align-items: center">
                  <template v-if="p.type === 'rules'">
                    <el-button v-if="!p.installed" size="small" type="primary" :loading="busy" @click="installPlugin(p)">安装</el-button>
                    <el-button v-else size="small" type="danger" plain @click="uninstallPlugin(p)">卸载</el-button>
                    <el-tag v-if="p.installed" size="small" type="success">已安装</el-tag>
                  </template>
                  <template v-else>
                    <el-button v-if="!p.installed" size="small" type="primary" :loading="busy" @click="installPlugin(p)">启用</el-button>
                    <el-button v-else size="small" @click="goTab(p.tab)">去配置</el-button>
                    <el-tag v-if="p.installed" size="small" type="success">已启用</el-tag>
                    <el-button v-if="p.installed" size="small" type="warning" plain @click="uninstallPlugin(p)">停用</el-button>
                  </template>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </section>

        <!-- 群管自动化 -->
        <!-- 群管自动化 -->
        <section v-show="tab === 'automation'">
          <el-card style="margin-bottom: 16px">
            <div style="display: flex; align-items: center; gap: 16px">
              <span style="font-weight: 600">总开关</span>
              <el-switch v-model="ga.master_enabled" size="large" @change="saveGa" />
              <span style="color: #909399; font-size: 13px">关闭后所有自动化规则停跑（手动管理指令不受影响）</span>
            </div>
            <el-divider style="margin: 12px 0" />
            <el-form label-width="130" style="max-width: 720px; margin-bottom: 0">
              <el-form-item label="指令管理员名单">
                <el-input v-model="ga.admin_openids" type="textarea" :rows="2" placeholder="每行一个 user_openid，名单内的人可用 /禁言 /踢人 等指令" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="busy" @click="saveGa">保存设置</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card>
            <template #header>
              <div style="display: flex; align-items: center">
                <span>自动化规则（触发条件 → 执行动作，支持分群）</span>
                <span style="flex: 1"></span>
                <el-button type="primary" @click="openRuleDialog()">新建规则</el-button>
              </div>
            </template>
            <el-table :data="rules">
              <el-table-column prop="name" label="名称" min-width="120" />
              <el-table-column label="作用群" min-width="150">
                <template #default="{ row }">{{ row.group_openid === '*' ? '所有群' : gLabel(row.group_openid) }}</template>
              </el-table-column>
              <el-table-column label="触发" min-width="180">
                <template #default="{ row }">{{ triggerText(row) }}</template>
              </el-table-column>
              <el-table-column label="动作" min-width="220">
                <template #default="{ row }">{{ actionsText(row.actions) }}</template>
              </el-table-column>
              <el-table-column label="启用" width="80">
                <template #default="{ row }"><el-switch v-model="row.enabled" @change="saveRule(row)" /></template>
              </el-table-column>
              <el-table-column label="操作" width="140">
                <template #default="{ row }">
                  <el-button size="small" @click="openRuleDialog(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="delRule(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </section>

        <!-- 群管理工具 -->
        <!-- 群管理工具 -->
        <section v-show="tab === 'tools'">
          <el-card style="margin-bottom: 16px">
            <el-form inline>
              <el-form-item label="操作群">
                <el-select v-model="toolGroup" filterable allow-create placeholder="选择已发现的群" class="mobile-fluid-380">
                  <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
                </el-select>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card header="禁言管理" style="margin-bottom: 16px">
            <el-form inline>
              <el-form-item><el-button @click="queryMute">查询禁言状态</el-button></el-form-item>
            </el-form>
            <el-table v-if="muteMembers.length" :data="muteMembers" size="small" style="margin-bottom: 12px">
              <el-table-column prop="member_openid" label="成员 openid" min-width="260" show-overflow-tooltip />
              <el-table-column label="到期时间" width="220"><template #default="{ row }">{{ fmt(row.mute_expire_at) }}</template></el-table-column>
            </el-table>
            <el-form inline>
              <el-form-item label="成员 openid">
                <el-input v-model="toolOpenids" placeholder="多个用逗号分隔" style="width: 320px" />
              </el-form-item>
              <el-form-item label="时长(分钟)"><el-input-number v-model="toolMuteMinutes" :min="1" :max="43200" /></el-form-item>
              <el-form-item>
                <el-button type="warning" @click="doMute">禁言</el-button>
                <el-button @click="doUnmute">解禁</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card header="踢人" style="margin-bottom: 16px">
            <el-form inline>
              <el-form-item label="成员 openid"><el-input v-model="toolOpenids" placeholder="多个用逗号分隔，单次≤20" style="width: 320px" /></el-form-item>
              <el-form-item><el-checkbox v-model="kickBlacklist">同时加入黑名单</el-checkbox></el-form-item>
              <el-form-item><el-button type="danger" @click="doKick">移出群聊</el-button></el-form-item>
            </el-form>
          </el-card>

          <el-card header="群黑名单" style="margin-bottom: 16px">
            <el-form inline>
              <el-form-item><el-button @click="queryBlacklist">查询黑名单</el-button></el-form-item>
            </el-form>
            <el-table v-if="blacklistRows.length" :data="blacklistRows" size="small" style="margin-bottom: 12px">
              <el-table-column prop="member_openid" label="成员 openid" min-width="260" show-overflow-tooltip />
              <el-table-column prop="username" label="昵称" min-width="140" />
              <el-table-column prop="banned_at" label="拉黑时间" width="220"><template #default="{ row }">{{ fmt(row.banned_at) }}</template></el-table-column>
            </el-table>
            <el-form inline>
              <el-form-item label="成员 openid"><el-input v-model="toolOpenids" placeholder="多个用逗号分隔" style="width: 320px" /></el-form-item>
              <el-form-item>
                <el-button type="warning" @click="doBlacklist('add')">加入黑名单</el-button>
                <el-button @click="doBlacklist('del')">移出黑名单</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card header="成员浏览（官方内邀制，未开通会提示）">
            <el-button @click="queryMembers">查询成员列表</el-button>
            <el-table v-if="memberRows.length" :data="memberRows" size="small" style="margin-top: 12px">
              <el-table-column prop="member_openid" label="成员 openid" min-width="240" show-overflow-tooltip />
              <el-table-column prop="username" label="昵称" min-width="140" />
              <el-table-column prop="member_role" label="角色" width="100" />
              <el-table-column prop="joined_at" label="入群时间" width="220"><template #default="{ row }">{{ fmt(row.joined_at) }}</template></el-table-column>
            </el-table>
          </el-card>
        </section>

        <!-- 关键词 -->
        <!-- 关键词回复 -->
        <section v-show="tab === 'keywords'">
          <el-card style="margin-bottom: 16px">
            <div style="display: flex; align-items: center; gap: 12px">
              <b>功能总开关</b>
              <el-switch :model-value="featureStatus.keywords" @change="(v) => toggleFeature('keywords', v)" />
              <span style="color: #909399; font-size: 13px">{{ featureStatus.keywords ? '关键词回复已开启' : '已停用：群里的关键词自动回复不会工作' }}</span>
              <span style="flex: 1"></span>
              <span style="color: #c0c4cc; font-size: 12px">与「插件市场」里关键词回复的启停是同一个开关</span>
            </div>
          </el-card>
          <ScopePanel v-model="scopes.keywords" title="设置范围" :groups="knownGroups" :configured-gids="fgConfigured('keywords')" @pick="(gid) => fgPick('keywords', gid)">
            <div v-if="scopes.keywords === 'global'">
                      <el-button type="primary" style="margin-bottom: 12px" @click="editKw = { pattern: '', reply_type: 'text', reply_content: '', trigger_scope: 'all', group_openid: '*', enabled: true }; kwDialog = true">新增规则</el-button>
          <el-table :data="keywords">
            <el-table-column prop="pattern" label="触发词（|分隔多个）" min-width="160" />
            <el-table-column prop="reply_content" label="回复内容" min-width="220" show-overflow-tooltip />
            <el-table-column label="类型" width="80"><template #default="{ row }">{{ row.reply_type === 'image' ? '图片' : '文本' }}</template></el-table-column>
            <el-table-column label="触发范围" width="110"><template #default="{ row }">{{ row.trigger_scope === 'at' ? '仅@触发' : '全部消息' }}</template></el-table-column>
            <el-table-column label="作用群" min-width="130"><template #default="{ row }">{{ row.group_openid === '*' ? '所有群' : gLabel(row.group_openid) }}</template></el-table-column>
            <el-table-column label="启用" width="80"><template #default="{ row }"><el-switch v-model="row.enabled" @change="saveKw(row)" /></template></el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" @click="editKw = { ...row }; kwDialog = true">编辑</el-button>
                <el-button size="small" type="danger" @click="delKw(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        
            </div>
            <el-card v-else>
              <template #header><b>「{{ gLabel(scopes.keywords) }}」的关键词回复</b></template>
              <el-form label-position="top" style="max-width: 480px">
                <el-form-item label="此群启用关键词回复">
                  <el-switch :model-value="fgOn('keywords', scopes.keywords)" @change="(v) => fgSet('keywords', scopes.keywords, v)" />
                </el-form-item>
              </el-form>
              <el-divider content-position="left">此群的专属规则（仅该群生效）</el-divider>
              <el-table :data="kwScoped" size="small">
                <el-table-column prop="pattern" label="触发词" min-width="120" />
                <el-table-column prop="reply_content" label="回复" min-width="160" show-overflow-tooltip />
                <el-table-column label="启用" width="70"><template #default="{ row }"><el-switch v-model="row.enabled" @change="saveKw(row)" /></template></el-table-column>
                <el-table-column label="操作" width="120">
                  <template #default="{ row }">
                    <el-button size="small" @click="editKw = { ...row }; kwDialog = true">编辑</el-button>
                    <el-button size="small" type="danger" @click="delKw(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-button size="small" type="primary" plain style="margin-top: 10px" @click="editKw = { pattern: '', reply_type: 'text', reply_content: '', trigger_scope: 'all', group_openid: scopes.keywords, enabled: true }; kwDialog = true">给这个群加规则</el-button>
            </el-card>
          </ScopePanel>
        </section>

        <!-- AI -->
        <!-- AI 对话 -->
        <section v-show="tab === 'ai'">
          <div style="display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap">
            <el-card class="persona-scope-card">
              <template #header><b>人设范围</b></template>
              <div class="wl-menu">
                <div :class="['wl-item', personaScope === 'global' ? 'active' : '']" @click="selectPersonaScope('global')">全局默认</div>
                <div v-for="g in personaGroups" :key="g.group_openid"
                  :class="['wl-item', personaScope === g.group_openid ? 'active' : '']"
                  @click="selectPersonaScope(g.group_openid)">按群：{{ gLabel(g.group_openid) }}</div>
              </div>
              <el-select v-model="newPersonaGroup" filterable allow-create size="small" placeholder="选择群：切换或新建人设" style="width: 100%; margin-top: 10px" @change="onPersonaGroupPick">
                <el-option v-for="g in knownGroupIds" :key="g" :label="gLabel(g)" :value="g" />
              </el-select>
            </el-card>

            <el-card style="flex: 1; min-width: 0" v-if="personaScope === 'global' && ai">
              <template #header><b>全局默认人设</b></template>
              <el-form label-position="top" style="max-width: 640px">
                <el-divider content-position="left">💬 对话人设（@机器人聊天时）</el-divider>
                <el-form-item label="AI 名字" style="max-width: 300px; margin-bottom: 10px">
                  <el-input v-model="ai.persona_name" placeholder="例如：小管家" />
                </el-form-item>
                <el-form-item label="人设描述（它是谁、负责什么、什么性格）">
                  <el-input v-model="ai.persona_desc" type="textarea" :rows="3"
                    placeholder="例如：你是本群的专属管家，性格温和但原则性强，回答简短口语化。" />
                </el-form-item>
                <el-divider content-position="left">🛡️ 审核人设（AI 审核消息时）</el-divider>
                <el-form-item label="审核员名字" style="max-width: 300px; margin-bottom: 10px">
                  <el-input v-model="ai.audit_persona_name" placeholder="选填，例如：风控专员" />
                </el-form-item>
                <el-form-item label="审核风格描述">
                  <el-input v-model="ai.audit_persona_desc" type="textarea" :rows="3"
                    placeholder="例如：执法严格，对广告零容忍，但对玩笑和正常斗嘴宽容。" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="busy" @click="saveCfg('ai', ai, 'api_key')">保存</el-button>
                </el-form-item>
              </el-form>
            </el-card>

            <el-card style="flex: 1; min-width: 0" v-else-if="personaScope !== 'global' && personaEdit">
              <template #header><b>按群人设</b>　<span style="color:#909399;font-size:12px;font-weight:normal">{{ gLabel(personaScope) }}</span></template>
              <el-form label-position="top" style="max-width: 640px">
              <el-form-item label="此群启用 AI 对话" style="margin-bottom: 12px">
                <el-switch :model-value="fgOn('ai', personaScope)" @change="(v) => fgSet('ai', personaScope, v)" />
                <span style="margin-left: 12px; color: #909399; font-size: 12px">关闭后此群 @机器人 不再回复（人设配置保留）</span>
              </el-form-item>
                <el-divider content-position="left">💬 对话人设（此群覆盖）</el-divider>
                <el-form-item label="AI 名字" style="max-width: 300px; margin-bottom: 10px">
                  <el-input v-model="personaEdit.chat_persona_name" :placeholder="ai?.persona_name || '沿用全局'" />
                </el-form-item>
                <el-form-item label="人设描述">
                  <el-input v-model="personaEdit.chat_persona_desc" type="textarea" :rows="3" placeholder="留空 = 沿用全局对话人设" />
                </el-form-item>
                <el-divider content-position="left">🛡️ 审核人设（此群覆盖）</el-divider>
                <el-form-item label="审核员名字" style="max-width: 300px; margin-bottom: 10px">
                  <el-input v-model="personaEdit.audit_persona_name" :placeholder="ai?.audit_persona_name || '沿用全局'" />
                </el-form-item>
                <el-form-item label="审核风格描述">
                  <el-input v-model="personaEdit.audit_persona_desc" type="textarea" :rows="3" placeholder="留空 = 沿用全局审核人设" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="busy" @click="saveGroupPersona">保存</el-button>
                  <el-popconfirm title="删除后该群回退为全局人设，确定？" @confirm="deleteGroupPersona">
                    <template #reference><el-button type="danger" plain>删除</el-button></template>
                  </el-popconfirm>
                </el-form-item>
              </el-form>
            </el-card>

            <el-card style="flex: 1; min-width: 0">
              <template #header><b>AI 对话</b>　<span style="color:#909399;font-size:12px;font-weight:normal">@机器人提问接大模型回答</span></template>
            <el-form label-width="160" style="max-width: 640px" v-if="ai">
            <el-form-item label="启用 AI 对话"><el-switch v-model="ai.enabled" @change="saveCfg('ai', ai, 'api_key')" /></el-form-item>
            <el-form-item label="API 地址"><el-input v-model="ai.api_base" placeholder="OpenAI 兼容接口地址" /></el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="aiKey" type="password" show-password :placeholder="ai.api_key_masked ? `已设置（${ai.api_key_masked}），留空不修改` : 'sk-...'" />
            </el-form-item>
            <el-form-item label="模型"><el-input v-model="ai.model" /></el-form-item>
            <el-form-item label="人设提示词"><el-input v-model="ai.system_prompt" type="textarea" :rows="3" /></el-form-item>
            <el-form-item label="触发方式">
              <el-radio-group v-model="ai.trigger_mode">
                <el-radio value="at">仅 @机器人 提问</el-radio>
                <el-radio value="keyword">关键词唤醒</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="ai.trigger_mode === 'keyword'" label="唤醒词（逗号分隔）"><el-input v-model="ai.trigger_keywords" /></el-form-item>
            <el-form-item label="每人每日次数上限"><el-input-number v-model="ai.daily_limit_per_user" :min="1" :max="1000" /></el-form-item>
            <el-form-item label="群规 / FAQ 知识库">
              <el-input v-model="ai.group_rules_text" type="textarea" :rows="5" placeholder="把群规、常见问答粘贴到这里，AI 回答时会优先依据这些内容" />
              <div style="color: #909399; font-size: 12px">填了之后 @机器人 问群相关问题（资源在哪/几点禁言），AI 会按群规回答而不是瞎编</div>
            </el-form-item>
            <el-form-item><el-button type="primary" :loading="busy" @click="saveCfg('ai', ai, 'api_key')">保存对话设置</el-button></el-form-item>
          </el-form>
          </el-card>
          </div>
        </section>

        <!-- 审批 -->
        <!-- 入群审批 -->
        <section v-show="tab === 'approval'">
          <ScopePanel v-model="scopes.approval" title="设置范围" :groups="knownGroups" :configured-gids="fgConfigured('approval')" @pick="approvalPick">
            <div v-if="scopes.approval === 'global'">
                      <el-form label-width="200" style="max-width: 720px" v-if="approval">
            <el-form-item label="启用入群审批"><el-switch v-model="approval.enabled" @change="saveCfg('approval', approval)" /></el-form-item>
            <el-form-item label="自动通过关键词（每行一个）">
              <el-input v-model="approval.auto_approve_keywords" type="textarea" :rows="3" placeholder="申请答案包含关键词即自动同意" />
            </el-form-item>
            <el-form-item><el-button type="primary" :loading="busy" @click="saveCfg('approval', approval)">保存</el-button></el-form-item>
          </el-form>
          <el-card header="待处理申请（事件推送）">
            <el-table :data="joinRequests" size="small">
              <el-table-column prop="created_at" label="时间" width="170"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
              <el-table-column prop="group_openid" label="群" width="220" show-overflow-tooltip />
              <el-table-column prop="member_openid" label="申请人" width="200" show-overflow-tooltip />
              <el-table-column prop="answer" label="申请答案" min-width="160" show-overflow-tooltip />
              <el-table-column prop="risk_tips" label="风险" min-width="120" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="90" />
              <el-table-column label="操作" width="160">
                <template #default="{ row }">
                  <template v-if="row.status === 'pending'">
                    <el-button size="small" type="success" @click="review(row, 'approve')">同意</el-button>
                    <el-button size="small" type="danger" @click="review(row, 'decline')">拒绝</el-button>
                  </template>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
          <el-card header="从官方拉取申请列表（不依赖事件，需机器人是管理员）" style="margin-top: 16px">
            <el-button :loading="officialReqLoading" @click="pullOfficialRequests">拉取</el-button>
            <el-table v-if="officialRequests.length" :data="officialRequests" size="small" style="margin-top: 12px">
              <el-table-column prop="member_openid" label="申请人" min-width="220" show-overflow-tooltip />
              <el-table-column prop="source" label="来源" width="120" />
              <el-table-column label="验证信息" min-width="200"><template #default="{ row }">{{ row.verify_info?.verify_message || '（无）' }}</template></el-table-column>
              <el-table-column label="风险" min-width="160"><template #default="{ row }">{{ row.risk_tips || '无' }}</template></el-table-column>
            </el-table>
          </el-card>
        
            </div>
            <el-card v-else>
              <template #header><b>「{{ gLabel(scopes.approval) }}」的入群审批</b></template>
              <el-form label-position="top" style="max-width: 480px">
                <el-form-item label="此群启用该功能">
                  <el-switch :model-value="fgOn('approval', scopes.approval)" @change="(v) => fgSet('approval', scopes.approval, v)" />
                </el-form-item>
                <el-form-item label="该群自动通过关键词（每行一个）">
                  <el-input v-model="approvalGroupKeywords" type="textarea" :rows="4" placeholder="申请答案包含任一关键词即自动通过；留空使用全局关键词" />
                  <div style="color: #909399; font-size: 12px; margin-top: 4px">仅对此群生效。留空并保存后，将继承全局审批关键词。</div>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="approvalGroupSaving" @click="saveApprovalGroup">保存该群关键词</el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </ScopePanel>
        </section>

        <!-- 举报通道 -->
        <section v-show="tab === 'report'">
          <ScopePanel v-model="scopes.report" title="设置范围" :groups="knownGroups" :configured-gids="fgConfigured('report')" @pick="(gid) => fgPick('report', gid)">
            <div v-if="scopes.report === 'global'">
                      <el-card header="举报通道">
            <el-form label-width="200" style="max-width: 640px" v-if="report">
              <el-form-item label="启用举报通道"><el-switch v-model="report.enabled" @change="saveCfg('report', report)" /></el-form-item>
              <el-form-item label="举报转发到管理群 openid">
                <el-input v-model="report.notify_group_openid" placeholder="管理群 group_openid" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="busy" @click="saveCfg('report', report)">保存</el-button>
              </el-form-item>
            </el-form>
            <el-alert type="info" :closable="false" title="群友在群里发「举报 + 内容」，机器人会转交到上面的管理群，并回复已受理。" />
          </el-card>
        
            </div>
            <el-card v-else>
              <template #header><b>「{{ gLabel(scopes.report) }}」的举报通道</b></template>
              <el-form label-position="top" style="max-width: 480px">
                <el-form-item label="此群启用该功能">
                  <el-switch :model-value="fgOn('report', scopes.report)" @change="(v) => fgSet('report', scopes.report, v)" />
                </el-form-item>
              </el-form>
            </el-card>
          </ScopePanel>
        </section>

        <!-- 定时任务 -->
        <!-- 定时推送 -->
        <section v-show="tab === 'schedule'">
          <el-card style="margin-bottom: 16px">
            <div style="display: flex; align-items: center; gap: 12px">
              <b>功能总开关</b>
              <el-switch :model-value="featureStatus.schedule" @change="(v) => toggleFeature('schedule', v)" />
              <span style="color: #909399; font-size: 13px">{{ featureStatus.schedule ? '定时推送已开启' : '已停用：所有定时任务不再执行' }}</span>
              <span style="flex: 1"></span>
              <span style="color: #c0c4cc; font-size: 12px">与「插件市场」里定时推送的启停是同一个开关</span>
            </div>
          </el-card>
          <el-card>
            <template #header>
              <b>全部定时任务</b>
              <span style="margin-left: 10px; color: #909399; font-size: 12px">每条任务各自指定发到哪个群（「目标群」下拉选择），不需要按群重复设置</span>
            </template>
            <el-button type="primary" style="margin-bottom: 12px" @click="editSch = { name: '', cron: '0 9 * * *', target_group_openid: '', task_type: 'text', content: '', enabled: true }; schDialog = true">新增任务</el-button>
            <el-table :data="schedules">
              <el-table-column prop="name" label="名称" min-width="120" />
              <el-table-column prop="cron" label="cron" width="110" />
              <el-table-column label="目标群" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ gLabel(row.target_group_openid) }}</template>
              </el-table-column>
              <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip />
              <el-table-column label="启用" width="80"><template #default="{ row }"><el-switch v-model="row.enabled" @change="saveSch(row)" /></template></el-table-column>
              <el-table-column label="操作" width="140">
                <template #default="{ row }">
                  <el-button size="small" @click="editSch = { ...row }; schDialog = true">编辑</el-button>
                  <el-button size="small" type="danger" @click="delSch(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </section>

        <!-- 每日签到 -->
        <section v-show="tab === 'fun'">
          <ScopePanel v-model="scopes.fun" title="设置范围" :groups="knownGroups" :configured-gids="fgConfigured('signin')" @pick="fgPickSignin">
            <div v-if="scopes.fun === 'global'">
              <el-form label-width="200" style="max-width: 640px" v-if="signin">
                <el-form-item label="启用签到（/签到）"><el-switch v-model="signin.enabled" @change="saveCfg('signin', signin)" /></el-form-item>
                <el-form-item label="签到回复模板">
                  <el-input v-model="signin.reward_template" type="textarea" :rows="2" />
                  <div style="color: #909399; font-size: 12px">{days} 会替换成连续签到天数</div>
                </el-form-item>
                <el-form-item><el-button type="primary" :loading="busy" @click="saveCfg('signin', signin)">保存</el-button></el-form-item>
              </el-form>
            </div>
            <el-card v-else>
              <template #header><b>「{{ gLabel(scopes.fun) }}」的签到</b></template>
              <el-form label-position="top" style="max-width: 480px">
                <el-form-item label="此群启用签到">
                  <el-switch :model-value="fgOn('signin', scopes.fun)" @change="(v) => fgSet('signin', scopes.fun, v)" />
                </el-form-item>
              </el-form>
            </el-card>
          </ScopePanel>
        </section>

        <!-- 菜单与面板 -->
        <!-- 菜单与面板 -->
        <section v-show="tab === 'menu'">
          <el-card style="margin-bottom: 16px">
            <template #header>
              <div style="display: flex; align-items: center">
                <span><b>单聊自定义菜单</b>　<span style="color:#909399;font-size:12px;font-weight:normal">用户单聊机器人时输入框上方的一排按钮</span></span>
                <span style="flex:1"></span>
                <el-tag v-if="menuVersion" size="small" type="info">当前版本 {{ menuVersion }}</el-tag>
              </div>
            </template>
            <el-alert type="warning" :closable="false" style="margin-bottom: 12px"
              title="保存会整体覆盖官方菜单；链接必须 https://；最多 10 个一级项、名称 ≤5 个汉字；官方限频每分钟 5 次。" />
            <div style="display: flex; gap: 16px; align-items: flex-start">
              <div style="flex: 1">
                <el-button size="small" @click="loadMenu" :loading="menuLoading">从 QQ 拉取</el-button>
                <el-button size="small" @click="fillMenuExample">填入示例</el-button>
                <el-button size="small" type="primary" plain @click="addMenuItem" :disabled="menuEdit.length >= 10">添加一级项</el-button>
                <el-button size="small" type="success" :loading="busy" @click="saveMenu">保存到 QQ</el-button>

                <div v-for="(item, idx) in menuEdit" :key="idx" style="border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; margin-top: 12px">
                  <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
                    <el-tag size="small">第 {{ idx + 1 }} 项</el-tag>
                    <span style="flex:1"></span>
                    <el-button size="small" type="danger" link @click="menuEdit.splice(idx, 1)">删除</el-button>
                  </div>
                  <el-form inline>
                    <el-form-item label="类型">
                      <el-select v-model="item.type" style="width: 170px">
                        <el-option label="发送消息（填入输入框）" value="send_message" />
                        <el-option label="跳转链接" value="link" />
                        <el-option label="子菜单" value="menu" />
                        <el-option label="开关（回调开关）" value="switch" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="名称">
                      <el-input v-model="item.name" maxlength="12" style="width: 200px" :suffix-icon="null" />
                      <span style="margin-left: 8px; font-size: 12px; color: #909399">已用 {{ charWidth(item.name) }}/10</span>
                    </el-form-item>
                  </el-form>
                  <template v-if="item.type === 'send_message'">
                    <el-form inline>
                      <el-form-item label="从关键词回复选用">
                        <el-select v-model="item._kwPick" placeholder="不选用，手动填写" clearable style="width: 240px" @change="pickKeyword(item)">
                          <el-option v-for="kw in keywordOptions" :key="kw" :label="kw" :value="kw" />
                        </el-select>
                      </el-form-item>
                      <el-form-item label="填入的指令">
                        <el-input v-model="item.send_message" placeholder="/help" style="width: 240px" />
                      </el-form-item>
                    </el-form>
                  </template>
                  <el-form inline v-if="item.type === 'link'">
                    <el-form-item label="链接（https://）">
                      <el-input v-model="item.link" placeholder="https://..." style="width: 360px" />
                    </el-form-item>
                  </el-form>
                  <el-form inline v-if="item.type === 'switch'">
                    <el-form-item label="开关 ID"><el-input v-model="item.switch_id" style="width: 140px" /></el-form-item>
                    <el-form-item label="默认状态">
                      <el-switch v-model="item.switch_default" />
                    </el-form-item>
                  </el-form>
                  <div v-if="item.type === 'menu'">
                    <div style="font-size: 13px; color: #606266; margin-bottom: 6px">子菜单（最多 5 个）<el-button size="small" link type="primary" @click="addSubItem(item)" :disabled="(item.sub_menu_items || []).length >= 5">+ 加子项</el-button></div>
                    <div v-for="(sub, si) in item.sub_menu_items" :key="si" style="display: flex; gap: 8px; margin-bottom: 6px; align-items: center">
                      <el-select v-model="sub.type" style="width: 140px" size="small">
                        <el-option label="发送消息" value="send_message" />
                        <el-option label="跳转链接" value="link" />
                      </el-select>
                      <el-input v-model="sub.name" size="small" placeholder="名称 ≤7 汉字" style="width: 160px" />
                      <el-input v-model="sub.send_message" v-if="sub.type === 'send_message'" size="small" placeholder="指令" style="width: 200px" />
                      <el-input v-model="sub.link" v-if="sub.type === 'link'" size="small" placeholder="https://..." style="width: 240px" />
                      <el-button size="small" type="danger" link @click="item.sub_menu_items.splice(si, 1)">删</el-button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 手机预览 -->
              <el-card class="menu-preview-card" shadow="never">
                <template #header><span style="font-size: 13px; color: #909399">手机预览 · 仅供对照，以 QQ 实机为准</span></template>
                <div class="phone">
                  <div class="phone-title">机器人</div>
                  <div class="phone-body">
                    <div class="phone-bubble">/help</div>
                  </div>
                  <div class="phone-submenu" v-if="previewSub && previewSub.length">
                    <span v-for="(s, i) in previewSub" :key="i" class="phone-menu-item sub">{{ s.name }}</span>
                  </div>
                  <div class="phone-menubar">
                    <span v-for="(item, i) in menuEdit" :key="i" class="phone-menu-item"
                      @click="previewSubToggle(item)">{{ item.name }}<template v-if="item.type === 'menu'"> ▾</template></span>
                  </div>
                  <div class="phone-input"><span>🎤</span><div class="phone-input-box"></div><span>😊</span><span>➕</span></div>
                </div>
              </el-card>
            </div>
          </el-card>

          <el-card>
            <template #header>
              <div style="display: flex; align-items: center">
                <span><b>指令面板</b>　<span style="color:#909399;font-size:12px;font-weight:normal">用户输入 / 时弹出的指令列表（单聊和群聊可分别配置）</span></span>
                <span style="flex:1"></span>
                <el-select v-model="panelScope" size="small" style="width: 110px; margin-right: 8px">
                  <el-option label="群聊面板" value="group" />
                  <el-option label="单聊面板" value="c2c" />
                </el-select>
                <el-button size="small" @click="loadPanels" :loading="panelsLoading">刷新</el-button>
                <el-button size="small" type="primary" @click="panelDialog = true">新建面板</el-button>
              </div>
            </template>
            <el-table :data="panels" size="small">
              <el-table-column prop="panel_id" label="面板 ID" min-width="180" show-overflow-tooltip />
              <el-table-column prop="remark" label="备注" min-width="120" />
              <el-table-column label="指令项" min-width="240">
                <template #default="{ row }">
                  {{ (row.panel?.items || row.items || []).map(i => i.name).join('、') }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-popconfirm title="删除该面板？" @confirm="deletePanel(row)">
                    <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </section>

        <!-- 命中记录 -->
        <!-- 命中记录 -->
        <section v-show="tab === 'hits'">
          <el-table :data="hits" size="small">
            <el-table-column prop="created_at" label="时间" width="170"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
            <el-table-column prop="rule_name" label="规则" width="140" />
            <el-table-column prop="user_openid" label="用户" width="200" show-overflow-tooltip />
            <el-table-column prop="reason" label="原因" width="180" />
            <el-table-column prop="excerpt" label="内容摘要" min-width="200" show-overflow-tooltip />
            <el-table-column label="处置" min-width="160"><template #default="{ row }">{{ JSON.stringify(row.actions) }}</template></el-table-column>
          </el-table>
        </section>

        <!-- 统计 -->
        <!-- 统计 -->
        <section v-show="tab === 'stats'">
          <el-card style="margin-bottom: 16px">
            <div style="display: flex; align-items: center; gap: 12px">
              <b>功能总开关</b>
              <el-switch :model-value="featureStatus.stats" @change="(v) => toggleFeature('stats', v)" />
              <span style="color: #909399; font-size: 13px">{{ featureStatus.stats ? '活跃统计已开启' : '已停用：不再记录发言统计' }}</span>
              <span style="flex: 1"></span>
              <span style="color: #c0c4cc; font-size: 12px">与「插件市场」里活跃统计的启停是同一个开关</span>
            </div>
          </el-card>
          <el-card>
            <template #header>
              <b>活跃统计</b>
              <span style="margin-left: 10px; color: #909399; font-size: 12px">默认显示全部群合计；选择单个群可查看该群统计，也可以单独停用某个群</span>
            </template>
            <el-select v-model="statsViewGroup" clearable filterable placeholder="全部群（合计）"
              style="width: 280px; margin-bottom: 12px">
              <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
            </el-select>
            <template v-if="!statsViewGroup">
              <el-card header="近 7 天群消息数（全部群合计）" shadow="never">
                <el-table :data="dayRows" size="small">
                  <el-table-column prop="day" label="日期" width="140" />
                  <el-table-column label="消息量">
                    <template #default="{ row }">
                      <el-progress :percentage="barPct(row.count)" :show-text="false" style="width: 60%" />
                      <span style="margin-left: 8px">{{ row.count }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
              <el-card header="发言排行 Top 20（全部群合计）" shadow="never" style="margin-top: 12px">
                <el-table :data="stats.top_users" size="small">
                  <el-table-column prop="user" label="用户" min-width="200" />
                  <el-table-column prop="count" label="消息数" width="120" />
                </el-table>
              </el-card>
            </template>
            <template v-else>
              <el-form label-position="top" style="max-width: 480px">
                <el-form-item label="此群启用统计">
                  <el-switch :model-value="fgOn('stats', statsViewGroup)" @change="(v) => fgSet('stats', statsViewGroup, v)" />
                  <span style="margin-left: 8px; color: #909399; font-size: 12px">关闭后只停这个群的统计，其他群不受影响</span>
                </el-form-item>
              </el-form>
              <el-divider content-position="left">此群近 7 天消息量</el-divider>
              <el-table :data="groupDayRows" size="small">
                <el-table-column prop="day" label="日期" width="140" />
                <el-table-column label="消息量">
                  <template #default="{ row }">
                    <el-progress :percentage="groupBarPct(row.count)" :show-text="false" style="width: 60%" />
                    <span style="margin-left: 8px">{{ row.count }}</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-divider content-position="left">此群发言排行 Top 20</el-divider>
              <el-table :data="statsGroup?.top_users || []" size="small">
                <el-table-column prop="user" label="用户" min-width="200" />
                <el-table-column prop="count" label="消息数" width="120" />
              </el-table>
            </template>
          </el-card>
        </section>

        <!-- 日志 -->
        <!-- 运行日志 -->
        <section v-show="tab === 'logs'">
          <el-table :data="logs" size="small" v-loading="logsLoading">
            <el-table-column prop="created_at" label="时间" width="170"><template #default="{ row }">{{ fmt(row.created_at) }}</template></el-table-column>
            <el-table-column label="级别" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'">{{ row.level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="内容" min-width="400" show-overflow-tooltip />
          </el-table>
        </section>
        </div>
      </div>
    </el-main>

    <!-- 关键词编辑 -->
    <el-dialog v-model="kwDialog" title="关键词规则" width="min(520px, calc(100vw - 24px))">
      <el-form label-width="120">
        <el-form-item label="触发词"><el-input v-model="editKw.pattern" placeholder="多个用 | 分隔" /></el-form-item>
        <el-form-item label="回复类型">
          <el-radio-group v-model="editKw.reply_type">
            <el-radio value="text">文本</el-radio>
            <el-radio value="image">图片（公网URL）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="editKw.reply_type === 'image' ? '图片URL' : '回复文本'">
          <el-input v-model="editKw.reply_content" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="触发范围">
          <el-radio-group v-model="editKw.trigger_scope">
            <el-radio value="all">全部消息</el-radio>
            <el-radio value="at">仅@触发</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="作用群">
          <el-select v-model="editKw.group_openid" style="width: 100%">
            <el-option label="所有群" value="*" />
            <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="kwDialog = false">取消</el-button>
        <el-button type="primary" @click="saveKw(editKw, true)">保存</el-button>
      </template>
    </el-dialog>

    <!-- 定时任务编辑 -->
    <el-dialog v-model="schDialog" title="定时任务" width="min(520px, calc(100vw - 24px))">
      <el-form label-width="130">
        <el-form-item label="任务名称"><el-input v-model="editSch.name" /></el-form-item>
        <el-form-item label="cron 表达式"><el-input v-model="editSch.cron" placeholder="0 9 * * * = 每天 9 点" /></el-form-item>
        <el-form-item label="目标群">
          <el-select v-model="editSch.target_group_openid" filterable allow-create default-first-option
            style="width: 100%" placeholder="选择发送到哪个群">
            <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
          </el-select>
          <span style="color: #909399; font-size: 12px">列表没有的群可直接粘贴群 openid</span>
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="editSch.task_type">
            <el-radio value="text">文本</el-radio>
            <el-radio value="image">图片URL</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="editSch.task_type === 'image' ? '图片URL' : '内容'">
          <el-input v-model="editSch.content" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="schDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSch(editSch)">保存</el-button>
      </template>
    </el-dialog>

    <!-- 规则构建器 -->
    <el-dialog v-model="ruleDialog" title="自动化规则" width="min(640px, calc(100vw - 24px))" class="rule-dialog">
      <el-form label-width="130">
        <el-form-item label="规则名称"><el-input v-model="editRule.name" /></el-form-item>
        <el-form-item label="作用群">
          <el-select v-model="editRule.group_openid" style="width: 100%">
            <el-option label="所有群" value="*" />
            <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
          </el-select>
        </el-form-item>
        <el-form-item label="触发类型">
          <el-alert v-if="!visibleTypes.length" type="warning" :closable="false" style="margin-bottom: 8px"
            title="还没有可用的触发类型：先到「插件市场」安装规则类插件（防广告基础包 / 防刷屏 / 新人进群通知 / AI 智能审核）。" />
          <el-radio-group v-model="curType">
            <el-radio v-for="t in visibleTypes" :key="t.key" :value="t.key">{{ t.label }}</el-radio>
          </el-radio-group>
          <div style="color: #909399; font-size: 12px; line-height: 1.6; margin-top: 4px">
            每个触发类型的配置在后台独立存储、互不影响。切换类型就是查看/编辑对应的那份配置，点「保存规则」才会写入后台。类型列表跟着已安装的规则类插件走。
          </div>
        </el-form-item>
        <el-form-item label="启用此类型">
          <el-switch v-model="cfg.enabled" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px">关闭则此类型不参与自动化，其他类型不受影响</span>
        </el-form-item>
        <template v-if="curType === 'ai_audit'">
          <el-alert type="info" :closable="false" style="margin-bottom: 12px"
            title="两段式：先按下面的条件筛出可疑消息（不花钱），只有筛中的才交给 AI 判定。AI 用「AI 对话」页配置的 Key。" />
          <el-divider content-position="left">送审条件（任一命中即送审，至少配一个）</el-divider>
          <el-form-item label="含关键词（每行一个）">
            <el-input v-model="sendKwText" type="textarea" :rows="2" placeholder="私我&#10;兼职" />
            <div style="display: flex; align-items: center; margin-top: 4px">
              <el-switch v-model="cfg.params.send_char_mode" size="small" />
              <span style="margin-left: 8px; color: #909399; font-size: 12px">单字模式：输入的每个字独立触发，如填「薇微V扣」→ 消息含任一字就送审（抓变体广告）</span>
            </div>
          </el-form-item>
          <el-form-item label="含正则（每行一个）">
            <el-input v-model="sendRegexText" type="textarea" :rows="2" placeholder="\\d{11}（11位连续数字）" />
          </el-form-item>
          <el-form-item label="含链接/拉群引流"><el-switch v-model="cfg.params.send_link" /></el-form-item>
          <el-form-item label="含连续数字 ≥">
            <el-input-number v-model="cfg.params.send_digit_len" :min="0" :max="30" />
            <span style="margin-left: 8px; color: #909399; font-size: 12px">0=不启用；11=手机号特征</span>
          </el-form-item>
          <el-divider content-position="left">AI 判定与费用控制</el-divider>
          <el-form-item label="判定要求（给 AI 的指令）">
            <el-input v-model="cfg.params.ai_prompt" type="textarea" :rows="3"
              placeholder="留空=默认审核广告/诈骗/引流/辱骂。可自定义，如：判断消息里的11位数字是不是手机号" />
          </el-form-item>
          <el-form-item label="模型（选填覆盖）">
            <el-input v-model="cfg.params.ai_model" style="width: 240px" placeholder="默认用 AI 对话页的模型" />
          </el-form-item>
          <el-form-item label="每日送审上限"><el-input-number v-model="cfg.params.max_per_day" :min="1" :max="5000" /></el-form-item>
          <el-form-item label="送审最小间隔（秒）"><el-input-number v-model="cfg.params.min_interval_sec" :min="0" :max="600" /></el-form-item>
        </template>
        <template v-if="curType === 'keyword'">
          <el-form-item label="关键词（每行一个）"><el-input v-model="kwText" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="匹配方式">
            <el-radio-group v-model="cfg.params.match_mode">
              <el-radio value="contains">包含</el-radio>
              <el-radio value="regex">正则</el-radio>
            </el-radio-group>
          </el-form-item>
        </template>
        <el-form-item v-if="curType === 'link'" label="同时拦截拉群引流">
          <el-switch v-model="cfg.params.block_group_invite" />
        </el-form-item>
        <template v-if="curType === 'spam'">
          <el-form-item label="窗口（秒）"><el-input-number v-model="cfg.params.spam_window" :min="3" :max="300" /></el-form-item>
          <el-form-item label="超过条数"><el-input-number v-model="cfg.params.spam_max" :min="2" :max="50" /></el-form-item>
        </template>
        <template v-if="curType === 'member_join'">
          <el-alert type="info" :closable="false" style="margin-bottom: 12px"
            title="新人进群即触发：可发欢迎语（支持 @新人），也可做管理动作（通知管理群、进群先禁言防广告、踢黑名单等）。不同群要不同欢迎语？把本规则的作用群选成那个群、改欢迎语即可。" />
          <el-divider content-position="left">欢迎语</el-divider>
          <el-form-item label="发送欢迎语"><el-switch v-model="cfg.act.reply" /></el-form-item>
          <template v-if="cfg.act.reply">
            <el-form-item label="欢迎语内容">
              <el-input v-model="cfg.act.replyContent" type="textarea" :rows="2" placeholder="欢迎 {at} 加入本群！" />
              <span style="color: #909399; font-size: 12px">变量：{at}=@新人　{user}=新人 openid　{group}=群 openid</span>
            </el-form-item>
            <el-form-item label="自动 @新人">
              <el-switch v-model="cfg.act.welcomeAt" />
              <span style="margin-left: 8px; color: #909399; font-size: 12px">文案里没写 {at} 时，自动在开头 @</span>
            </el-form-item>
            <el-form-item label="Markdown 格式"><el-switch v-model="cfg.act.replyMarkdown" /></el-form-item>
          </template>
          <el-divider content-position="left">管理动作</el-divider>
          <el-form-item label="动作延迟（秒）">
            <el-input-number v-model="cfg.params.delay_seconds" :min="0" :max="600" />
            <span style="margin-left: 8px; color: #909399; font-size: 12px">进群后等这么久再执行，0=立即；延迟几秒更自然也更稳</span>
          </el-form-item>
        </template>
        <template v-if="curType === 'msg_type'">
          <el-form-item label="要撤回的类型">
            <el-checkbox-group v-model="cfg.params.msg_types">
              <el-checkbox v-for="m in MSG_TYPE_OPTIONS" :key="m.value" :value="m.value">
                {{ m.desc }}
              </el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-alert type="info" :closable="false"
            title="成员发出所选类型的消息即自动撤回（撤回为固定动作），下方可追加禁言/踢人/通知等动作。类型为 QQ 官方接收侧的消息分类。" />
        </template>
        <el-form-item label="触发白名单">
          <el-input v-model="whitelistText" type="textarea" :rows="2" placeholder="这些 openid 的消息不触发本规则（每行一个）" />
        </el-form-item>
        <el-divider content-position="left">触发后的动作</el-divider>
        <el-form-item v-if="curType !== 'member_join' && curType !== 'msg_type'" label="撤回原消息"><el-switch v-model="cfg.act.recall" /></el-form-item>
        <el-form-item v-if="curType !== 'member_join'" label="回复一条消息">
          <el-switch v-model="cfg.act.reply" />
          <el-input v-if="cfg.act.reply" v-model="cfg.act.replyContent" type="textarea" :rows="2" style="margin-top: 8px" placeholder="支持 {user} 变量" />
        </el-form-item>
        <el-form-item label="禁言发送者">
          <el-switch v-model="cfg.act.mute" />
          <el-input-number v-if="cfg.act.mute" v-model="cfg.act.muteMinutes" :min="1" :max="43200" style="margin-left: 12px" />
          <span v-if="cfg.act.mute" style="margin-left: 8px; color: #909399">分钟（≤30天）</span>
        </el-form-item>
        <el-form-item label="踢出群聊">
          <el-switch v-model="cfg.act.kick" />
          <el-checkbox v-if="cfg.act.kick" v-model="cfg.act.kickBlacklist" style="margin-left: 12px">同时拉黑（内邀）</el-checkbox>
        </el-form-item>
        <el-form-item label="加入群黑名单">
          <el-switch v-model="cfg.act.blacklist" />
          <span style="margin-left: 12px; color: #909399; font-size: 12px">内邀接口，未开通时自动跳过</span>
        </el-form-item>
        <el-form-item label="通知到主人">
          <el-switch v-model="cfg.act.notify" />
          <template v-if="cfg.act.notify">
            <el-input v-model="cfg.act.notifyTarget" style="margin-top: 8px"
              placeholder="填 user_openid（群里发 /我的ID 获取）；留空 = 不通知" />
            <span style="color: #909399; font-size: 12px">规则命中后机器人私聊通知这个人（QQ 官方要求对方先给机器人发过消息才能收到）</span>
          </template>
        </el-form-item>
        <el-form-item label="记录命中日志"><el-switch v-model="cfg.act.log" /></el-form-item>
        <el-form-item v-if="editRule.id && !cfg._deleted">
          <el-button type="danger" plain size="small" @click="deleteTypeConfig">删除此类型的配置</el-button>
          <span style="margin-left: 8px; color: #909399; font-size: 12px">点「保存规则」后，「{{ typeLabel(curType) }}」将从后台移除</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialog = false">取消</el-button>
        <el-button type="primary" @click="submitRule">保存规则</el-button>
      </template>
    </el-dialog>
    <!-- 指令面板新建 -->
    <el-dialog v-model="panelDialog" title="新建指令面板" width="min(620px, calc(100vw - 24px))">
      <el-form label-width="110">
        <el-form-item label="生效场景">
          <el-radio-group v-model="panelForm.scope">
            <el-radio value="group">群聊</el-radio>
            <el-radio value="c2c">单聊</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="生效范围">
          <el-radio-group v-model="panelForm.target_type">
            <el-radio value="all">全部{{ panelForm.scope === 'group' ? '群' : '用户' }}</el-radio>
            <el-radio value="specific">指定{{ panelForm.scope === 'group' ? '群' : '用户' }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="panelForm.target_type === 'specific' && panelForm.scope === 'group'" label="指定群">
          <el-select v-model="panelForm.group_openids" multiple filterable style="width: 100%" placeholder="最多选 20 个群">
            <el-option v-for="g in knownGroups" :key="g.group_openid" :label="gLabel(g.group_openid)" :value="g.group_openid" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="panelForm.target_type === 'specific' && panelForm.scope === 'c2c'" label="用户 openid">
          <el-input v-model="panelForm.userOpenids" type="textarea" :rows="2" placeholder="每行一个 user_openid，最多 20" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="panelForm.remark" /></el-form-item>
        <el-divider content-position="left">指令项（最多 20）</el-divider>
        <div v-for="(item, i) in panelForm.items" :key="i" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center; flex-wrap: wrap">
          <el-input v-model="item.name" placeholder="名称 ≤7汉字" style="width: 150px" />
          <el-input v-model="item.desc" placeholder="描述(选填)" style="width: 150px" />
          <el-select v-model="item.type" style="width: 110px">
            <el-option label="指令" value="command" />
            <el-option label="链接" value="link" />
          </el-select>
          <el-input v-if="item.type === 'command'" v-model="item.command" placeholder="/帮助" style="width: 170px" />
          <el-input v-if="item.type === 'link'" v-model="item.link" placeholder="https://..." style="width: 170px" />
          <el-checkbox v-model="item.only_admin">仅管理员可见</el-checkbox>
          <el-button size="small" type="danger" link @click="panelForm.items.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" @click="panelForm.items.push({ name: '', desc: '', type: 'command', command: '', link: '', only_admin: false })" :disabled="panelForm.items.length >= 20">+ 加指令项</el-button>
      </el-form>
      <template #footer>
        <el-button @click="panelDialog = false">取消</el-button>
        <el-button type="primary" @click="submitPanel" :loading="busy">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, computed, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { http, errText } from '../api'
import ScopePanel from '../components/ScopePanel.vue'

const props = defineProps({ id: { type: String, required: true } })

const loaded = ref(false)
const busy = ref(false)
const tab = ref('home')
const navGroups = [
  { title: '群管', items: [
    { key: 'automation', icon: '⚙️', label: '群管自动化', desc: '总开关、自动化规则、管理员名单' },
    { key: 'tools', icon: '🧰', label: '群管理工具', desc: '禁言/踢人/黑名单/成员/审批策略' },
    { key: 'approval', icon: '🚪', label: '入群审批', desc: '申请通知与人工/自动审批' },
    { key: 'report', icon: '📮', label: '举报通道', desc: '群友举报转发到管理群' },
    { key: 'hits', icon: '🎯', label: '命中记录', desc: '自动化规则触发历史' },
  ]},
  { title: '消息与互动', items: [
    { key: 'keywords', icon: '💬', label: '关键词回复', desc: '触发词 → 自动回复' },
    { key: 'ai', icon: '🤖', label: 'AI 对话', desc: '大模型问答（自带 Key）' },
    { key: 'menu', icon: '📋', label: '菜单与面板', desc: '单聊菜单、指令面板' },
  ]},
  { title: '运营', items: [
    { key: 'schedule', icon: '⏰', label: '定时推送', desc: 'cron 定时任务' },
    { key: 'fun', icon: '📅', label: '每日签到', desc: '/签到 打卡与连续天数' },
    { key: 'stats', icon: '📊', label: '统计', desc: '活跃度与排行榜' },
    { key: 'logs', icon: '📜', label: '运行日志', desc: '连接、发送与错误记录' },
  ]},
  { title: '平台', items: [
    { key: 'market', icon: '🛍️', label: '插件市场', desc: '预设插件包一键安装' },
    { key: 'overview', icon: '🩺', label: '概览 / 自检', desc: '实例状态诊断与修复指引' },
  ]},
]
const inst = ref({})
const knownGroups = ref([])
const keywords = ref([])
const schedules = ref([])
const hits = ref([])
const joinRequests = ref([])
const officialRequests = ref([])
const officialReqLoading = ref(false)
const logs = ref([])
const logsLoading = ref(false)
const stats = ref({ messages_by_day: {}, top_users: [] })
const ai = ref(null)
const approval = ref(null)
const approvalGroupKeywords = ref('')
const approvalGroupSaving = ref(false)
const report = ref(null)
const signin = ref(null)
const aiKey = ref('')
const ga = reactive({ master_enabled: true, admin_openids: '', default_notify_group: '' })
const rules = ref([])
const availableTypes = ref([]) // 触发类型门禁：装了哪个规则类插件，才可用哪些触发类型
async function reloadRules() {
  const r = (await http.get(`/instances/${props.id}/rules`)).data
  rules.value = r.items
  availableTypes.value = r.available_types || []
}
const pluginItems = ref([])
const ruleDialog = ref(false)
const editRule = ref({ name: '', group_openid: '*', priority: 100 })
const RULE_TYPES = [
  { key: 'keyword', label: '关键词' },
  { key: 'link', label: '链接/引流' },
  { key: 'spam', label: '刷屏' },
  { key: 'member_join', label: '新人进群' },
  { key: 'msg_type', label: '消息类型撤回' },
  { key: 'ai_audit', label: 'AI 审核' },
]
const MSG_TYPE_OPTIONS = [
  { value: '文本', desc: '纯文字消息' },
  { value: '图片', desc: '图片消息' },
  { value: '视频', desc: '视频消息' },
  { value: '语音', desc: '语音消息' },
  { value: '文件', desc: '文件（文档/压缩包等）' },
  { value: '结构化卡片', desc: '卡片消息（官方 message_type=3）' },
  { value: '引用消息', desc: '引用回复（官方 message_type=103）' },
]
const typeLabel = (t) => (RULE_TYPES.find((x) => x.key === t) || {}).label || t
const curType = ref('keyword')
const typeConfigs = reactive({}) // 每个触发类型一份独立配置：{ rowId, enabled, params, act }
const touched = reactive({})     // 用户在该类型下改过东西，保存时才创建对应的后台存储
let suppressWatch = false        // 装配槽位期间暂停 touched 标记
const cfg = computed(() => typeConfigs[curType.value] || { rowId: null, enabled: false, params: {}, act: {} })
// 类型门禁：新建时只显示已装插件解锁的类型；编辑时自己那条的类型始终可见
const visibleTypes = computed(() => {
  const list = RULE_TYPES.filter((t) => availableTypes.value.includes(t.key))
  const own = editRule.value._ownType
  if (own && !list.some((t) => t.key === own)) {
    const rt = RULE_TYPES.find((t) => t.key === own)
    if (rt) list.unshift(rt)
  }
  return list
})
const kwText = computed({
  get: () => (cfg.value.params.keywords || []).join('\n'),
  set: (v) => { cfg.value.params.keywords = v.split('\n') },
})
const whitelistText = computed({
  get: () => (cfg.value.params.whitelist_openids || []).join('\n'),
  set: (v) => { cfg.value.params.whitelist_openids = v.split('\n') },
})
const sendKwText = computed({
  get: () => (cfg.value.params.send_keywords || []).join('\n'),
  set: (v) => { cfg.value.params.send_keywords = v.split('\n') },
})
const sendRegexText = computed({
  get: () => (cfg.value.params.send_regex || []).join('\n'),
  set: (v) => { cfg.value.params.send_regex = v.split('\n') },
})
const personaGroups = ref([])
const personaScope = ref('global')
const personaEdit = ref(null)
const newPersonaGroup = ref('')
const selfcheckGroup = ref('')
const selfchecking = ref(false)
const selfcheckResult = ref(null)
const toolGroup = ref('')
const toolOpenids = ref('')
const toolMuteMinutes = ref(10)
const kickBlacklist = ref(false)
const muteMembers = ref([])
const blacklistRows = ref([])
const memberRows = ref([])
const kwDialog = ref(false)
const fgRows = ref([])

// 功能总览卡片上的启停状态：与各页签/插件市场同源（config 总开关、按群 '*' 默认行、群管总开关）
const featureStatus = computed(() => {
  const star = {}
  for (const r of fgRows.value) {
    if (r.group_openid === '*') star[r.feature] = !!r.enabled
  }
  const cfg = (v) => !!(v && v.enabled)
  const feature = (k) => (star[k] === undefined ? true : star[k]) // 无记录 = 默认开启
  return {
    automation: !!ga.master_enabled,
    approval: cfg(approval.value),
    report: cfg(report.value),
    keywords: feature('keywords'),
    ai: cfg(ai.value),
    schedule: feature('schedule'),
    fun: cfg(signin.value),
    stats: feature('stats'),
  }
})
const scopes = reactive({ approval: 'global', report: 'global', fun: 'global', keywords: 'global' })

// 统计查看范围：'' = 全部群合计；选中群时拉取该群自己的统计
const statsViewGroup = ref('')
const statsGroup = ref(null)
watch(statsViewGroup, (gid) => {
  statsGroup.value = null
  if (!gid) return
  http.get(`/instances/${props.id}/stats`, { params: { group_openid: gid } })
    .then((r) => { statsGroup.value = r.data })
    .catch(() => {})
})

const kwScoped = computed(() => keywords.value.filter((k) => k.group_openid === scopes.keywords))

function fgOn(feature, gid) {
  const r = fgRows.value.find((x) => x.feature === feature && x.group_openid === gid)
  return r ? r.enabled : true
}
function fgConfigured(feature) {
  return fgRows.value.filter((x) => x.feature === feature && x.group_openid !== '*').map((x) => x.group_openid)
}
async function loadFg() {
  fgRows.value = (await http.get(`/instances/${props.id}/feature-groups`)).data.items
}
async function fgSet(feature, gid, enabled) {
  try {
    await http.put(`/instances/${props.id}/feature-groups/${feature}/${gid}`, { enabled })
    await loadFg()
    await refreshData()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}
// 签到页的范围键是 scopes.fun，但开关走的 feature 是 signin，包装对齐两者
async function fgPickSignin(gid) {
  if (!gid) return
  if (!fgConfigured('signin').includes(gid)) await fgSet('signin', gid, true)
  scopes.fun = gid
}
async function approvalPick(gid) {
  if (!gid) return
  if (!fgConfigured('approval').includes(gid)) await fgSet('approval', gid, true)
  scopes.approval = gid
  approvalGroupKeywords.value = ''
  try {
    approvalGroupKeywords.value = (await http.get(`/instances/${props.id}/approval-groups/${encodeURIComponent(gid)}`)).data.auto_approve_keywords || ''
  } catch (e) {
    ElMessage.error(errText(e))
  }
}
async function saveApprovalGroup() {
  if (scopes.approval === 'global') return
  approvalGroupSaving.value = true
  try {
    await http.put(`/instances/${props.id}/approval-groups/${encodeURIComponent(scopes.approval)}`, {
      auto_approve_keywords: approvalGroupKeywords.value,
    })
    ElMessage.success(approvalGroupKeywords.value.trim() ? '该群关键词已保存' : '已清空该群关键词，将继承全局设置')
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    approvalGroupSaving.value = false
  }
}
async function fgPick(feature, gid) {
  if (!gid) return
  if (!fgConfigured(feature).includes(gid)) await fgSet(feature, gid, true)
  scopes[feature] = gid
}
const schDialog = ref(false)
const editKw = ref({})
const editSch = ref({})
const menuEdit = ref([])
const menuVersion = ref('')
const menuLoading = ref(false)
const previewSub = ref([])
const panels = ref([])
const panelScope = ref('group')
const panelsLoading = ref(false)
const panelDialog = ref(false)
const panelForm = reactive({ scope: 'group', target_type: 'all', group_openids: [], userOpenids: '', remark: '', items: [{ name: '', desc: '', type: 'command', command: '', link: '', only_admin: false }] })
let timer = null

const keywordOptions = computed(() => {
  const out = []
  for (const k of keywords.value) {
    if (!k.enabled) continue
    for (const p of (k.pattern || '').split('|')) {
      const s = p.trim()
      if (s && !out.includes(s)) out.push(s)
    }
  }
  return out
})

function charWidth(s) {
  return String(s || '').split('').reduce((a, c) => a + (c.charCodeAt(0) > 255 ? 2 : 1), 0)
}

function _menuPayloadItem(item) {
  const out = { name: item.name, type: item.type }
  if (item.type === 'send_message') out.send_message = item.send_message
  if (item.type === 'link') out.link = item.link
  if (item.type === 'switch') {
    out.switch = { switch_id: item.switch_id || '', default: !!item.switch_default }
  }
  if (item.type === 'menu') {
    out.sub_menu_items = (item.sub_menu_items || []).map((s) => {
      const so = { name: s.name, type: s.type }
      if (s.type === 'send_message') so.send_message = s.send_message
      if (s.type === 'link') so.link = s.link
      return so
    })
  }
  return out
}

async function loadMenu() {
  menuLoading.value = true
  try {
    const data = (await http.get(`/instances/${props.id}/menu`)).data
    menuVersion.value = data.version || ''
    const items = data.menu?.items || []
    menuEdit.value = items.map((it) => ({
      type: it.type || 'send_message',
      name: it.name || '',
      send_message: it.send_message || '',
      link: it.link || '',
      switch_id: it.switch?.switch_id || '',
      switch_default: !!it.switch?.default,
      sub_menu_items: (it.sub_menu_items || []).map((s) => ({
        type: s.type || 'send_message', name: s.name || '', send_message: s.send_message || '', link: s.link || '',
      })),
    }))
    ElMessage.success('已拉取官方当前菜单')
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    menuLoading.value = false
  }
}

function fillMenuExample() {
  menuEdit.value = [
    { type: 'send_message', name: '帮助', send_message: '/帮助', link: '', switch_id: '', switch_default: false, _kwPick: null, sub_menu_items: [] },
    { type: 'menu', name: '更多', send_message: '', link: '', switch_id: '', switch_default: false, _kwPick: null, sub_menu_items: [
      { type: 'send_message', name: '签到', send_message: '/签到', link: '' },
      { type: 'send_message', name: '抽签', send_message: '/抽签', link: '' },
    ] },
  ]
}

function addMenuItem() {
  menuEdit.value.push({ type: 'send_message', name: '', send_message: '', link: '', switch_id: '', switch_default: false, _kwPick: null, sub_menu_items: [] })
}

function addSubItem(item) {
  if (!item.sub_menu_items) item.sub_menu_items = []
  item.sub_menu_items.push({ type: 'send_message', name: '', send_message: '', link: '' })
}

function pickKeyword(item) {
  if (item._kwPick) {
    item.name = item._kwPick.slice(0, 5)
    item.send_message = item._kwPick
  }
}

async function saveMenu() {
  busy.value = true
  try {
    const payload = { items: menuEdit.value.map(_menuPayloadItem) }
    const data = (await http.put(`/instances/${props.id}/menu`, payload)).data
    menuVersion.value = data.version || menuVersion.value
    ElMessage.success('已保存到 QQ，单聊窗口即可见')
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

function previewSubToggle(item) {
  previewSub.value = item.type === 'menu' ? (item.sub_menu_items || []) : []
}

async function loadPanels() {
  panelsLoading.value = true
  try {
    const data = (await http.get(`/instances/${props.id}/panels`, { params: { scope: panelScope.value } })).data
    panels.value = data.panels || data.items || []
  } catch (e) {
    panels.value = []
    ElMessage.error(errText(e))
  } finally {
    panelsLoading.value = false
  }
}

async function submitPanel() {
  const items = panelForm.items.filter((i) => i.name && (i.type === 'command' ? i.command : i.link))
  if (!items.length) return ElMessage.warning('至少要有一个填好的指令项')
  busy.value = true
  try {
    await http.post(`/instances/${props.id}/panels`, {
      scope: panelForm.scope,
      target_type: panelForm.target_type,
      group_openids: panelForm.scope === 'group' ? panelForm.group_openids : [],
      remark: panelForm.remark,
      items: items.map((i) => ({
        name: i.name, desc: i.desc || '', type: i.type,
        command: i.type === 'command' ? i.command : '', link: i.type === 'link' ? i.link : '',
        only_admin: i.only_admin,
      })),
    })
    ElMessage.success('面板已创建')
    panelDialog.value = false
    panelScope.value = panelForm.scope
    loadPanels()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

async function deletePanel(row) {
  try {
    await http.delete(`/instances/${props.id}/panels/${row.panel_id}`)
    ElMessage.success('已删除')
    loadPanels()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

const globalMuteText = computed(() => {
  const gr = selfcheckResult.value?._globalMute
  if (!gr) return '未查询'
  const mode = gr.mode || gr.global_rule?.mode
  return { none: '未开启', always: '已开启（永久）', schedule: '定时禁言中' }[mode] || (mode || '未知')
})

const knownGroupIds = computed(() => [
  ...knownGroups.value.map((g) => g.group_openid),
  ...personaGroups.value.map((g) => g.group_openid),
].filter((v, i, arr) => arr.indexOf(v) === i))

function selectPersonaScope(scope) {
  personaScope.value = scope
  if (scope === 'global') {
    personaEdit.value = null
    return
  }
  const row = personaGroups.value.find((g) => g.group_openid === scope)
  personaEdit.value = row ? { ...row } : null
}

async function refreshPersonaGroups() {
  personaGroups.value = (await http.get(`/instances/${props.id}/ai-personas`)).data.items
}

async function onPersonaGroupPick(gid) {
  if (!gid) return
  try {
    if (!personaGroups.value.some((g) => g.group_openid === gid)) {
      await http.put(`/instances/${props.id}/ai-personas/${gid}`, {
        chat_persona_name: '', chat_persona_desc: '', audit_persona_name: '', audit_persona_desc: '',
      })
      await refreshPersonaGroups()
    }
    selectPersonaScope(gid)
    newPersonaGroup.value = ''
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function saveGroupPersona() {
  try {
    await http.put(`/instances/${props.id}/ai-personas/${personaScope.value}`, personaEdit.value)
    await refreshPersonaGroups()
    await refreshData()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function deleteGroupPersona() {
  try {
    await http.delete(`/instances/${props.id}/ai-personas/${personaScope.value}`)
    ElMessage.success('已删除，该群回退为全局人设')
    await refreshPersonaGroups()
    await refreshData()
    personaScope.value = 'global'
    personaEdit.value = null
  } catch (e) {
    ElMessage.error(errText(e))
  }
}


const dayRows = computed(() =>
  Object.entries(stats.value.messages_by_day || {}).map(([day, count]) => ({ day, count })),
)
function barPct(v) {
  const max = Math.max(...dayRows.value.map((r) => r.count), 1)
  return Math.round((v / max) * 100)
}
const groupDayRows = computed(() =>
  Object.entries((statsGroup.value || {}).messages_by_day || {}).map(([day, count]) => ({ day, count })),
)
function groupBarPct(v) {
  const max = Math.max(...groupDayRows.value.map((r) => r.count), 1)
  return Math.round((v / max) * 100)
}
function statusType(s) { return { online: 'success', connecting: 'warning', error: 'danger', offline: 'info' }[s] || 'info' }
function statusText(s) { return { online: '在线', connecting: '连接中', error: '异常', offline: '离线' }[s] || s }
function fmt(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '—' }
function shortId(s) { return s && s.length > 16 ? s.slice(0, 8) + '…' + s.slice(-6) : (s || '') }
function gLabel(gid) {
  if (!gid || gid === '*') return gid || ''
  const g = knownGroups.value.find((k) => k.group_openid === gid)
  return (g && g.group_name) ? g.group_name : shortId(gid)
}

// 主动拉群名（进群后点按钮立即补全下拉列表；首次加载时也会静默尝试一次）
const groupsRefreshing = ref(false)
async function refreshGroupNames(manual = false) {
  if (manual) groupsRefreshing.value = true
  try {
    const r = await http.post(`/instances/${props.id}/groups/refresh-names`)
    knownGroups.value = (await http.get(`/instances/${props.id}/groups`)).data.items
    if (manual) ElMessage.success(r.data.updated ? `已更新 ${r.data.updated} 个群名` : '群名已是最新')
  } catch (e) {
    if (manual) ElMessage.error(errText(e))
  } finally {
    if (manual) groupsRefreshing.value = false
  }
}
function roleName(state) {
  const role = state?.role || state?.bot_role
  return { admin: '群管理员', owner: '群主', member: '普通成员' }[role] || role || '未知'
}
function msgMode(state) {
  const mode = state?.receive_message_mode || state?.message_mode
  return { all: '获取群内全部消息', only_mention: '仅@机器人的消息', mention_and_context: '@及上下文' }[mode] || mode || '未知'
}
function triggerText(row) {
  const p = row.trigger_params || {}
  // 综合规则行：列出启用的触发类型
  if (row.type_configs && typeof row.type_configs === 'object') {
    const labels = RULE_TYPES.filter((t) => row.type_configs[t.key] && row.type_configs[t.key].enabled !== false)
      .map((t) => t.label)
    return labels.length ? `综合：${labels.join(' / ')}` : '（未启用任何类型）'
  }
  if (row.trigger_type === 'keyword') {
    const kws = (p.keywords || []).join('、')
    return `关键词：${kws.slice(0, 40)}${p.match_mode === 'regex' ? '（正则）' : ''}`
  }
  if (row.trigger_type === 'link') return '发送链接' + (p.block_group_invite !== false ? ' / 拉群引流' : '')
  if (row.trigger_type === 'spam') return `${p.spam_window || 10}秒内超过${p.spam_max || 5}条`
  if (row.trigger_type === 'member_join') return '新人进群'
  if (row.trigger_type === 'msg_type') return `消息类型：${(p.msg_types || []).join('、') || '（未选）'}`
  if (row.trigger_type === 'ai_audit') {
    const conds = []
    if (p.send_digit_len) conds.push(`≥${p.send_digit_len}位数字`)
    if (p.send_link) conds.push('链接')
    if ((p.send_keywords || []).length) conds.push(p.send_char_mode ? '单字' : '关键词')
    if ((p.send_regex || []).length) conds.push('正则')
    return `AI审核[${conds.join('+') || '未配置条件'}]`
  }
  return row.trigger_type
}
function actionsText(actions) {
  if (!actions?.length) return '（无动作）'
  const names = { recall: '撤回', reply: '回复', mute: '禁言', kick: '踢出', blacklist: '拉黑', notify: '通知', log: '记录' }
  return actions.map((a) => {
    let t = names[a.type] || a.type
    if (a.type === 'mute') t += `${a.minutes}分钟`
    if (a.type === 'kick' && a.blacklist) t += '+拉黑'
    return t
  }).join(' → ')
}

function slotSkeleton(t) {
  return {
    rowId: null,
    enabled: true,
    params: {
      match_mode: 'contains', block_group_invite: true, spam_window: 10, spam_max: 5,
      send_link: true, send_digit_len: t === 'ai_audit' ? 11 : 0, send_char_mode: false,
      send_long_text: 0, delay_seconds: 0, max_per_day: 200, min_interval_sec: 3,
      ai_prompt: '', ai_model: '', keywords: [], send_keywords: [], send_regex: [], whitelist_openids: [],
      msg_types: t === 'msg_type' ? ['图片'] : [],
    },
    act: {
      recall: false, reply: false, replyContent: '', welcomeAt: false, replyMarkdown: false,
      mute: false, muteMinutes: 10, kick: false, kickBlacklist: false, blacklist: false, notify: false, notifyTarget: '', log: true,
    },
  }
}

function slotFromTypeConfig(row, t, c) {
  const s = slotSkeleton(t)
  s.rowId = row.id
  s.enabled = c.enabled !== false
  Object.assign(s.params, c.params || {})
  const find = (x) => (c.actions || []).find((a) => a.type === x) || {}
  Object.assign(s.act, {
    recall: !!find('recall').type,
    reply: !!find('reply').type,
    replyContent: find('reply').content || '',
    welcomeAt: !!find('reply').at,
    replyMarkdown: !!find('reply').markdown,
    mute: !!find('mute').type,
    muteMinutes: find('mute').minutes || 10,
    kick: !!find('kick').type,
    kickBlacklist: !!find('kick').blacklist,
    blacklist: !!find('blacklist').type,
    notify: !!find('notify').type,
    notifyTarget: find('notify').target || '',
    log: (c.actions || []).some((a) => a.type === 'log'),
  })
  return s
}

function slotFromRow(r) {
  const s = slotSkeleton(r.trigger_type)
  s.rowId = r.id
  s.enabled = !!r.enabled
  Object.assign(s.params, r.trigger_params || {})
  const find = (t) => (r.actions || []).find((a) => a.type === t) || {}
  Object.assign(s.act, {
    recall: !!find('recall').type,
    reply: !!find('reply').type,
    replyContent: find('reply').content || '',
    welcomeAt: !!find('reply').at,
    replyMarkdown: !!find('reply').markdown,
    mute: !!find('mute').type,
    muteMinutes: find('mute').minutes || 10,
    kick: !!find('kick').type,
    kickBlacklist: !!find('kick').blacklist,
    blacklist: !!find('blacklist').type,
    notify: !!find('notify').type,
    notifyTarget: find('notify').target || '',
    log: r.actions?.some((a) => a.type === 'log') !== false,
  })
  return s
}

function openRuleDialog(row) {
  suppressWatch = true
  const shared = row || {}
  editRule.value = { id: shared.id || null, name: shared.name || '', group_openid: shared.group_openid || '*', priority: shared.priority ?? 100, _ownType: shared.trigger_type || '' }
  const tc = row && row.type_configs && typeof row.type_configs === 'object' ? row.type_configs : null
  for (const t of RULE_TYPES) {
    if (tc) {
      // 综合规则行：每个类型的配置都在这一行里，直接读
      typeConfigs[t.key] = tc[t.key]
        ? slotFromTypeConfig(row, t.key, tc[t.key])
        : { ...slotSkeleton(t.key), rowId: row.id, enabled: false }
    } else if (row) {
      // 旧格式单类型行：自己的类型读行数据，其余类型给空槽位（保存时升级为综合格式）
      typeConfigs[t.key] = t.key === row.trigger_type
        ? slotFromRow(row)
        : { ...slotSkeleton(t.key), rowId: row.id, enabled: false }
    } else {
      typeConfigs[t.key] = slotSkeleton(t.key)
      touched[t.key] = false
    }
  }
  if (row) for (const t of RULE_TYPES) touched[t.key] = false
  curType.value = row ? row.trigger_type || 'keyword' : 'keyword'
  suppressWatch = false
  ruleDialog.value = true
}

// 用户在当前查看的类型下改了任何东西，保存时才为该类型创建后台存储
watch(typeConfigs, () => {
  if (!suppressWatch) touched[curType.value] = true
}, { deep: true })

function buildActionsFor(t, c) {
  const list = []
  // 消息类型撤回：撤回是固定动作，不需开关
  if ((c.act.recall || t === 'msg_type') && t !== 'member_join') list.push({ type: 'recall' })
  if (c.act.reply && c.act.replyContent) {
    // 新人进群的欢迎语带 @/markdown 标记，引擎按这些发
    const action = { type: 'reply', content: c.act.replyContent }
    if (t === 'member_join') {
      if (c.act.welcomeAt) action.at = true
      if (c.act.replyMarkdown) action.markdown = true
    }
    list.push(action)
  }
  if (c.act.mute) list.push({ type: 'mute', minutes: c.act.muteMinutes })
  if (c.act.kick) list.push({ type: 'kick', blacklist: c.act.kickBlacklist })
  if (c.act.blacklist) list.push({ type: 'blacklist', op: 'add' })
  // 通知到主人：target=user openid；留空=不通知
  if (c.act.notify) list.push({ type: 'notify', target: (c.act.notifyTarget || '').trim() })
  if (c.act.log) list.push({ type: 'log' })
  return list
}

const cleanList = (arr) => (arr || []).map((s) => String(s).trim()).filter(Boolean)

async function submitRule() {
  if (!editRule.value.name.trim()) {
    ElMessage.warning('请填写规则名称')
    return
  }
  if (!visibleTypes.value.length) {
    ElMessage.warning('还没有可用的触发类型，请先在插件市场安装规则类插件')
    return
  }
  // 组装六个类型各自的存储：互不影响；行级总开关（列表里的启用）保持不变
  const type_configs = {}
  for (const t of RULE_TYPES) {
    const c = typeConfigs[t.key]
    if (c._deleted) continue
    type_configs[t.key] = {
      enabled: !!c.enabled,
      params: {
        ...c.params,
        keywords: cleanList(c.params.keywords),
        send_keywords: cleanList(c.params.send_keywords),
        send_regex: cleanList(c.params.send_regex),
        whitelist_openids: cleanList(c.params.whitelist_openids),
      },
      actions: buildActionsFor(t.key, c),
    }
  }
  const payload = {
    name: editRule.value.name.trim(),
    group_openid: editRule.value.group_openid,
    priority: editRule.value.priority,
    trigger_type: curType.value,
    trigger_params: { ...typeConfigs[curType.value].params },
    actions: [...typeConfigs[curType.value].actions],
    type_configs,
  }
  try {
    if (editRule.value.id) {
      await http.put(`/instances/${props.id}/rules/${editRule.value.id}`, payload)
    } else {
      if (!RULE_TYPES.some((t) => touched[t.key])) {
        ruleDialog.value = false
        return
      }
      await http.post(`/instances/${props.id}/rules`, payload)
    }
    ruleDialog.value = false
    ElMessage.success('规则已保存，各类型独立生效')
    await reloadRules()
    await refreshData()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function deleteTypeConfig() {
  const t = curType.value
  typeConfigs[t]._deleted = true
  touched[t] = true
  ElMessage.success('点「保存规则」后，该类型将从后台移除')
}

async function saveRule(row) {
  try {
    await http.put(`/instances/${props.id}/rules/${row.id}`, row)
    ElMessage.success('已保存')
    await refreshData(true)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function delRule(row) {
  await http.delete(`/instances/${props.id}/rules/${row.id}`)
  rules.value = rules.value.filter((r) => r.id !== row.id)
  await refreshData()
}

async function saveGa() {
  try {
    await http.put(`/instances/${props.id}/config/groupadmin`, ga)
    ElMessage.success('已保存')
    await refreshData(true)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

function ids() {
  return toolOpenids.value.split(/[,，\s]+/).filter(Boolean)
}

async function queryMute() {
  if (!toolGroup.value) return ElMessage.warning('先选择操作群')
  try {
    const data = (await http.get(`/instances/${props.id}/groups/${toolGroup.value}/mute-state`)).data
    muteMembers.value = data.members || []
    ElMessage.success(muteMembers.value.length ? `共 ${muteMembers.value.length} 人禁言中` : '当前没有成员被禁言')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function doMute() {
  try {
    await http.post(`/instances/${props.id}/groups/${toolGroup.value}/mute`, { member_openids: ids(), minutes: toolMuteMinutes.value })
    ElMessage.success('已执行禁言')
    queryMute()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function doUnmute() {
  try {
    await http.post(`/instances/${props.id}/groups/${toolGroup.value}/unmute`, { member_openids: ids() })
    ElMessage.success('已执行解禁')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function doKick() {
  try {
    await http.post(`/instances/${props.id}/groups/${toolGroup.value}/kick`, { member_openids: ids(), add_to_blacklist: kickBlacklist.value })
    ElMessage.success('已执行移除')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function queryBlacklist() {
  if (!toolGroup.value) return ElMessage.warning('先选择操作群')
  try {
    const data = (await http.get(`/instances/${props.id}/groups/${toolGroup.value}/blacklist`)).data
    blacklistRows.value = data.members || data.blacklist || data.items || []
    if (!blacklistRows.value.length) ElMessage.success('黑名单为空')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function doBlacklist(op) {
  try {
    await http.post(`/instances/${props.id}/groups/${toolGroup.value}/blacklist`, { op, member_openids: ids() })
    ElMessage.success('已执行')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function queryMembers() {
  if (!toolGroup.value) return ElMessage.warning('先选择操作群')
  try {
    const data = (await http.get(`/instances/${props.id}/groups/${toolGroup.value}/members`)).data
    memberRows.value = data.members || data.items || []
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function pullOfficialRequests() {
  if (!toolGroup.value) return ElMessage.warning('请先在上方选择群')
  officialReqLoading.value = true
  try {
    const gid = toolGroup.value
    const data = (await http.get(`/instances/${props.id}/groups/${gid}/join-requests-official`)).data
    officialRequests.value = data.requests || data.items || []
    if (!officialRequests.value.length) ElMessage.success('没有待处理的入群申请')
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    officialReqLoading.value = false
  }
}

async function runSelfcheck() {
  if (!selfcheckGroup.value) {
    ElMessage.warning('请选择或填写群 openid')
    return
  }
  selfchecking.value = true
  try {
    selfcheckResult.value = (
      await http.post(`/instances/${props.id}/selfcheck`, { group_openid: selfcheckGroup.value })
    ).data
    try {
      const muteState = (await http.get(`/instances/${props.id}/groups/${selfcheckGroup.value}/mute-state`)).data
      selfcheckResult.value._globalMute = muteState.global_rule || muteState
    } catch { /* 禁言状态查询失败不阻塞自检 */ }
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    selfchecking.value = false
  }
}

// 功能型插件（关键词/统计/定时推送）的总开关：和插件市场的启停是同一个后台存储
async function toggleFeature(key, on) {
  try {
    if (on) {
      await http.post(`/instances/${props.id}/plugins/${key}/install`)
      ElMessage.success('已开启，即时生效')
    } else {
      await http.delete(`/instances/${props.id}/plugins/${key}`)
      ElMessage.success('已停用，即时生效')
    }
  } catch (e) {
    ElMessage.error(errText(e))
  }
  await refreshData()
}

async function installPlugin(p) {
  busy.value = true
  try {
    await http.post(`/instances/${props.id}/plugins/${p.key}/install`)
    ElMessage.success(p.type === 'rules' ? '已安装，规则即时生效' : '已启用，去对应页签完善配置')
    await refreshData()
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

async function uninstallPlugin(p) {
  try {
    await http.delete(`/instances/${props.id}/plugins/${p.key}`)
    ElMessage.success(p.type === 'rules' ? '已卸载（生成的规则已删除）' : '已停用（参数保留）')
    await refreshData()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

function goTab(name) {
  tab.value = name
}

async function refreshData(force = false) {
  // 焦点在输入框/文本域里时跳过，避免覆盖正在编辑的内容；用户显式操作传 force=true 强制刷新
  const editing = ["INPUT", "TEXTAREA"].includes(
    (document.activeElement || {}).tagName || ""
  );
  if (editing && !force) return;
  const [aiC, ap, sn, gaC, rulesC, groupsC, rpC, plC] = await Promise.all([
    http.get(`/instances/${props.id}/config/ai`),
    http.get(`/instances/${props.id}/config/approval`),
    http.get(`/instances/${props.id}/config/signin`),
    http.get(`/instances/${props.id}/config/groupadmin`),
    http.get(`/instances/${props.id}/rules`),
    http.get(`/instances/${props.id}/groups`),
    http.get(`/instances/${props.id}/config/report`),
    http.get(`/instances/${props.id}/plugins`),
  ])
  ai.value = aiC.data
  approval.value = ap.data
  report.value = rpC.data
  signin.value = sn.data
  Object.assign(ga, gaC.data)
  rules.value = rulesC.data.items
  availableTypes.value = rulesC.data.available_types || []
  knownGroups.value = groupsC.data.items
  pluginItems.value = plC.data.items
  if (!loaded.value) refreshGroupNames()
  await loadFg()
  keywords.value = (await http.get(`/instances/${props.id}/keywords`)).data.items
  schedules.value = (await http.get(`/instances/${props.id}/schedules`)).data.items
  stats.value = (await http.get(`/instances/${props.id}/stats`)).data
  personaGroups.value = (await http.get(`/instances/${props.id}/ai-personas`)).data.items
  if (!toolGroup.value && knownGroups.value.length) toolGroup.value = knownGroups.value[0].group_openid
  loaded.value = true
}

async function loadAll() {
  try {
    inst.value = (await http.get('/instances')).data.items.find((i) => String(i.id) === props.id) || {}
    await refreshData()
    hits.value = (await http.get(`/instances/${props.id}/moderation-hits`)).data.items
    joinRequests.value = (await http.get(`/instances/${props.id}/join-requests`)).data.items
    logsLoading.value = true
    logs.value = (await http.get(`/instances/${props.id}/logs`)).data.items
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    logsLoading.value = false
  }
}

async function saveCfg(name, cfg, keyField) {
  busy.value = true
  try {
    const body = { ...cfg }
    if (keyField) {
      body[keyField] = aiKey.value
      delete body.api_key_masked
    }
    await http.put(`/instances/${props.id}/config/${name}`, body)
    ElMessage.success('已保存，配置即时生效')
    await refreshData(true)
  } catch (e) {
    ElMessage.error(errText(e))
  } finally {
    busy.value = false
  }
}

async function saveKw(row, isNew = false) {
  try {
    if (isNew || !row.id) {
      await http.post(`/instances/${props.id}/keywords`, row)
      kwDialog.value = false
    } else {
      await http.put(`/instances/${props.id}/keywords/${row.id}`, row)
    }
    keywords.value = (await http.get(`/instances/${props.id}/keywords`)).data.items
    ElMessage.success('已保存')
    await refreshData(true)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function delKw(row) {
  await http.delete(`/instances/${props.id}/keywords/${row.id}`)
  keywords.value = keywords.value.filter((k) => k.id !== row.id)
  await refreshData()
}

async function saveSch(row, isNew = false) {
  if (!String(row.target_group_openid || '').trim()) {
    ElMessage.error('请选择目标群：每条定时任务都要指定发到哪个群')
    return
  }
  try {
    if (isNew || !row.id) {
      await http.post(`/instances/${props.id}/schedules`, row)
      schDialog.value = false
    } else {
      await http.put(`/instances/${props.id}/schedules/${row.id}`, row)
    }
    schedules.value = (await http.get(`/instances/${props.id}/schedules`)).data.items
    ElMessage.success('已保存')
    await refreshData(true)
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function delSch(row) {
  await http.delete(`/instances/${props.id}/schedules/${row.id}`)
  schedules.value = schedules.value.filter((s) => s.id !== row.id)
  await refreshData()
}

async function review(row, op) {
  try {
    await http.post(`/instances/${props.id}/join-requests/review`, { request_id: row.id, op })
    ElMessage.success(op === 'approve' ? '已同意' : '已拒绝')
    loadAll()
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

onMounted(() => {
  loadAll()
  timer = setInterval(loadAll, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.page { min-height: 100vh; min-width: 0; }
.header {
  min-height: 56px;
  padding: 8px 16px;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.title { font-weight: 600; margin-left: 12px; }
.el-main { width: 100%; min-width: 0; }
.detail-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.detail-status { flex-shrink: 0; }
.detail-spacer { flex: 1; }
.detail-status-text { max-width: 32vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #909399; font-size: 13px; }
.detail-layout { display: flex; gap: 16px; align-items: flex-start; min-width: 0; }
.detail-layout > .detail-nav-card { width: 170px; flex: 0 0 170px; position: sticky; top: 8px; }
.detail-content { flex: 1; min-width: 0; }
.persona-scope-card { width: 170px; flex: 0 0 170px; }
.menu-preview-card { width: 260px; flex: 0 0 260px; }
.mobile-fluid-380 { width: min(380px, 100%); }
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
.wl-group { font-size: 12px; color: #909399; padding: 10px 12px 2px; }
.nav-card :deep(.el-card__header), .scope-card :deep(.el-card__header) { padding: 10px 12px; font-size: 14px; }
.phone { border: 1px solid #dcdfe6; border-radius: 12px; overflow: hidden; background: #f2f3f5; }
.phone-title { background: #fff; text-align: center; padding: 8px; font-size: 13px; font-weight: 600; border-bottom: 1px solid #eee; }
.phone-body { height: 180px; padding: 10px; display: flex; flex-direction: column; justify-content: flex-start; }
.phone-bubble { background: #409eff; color: #fff; border-radius: 8px; padding: 6px 10px; font-size: 12px; align-self: flex-end; }
.phone-submenu { display: flex; gap: 6px; padding: 0 10px 6px; flex-wrap: wrap; }
.phone-menu-item { background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer; text-align: center; }
.phone-menu-item.sub { color: #409eff; }
.phone-menubar { display: flex; border-top: 1px solid #eee; background: #fff; }
.phone-menubar .phone-menu-item { flex: 1; border: none; border-right: 1px solid #f0f0f0; border-radius: 0; }
.phone-input { display: flex; gap: 6px; align-items: center; background: #fff; padding: 6px 10px 10px; font-size: 14px; }
@media (max-width: 760px) {
  .header { padding: 8px 12px; gap: 7px; }
  .back-button { padding: 0; }
  .detail-title { flex: 1 1 180px; margin-left: 2px; font-size: 13px; }
  .detail-status { margin-left: auto; }
  .detail-spacer { display: none; }
  .detail-status-text { flex: 1 1 100%; max-width: 100%; margin-left: 2px; font-size: 11px; }
  .detail-layout { flex-direction: column; gap: 12px; }
  .detail-layout > .detail-nav-card { position: static; width: 100%; flex: 0 0 auto; }
  .detail-layout > .detail-nav-card :deep(.el-card__header) { display: none; }
  .detail-layout > .detail-nav-card .wl-menu { flex-direction: row; overflow-x: auto; padding-bottom: 4px; width: 100%; max-width: 100%; }
  .detail-layout > .detail-nav-card .wl-item { flex: 0 0 auto; white-space: nowrap; }
  .detail-layout > .detail-nav-card .wl-group { display: none; }
  .detail-content { width: 100%; min-width: 0; }
  .menu-preview-card { width: 100%; max-width: 100%; flex: 1 1 100%; }
  .persona-scope-card { width: 100%; flex: 1 1 100%; }
  .mobile-fluid-380 { width: 100%; max-width: 380px; }
  .detail-content :deep(.el-table) { max-width: 100%; }
  .detail-content :deep(.el-form--inline .el-form-item) { margin-right: 0; }
  .detail-content :deep(.el-dialog) { width: calc(100vw - 24px) !important; max-width: 640px; }
  .detail-content :deep(.el-dialog__body) { max-height: calc(100dvh - 180px); overflow: auto; }
  .detail-content :deep(.el-form-item__label) { line-height: 1.4; }
  .detail-content :deep(.el-form:not(.el-form--label-top) .el-form-item) { display: block; }
  .detail-content :deep(.el-form:not(.el-form--label-top) .el-form-item__label) { display: block; text-align: left; }
  .detail-content :deep(.el-form:not(.el-form--label-top) .el-form-item__content) { margin-left: 0 !important; }
  .detail-content :deep(.el-form-item__content > .el-input),
  .detail-content :deep(.el-form-item__content > .el-select),
  .detail-content :deep(.el-form-item__content > .el-date-editor),
  .detail-content :deep(.el-form-item__content > .el-input-number) { max-width: 100%; }
  .detail-content :deep([style*="width: 380px"]),
  .detail-content :deep([style*="width: 360px"]),
  .detail-content :deep([style*="width: 320px"]) { width: 100% !important; max-width: 100%; }
  .detail-content :deep([style*="min-width: 380px"]) { min-width: 0 !important; }
}
@media (max-width: 480px) {
  .el-main { padding: 14px 12px 28px; }
  .detail-layout > .detail-nav-card :deep(.el-card__body) { padding: 10px; }
  .detail-layout > .detail-nav-card .wl-item { padding: 8px 10px; font-size: 12px; }
  .detail-content :deep(.el-row) { margin-right: -6px !important; margin-left: -6px !important; }
  .detail-content :deep(.el-col) { padding-right: 6px !important; padding-left: 6px !important; }
  .detail-content :deep(.el-card__body) { padding: 13px; }
  .detail-content :deep(.el-descriptions__label),
  .detail-content :deep(.el-descriptions__content) { word-break: break-word; }
  .detail-content :deep(.el-form-item__label) { padding: 0 0 5px; }
  .detail-content :deep(.el-radio-group), .detail-content :deep(.el-checkbox-group) { display: flex; flex-wrap: wrap; }
  .detail-content :deep(.el-form--inline) { display: block; }
  .detail-content :deep(.el-form--inline .el-form-item) { width: 100%; }
  .detail-content :deep(.el-form--inline .el-form-item__content) { width: 100%; }
  .detail-content :deep(.el-form--inline .el-button) { width: 100%; }
  .menu-preview-card :deep(.el-card__body) { overflow-x: auto; }
  .detail-content :deep(.el-table__body-wrapper),
  .detail-content :deep(.el-table__header-wrapper) { max-width: 100%; }
}
</style>
<style>
/* 规则编辑框：开关直接到位，不带滑动动画（切触发类型换动作模板时视觉更平静） */
.rule-dialog .el-switch__core,
.rule-dialog .el-switch__core .el-switch__action {
  transition: none !important;
}
</style>
