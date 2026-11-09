<template>
  <el-card style="margin-bottom: 16px">
    <template #header>
      <div style="display: flex; align-items: center">
        <b>按群开关</b>
        <span style="flex: 1"></span>
        <span style="color: #909399; font-size: 12px">指定群可单独开启/关闭，未列出的跟随总开关</span>
      </div>
    </template>
    <el-alert v-if="!knownGroups.length" title="还没有已发现的群（机器人进群并收到消息后自动记录）" type="info" :closable="false" style="margin-bottom: 8px" />
    <div v-for="g in knownGroups" :key="g.group_openid"
      class="group-switch-row">
      <span class="group-switch-name" :title="g.group_openid">{{ g.group_name || shortId(g.group_openid) }}</span>
      <el-select :model-value="stateOf(g.group_openid)" size="small" class="group-switch-select"
        @change="(v) => setGroup(g.group_openid, v)">
        <el-option label="跟随总开关" value="inherit" />
        <el-option label="单独开启" value="on" />
        <el-option label="单独关闭" value="off" />
      </el-select>
    </div>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { http, errText } from '../api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  instanceId: { type: String, required: true },
  feature: { type: String, required: true },
  knownGroups: { type: Array, default: () => [] },
})

const rows = ref([]) // [{group_openid, enabled}] 仅本 feature 的覆盖行

function shortId(s) {
  return s && s.length > 16 ? s.slice(0, 8) + '…' + s.slice(-6) : (s || '')
}

function stateOf(gid) {
  const row = rows.value.find((r) => r.group_openid === gid)
  if (!row) return 'inherit'
  return row.enabled ? 'on' : 'off'
}

async function load() {
  try {
    const items = (await http.get(`/instances/${props.instanceId}/feature-groups`)).data.items
    rows.value = items.filter((r) => r.feature === props.feature && r.group_openid !== '*')
  } catch (e) {
    ElMessage.error(errText(e))
  }
}

async function setGroup(gid, v) {
  try {
    if (v === 'inherit') {
      await http.delete(`/instances/${props.instanceId}/feature-groups/${props.feature}/${gid}`)
    } else {
      await http.put(`/instances/${props.instanceId}/feature-groups/${props.feature}/${gid}`, {
        enabled: v === 'on',
      })
    }
    await load()
  } catch (e) {
    ElMessage.error(errText(e))
    await load()
  }
}

onMounted(load)
</script>

<style scoped>
.group-switch-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-bottom: 1px dashed #ebeef5; min-width: 0; }
.group-switch-name { width: 220px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-switch-select { width: 130px; flex-shrink: 0; }
@media (max-width: 480px) {
  .group-switch-row { align-items: stretch; flex-direction: column; gap: 6px; }
  .group-switch-name, .group-switch-select { width: 100%; }
}
</style>
