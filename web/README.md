# XB-SVCB 前端

版本：`0.0.14`

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

## v0.0.14 重点

- 音频编辑器支持添加/删除音轨，并在导入音频时选择目标音轨。
- 编辑器接入可选人声分离与按歌词切分人声音频。
- 局部重新推理支持对选中片段微调推理参数。
- 多模型/多框架时间轴颜色更容易区分。
