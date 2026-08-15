# 第一个 SDK 插件

这个示例同时展示两部分 TypeScript：`src/plugin.ts` 生成插件清单，`frontend/src/App.vue` 和 `components/CoverForm.vue` 自定义页面布局与组件。组件通过 `@xb-svcb/plugin-sdk/vue` 调用宿主动作，Vite 会把 Vue runtime、组件和 CSS 构建成 `dist/frontend/index.html` 单文件入口。

```powershell
cd plugin-sdk\examples\hello-plugin
npm install
npm run dev
npm run typecheck
npm run validate
npm run pack
```

`npm run dev` 只预览布局；真实宿主动作需要安装插件后测试。`npm run pack` 生成的 `.xbplugin` 可以在 XB-SVCB 的“插件中心”安装。
