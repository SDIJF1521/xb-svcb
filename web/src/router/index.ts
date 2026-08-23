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
          path: 'create/realtime',
          name: 'RealtimeCover',
          component: () => import('@/views/create/realtime.vue'),
        },
        {
          path: 'enhancement',
          name: 'AiEnhancement',
          component: () => import('@/views/enhancement/enhancement.vue'),
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
          path: 'editor/projects',
          name: 'EditorProjects',
          component: () => import('@/views/editor/projects.vue'),
        },
        {
          path: 'editor',
          name: 'Editor',
          component: () => import('@/views/editor/editor.vue'),
        },
        {
          path: 'works',
          name: 'Works',
          component: () => import('@/views/works/works.vue'),
        },
        {
          path: 'player',
          name: 'Player',
          component: () => import('@/views/player/player.vue'),
        },
        {
          path: 'api',
          name: 'ApiAccess',
          component: () => import('@/views/api/api.vue'),
        },
        {
          path: 'plugins',
          name: 'Plugins',
          component: () => import('@/views/plugins/plugins.vue'),
        },
        {
          path: 'plugins/:pluginId/:pageId',
          name: 'PluginPage',
          component: () => import('@/views/plugins/page.vue'),
        },
      ],
    },
  ],
})

export default router
