# XB-SVCB 前端

版本：`0.0.15`

这里是 XB-SVCB 桌面应用的 Vue 3 + Vite 前端。生产构建产物会由 `installer/xb-svcb-app.spec` 打进 `XB-SVCB.exe`。

## 开发

```sh
npm install
npm run dev
```

## 构建

```sh
npm run build
```

构建输出目录是 `web/dist`，随后由桌面本体打包流程内置进应用。

## v0.0.15 重点

- 首页数据存储卡片拆分为「选择目录」与「迁移数据」两个动作。
- 数据迁移过程显示进度条、当前阶段和已复制/总大小。
- 前端 API 新增数据目录直接切换、后台迁移启动和迁移状态轮询。
- 桌面后端缺少新版 API 时会给出明确错误，并兼容旧迁移入口。
