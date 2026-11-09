<template>
  <div class="scope-layout">
    <el-card class="sp-card">
      <template #header><b>{{ title }}</b></template>
      <div class="sp-menu">
        <div :class="['sp-item', modelValue === 'global' ? 'active' : '']" @click="$emit('update:modelValue', 'global')">
          全局默认
        </div>
        <div v-for="gid in configuredGids" :key="gid"
          :class="['sp-item', modelValue === gid ? 'active' : '']"
          @click="$emit('update:modelValue', gid)">按群：{{ label(gid) }}</div>
      </div>
      <el-select :model-value="''" filterable allow-create size="small"
        placeholder="选择群：切换或新建" style="width: 100%; margin-top: 10px" @change="onPick">
        <el-option v-for="g in groups" :key="g.group_openid" :label="label(g.group_openid)" :value="g.group_openid" />
      </el-select>
    </el-card>
    <div style="flex: 1; min-width: 0">
      <slot />
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  title: { type: String, default: '设置范围' },
  groups: { type: Array, default: () => [] },        // [{group_openid, group_name}]
  configuredGids: { type: Array, default: () => [] }, // 已有按群配置的群
  modelValue: { type: String, default: 'global' },    // 'global' | group_openid
})
const emit = defineEmits(['update:modelValue', 'pick'])

function shortId(s) {
  return s && s.length > 16 ? s.slice(0, 8) + '…' + s.slice(-6) : (s || '')
}
function label(gid) {
  const g = props.groups.find((x) => x.group_openid === gid)
  return (g && g.group_name) ? g.group_name : shortId(gid)
}
function onPick(gid) {
  if (gid) emit('pick', gid)
}
</script>

<style scoped>
.scope-layout { display: flex; gap: 16px; align-items: flex-start; min-width: 0; }
.sp-card { width: 170px; flex: 0 0 170px; position: sticky; top: 8px; }
.sp-card :deep(.el-card__header) { padding: 10px 12px; font-size: 14px; }
.sp-menu { display: flex; flex-direction: column; gap: 4px; }
.sp-item {
  padding: 9px 12px; border-radius: 6px; cursor: pointer;
  font-size: 14px; color: #303133; transition: background 0.15s;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sp-item:hover { background: #f5f7fa; }
.sp-item.active { background: #ecf5ff; color: #409eff; font-weight: 600; }
@media (max-width: 760px) {
  .scope-layout { flex-direction: column; gap: 12px; }
  .sp-card { width: 100%; flex: 0 0 auto; position: static; }
  .sp-menu { flex-direction: row; overflow-x: auto; padding-bottom: 4px; }
  .sp-item { flex: 0 0 auto; max-width: 220px; }
  .scope-layout > div { width: 100%; }
}
</style>
