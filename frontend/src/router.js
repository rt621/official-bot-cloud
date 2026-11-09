import Login from './views/Login.vue'
import Instances from './views/Instances.vue'
import InstanceDetail from './views/InstanceDetail.vue'
import Admin from './views/Admin.vue'

export const routes = [
  { path: '/', redirect: '/instances' },
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/instances', component: Instances },
  { path: '/instances/:id', component: InstanceDetail, props: true },
  { path: '/admin', component: Admin },
]
