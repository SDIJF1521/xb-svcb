import { createRouter, createWebHashHistory } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

// 桌面端（pywebview）通过本地文件/内置 http server 加载，使用 hash 模式可避免
// 路径不为 "/" 时无法匹配路由导致的白屏问题。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      component: DefaultLayout,
      children: [
        {
          path: '',
          name: 'Index',
          component: () => import('@/views/index/index.vue'),
        },
        {
          path: 'create',
          name: 'Create',
          component: () => import('@/views/create/create.vue'),
        },
        {
          path: 'models',
          name: 'Models',
          component: () => import('@/views/models/models.vue'),
        },
        {
          path: 'music',
          name: 'Music',
          component: () => import('@/views/music/music.vue'),
        },
        {
          path: 'works',
          name: 'Works',
          component: () => import('@/views/works/works.vue'),
        },
      ],
    },
  ],
})

export default router
