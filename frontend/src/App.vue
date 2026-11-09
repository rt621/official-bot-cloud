<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<style>
*, *::before, *::after { box-sizing: border-box; }
html, body, #app { min-height: 100%; }
body {
  margin: 0;
  background: #f5f7fa;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
</style>
