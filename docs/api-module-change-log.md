# API 模块修改日志

- 修改日期：2026-08-31
- 修改范围：仅 API 模块、API 模块前端页面、API 相关测试；未修改模型、推理、音乐、编辑器等业务模块。

## 功能变更

### 1. 多 API Key 与独立有效期

- `http_api.api_keys` 现在保存 API Key 数组，每项包含：`id`、`name`、`key`、`enabled`、`expires_at`、`created_at`。
- `expires_at` 使用 UTC ISO 8601 字符串；`null` 表示永久有效。
- 每个 Key 可单独新增、重命名、启用/禁用、修改有效期、重新生成或删除。
- HTTP 请求必须同时满足 Key 正确、已启用且未过期，否则返回 `401`。
- 至少保留一个 Key；服务启动前必须存在至少一个可用 Key。
- 旧版只有 `api_key` 的配置会自动迁移为一个 `api_keys` 项，原 Key 保持不变。
- 为兼容已有调用，桥接层仍支持不传 `key_id` 重新生成第一个 Key。

### 2. 局域网、公网展示地址和域名

- API 监听范围仍只有：本机 `127.0.0.1` 或局域网 `0.0.0.0`。
- 新增公网 IP 设置：输入自定义 IPv4/IPv6 时使用自定义值；留空时自动从公网探测服务获取，失败后回退到本机局域网 IPv4。
- 新增可选绑定域名设置；域名会去除协议、端口和末尾点并进行格式校验。
- `public_ip` 与 `public_domain` **只用于生成外部访问地址**，不会被传给 Uvicorn 作为监听地址，因此不会错误地尝试绑定 `103.85.84.147`。
- 示例配置：
  - 公网 IP：`103.85.84.147`
  - 域名：`test.juzidc.cn`
  - 端口：`8765`（也支持 `8760`、`8761`、`8762`、`8763`）

## 乱码修复

- 修复新增 API 配置界面中文文本因错误编码写入为字面量问号（`?`）的问题；这不是字体或 WebView 缺失导致。
- 使用 UTF-8 恢复 API 页面、API 类型/Mock 和桥接层注释中的中文，并重新构建前端生产资源及 Windows 可执行程序。




## 测试记录

### 自动化测试

已通过：

```text
app\.venv\Scripts\python.exe -m pytest app\tests\test_http_api.py app\tests\test_http_api_keys.py -q
23 passed, 1 warning, 5 subtests passed
```

前端已通过：

```text
npm run type-check
npm run build
```

生产构建输出包含 API 页面资源 `api-*.js` 和 `api-*.css`。

完整测试命令曾执行为：

```text
app\.venv\Scripts\python.exe -m pytest app\tests -q
```

其中 API 相关测试全部通过；完整测试中有 4 个与本次 API 修改无关的环境/既有问题：模型导入测试尝试创建受限的 `D:\XB-SVCB\.xb_svcb`，以及 wheelhouse 测试缺少 `engines/so-vits-svc/requirements_win.txt`。本次未修改这些模块。

### 指定公网参数的验证边界

代码级测试已验证 `103.85.84.147` 和 `test.juzidc.cn` 会被保存、规范化并生成访问地址，同时监听地址仍为 `0.0.0.0`。由于本机公网 IP 无法被外部访问，公网连通性不能仅靠本机代码判定；还必须满足：

1. `test.juzidc.cn` 的 DNS A/AAAA 记录指向 `103.85.84.147`；
2. 路由器或云服务器将 `8765`、`8760`、`8761`、`8762`、`8763` 转发到本机；
3. 上游安全组、Windows 防火墙和运营商网络允许这些端口；
4. API 服务选择 `lan` 范围并监听对应端口。

本机测试不修改路由器、防火墙或系统网络设置，因此不能伪造公网访问成功。

## EXE 构建

使用项目现有 `installer/xb-svcb-app.spec` 重新执行 PyInstaller 构建后，产物应为：

```text
dist\XB-SVCB\XB-SVCB.exe
```

该 EXE 只包含本次源码和前端生产构建结果；API 配置仍在运行时保存到用户设置目录，不会把 API Key 固定写入程序。
