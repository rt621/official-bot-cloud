import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import { routes } from './router'

const app = createApp(App)
app.use(ElementPlus)

const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach((to) => {
  if (to.meta.public !== true && !localStorage.getItem('token')) {
    return '/login'
  }
})
app.use(router)
app.mount('#app')

