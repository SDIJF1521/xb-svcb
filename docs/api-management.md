# XB-SVCB API 管理与构建资源变更说明

> 0.0.32 中 `5616756` 提交的实现记录；当前使用说明见 [FastAPI 接入文档](api.md)。

## 1. 文档范围

本文档记录域名绑定和多 API Key 管理的实现变更；下文的验证结果仅对应当时的测试，不代表当前版本的发布验收。

## 2. 功能变更摘要

### 2.1 API 服务配置

- API 默认端口由 `8765` 调整为 `8760`。
- 支持选择监听范围：
  - 本机模式：监听 `127.0.0.1`，只允许本机访问；
  - 局域网模式：监听 `0.0.0.0`，允许局域网访问，并允许配置绑定域名。
- 域名绑定仅在局域网模式可用。
- 切换回本机模式时，域名会自动清空，避免出现本机监听却配置了不可用域名的情况。
- 域名会进行规范化和合法性校验。
- Swagger、ReDoc 和 API 状态中的访问地址会优先使用绑定域名。

### 2.2 API Key 管理

- 原来的单 API Key 扩展为多 API Key 管理。
- 每条 Key 支持：
  - 名称；
  - 自动生成；
  - 有效期；
  - 启用/禁用；
  - 编辑；
  - 删除。
- 生成的密钥统一使用前缀：`XB-SVCB-`。
- 保留原有复制按钮，并增加以下交互：
  - 单击密钥文本复制完整密钥；
  - 右侧按钮复制密钥；
  - 显示/隐藏明文按钮。
- 鉴权仅接受已启用且未过期的 Key。
- 至少保留一条 Key，避免误删全部密钥后无法调用 API。
- API 服务运行期间禁止修改、删除或切换 Key 状态，需要先停止服务。
- 旧版本单 Key 配置可以在读取时迁移为默认 Key。

### 2.3 前端布局

- 多个 Key 使用卡片列表展示。
- 页面支持宽屏多列和窄屏单列自适应布局。
- 域名输入框默认宽度接近提示文本，并会根据域名长度自适应，同时设置最大宽度避免撑破布局。
- 本机模式下域名输入框禁用，并显示对应提示。

## 3. 代码修改路径清单

### 3.1 后端

#### `app/api/http_server.py`

主要修改内容：

- 增加默认端口常量 `DEFAULT_HTTP_PORT = 8760`。
- 增加 API Key 前缀常量 `API_KEY_PREFIX = "XB-SVCB-"`。
- 将鉴权逻辑从单 Key 改为多 Key 记录。
- 增加 Key 的启用状态、过期时间、创建时间、唯一 ID 和过期判断。
- 增加 Key 的创建、列表查询、编辑和删除逻辑。
- 增加旧版 `api_key` 配置向 `api_keys` 列表迁移的兼容处理。
- 鉴权时只接受启用且未过期的 Key。
- 增加域名校验、域名规范化和本机模式清空域名逻辑。
- API 服务状态增加域名、域名访问地址和多 Key 信息。
- 修改 Swagger/ReDoc 的默认访问端口和访问地址生成逻辑。
- 保留服务运行期间禁止修改 Key 的保护逻辑。

#### `app/api/bridge.py`

增加桌面端桥接方法，使前端可以调用后端 Key 管理功能：

- `list_http_api_keys`
- `create_http_api_key`
- `update_http_api_key`
- `delete_http_api_key`


### 3.2 前端 API 调用层与数据类型

#### `web/src/api/types.ts`

主要修改内容：

- 增加 `HttpApiKey` 类型。
- 增加 `HttpApiKeyResult` 类型。
- 扩展 `HttpApiStatus`，加入：
  - `domain`
  - `domain_url`
  - `api_keys`
- 扩展 API 服务配置和启动参数，使其支持 `scope`、`port`、`domain`。

#### `web/src/api/index.ts`

主要修改内容：

- 配置 API 服务时传递域名参数。
- 启动 API 服务时传递域名参数。
- 增加以下前端调用方法：
  - `listHttpApiKeys`
  - `createHttpApiKey`
  - `updateHttpApiKey`
  - `deleteHttpApiKey`

#### `web/src/api/mock.ts`

主要修改内容：

- Mock API 默认端口同步改为 `8760`。
- Mock 数据增加域名和域名访问地址。
- Mock 数据增加多 Key 列表。
- Mock 层同步支持 Key 创建、编辑、删除、启用/禁用和过期判断。
- Mock 密钥统一使用 `XB-SVCB-` 前缀，保证前端离线开发时与后端行为一致。

### 3.3 API 页面

#### `web/src/views/api/api.vue`

主要修改内容：

- 服务配置区域增加域名输入和绑定状态提示。
- 本机模式下禁用域名输入；局域网模式下允许填写域名。
- 域名输入框根据内容自适应宽度，并限制最大宽度。
- 新增独立的“API 密钥”区域，位置在服务配置区域下方。
- 支持添加多个 API Key。
- 支持编辑 Key 名称、有效期和启用状态。
- 支持启用/禁用、删除 Key。
- 保留复制按钮，并支持单击密钥文本复制。
- 增加明文显示/隐藏按钮。
- 对长密钥进行省略显示，避免破坏卡片布局。
- 窄屏时 Key 卡片和操作区域自动调整为单列布局。
- 服务运行时根据后端状态禁用不允许的修改操作。

### 3.4 自动生成声明文件

#### `web/src/types/components.d.ts`

构建或前端组件自动导入过程中生成/更新的组件类型声明。该文件不承载 API Key 业务逻辑。

#### `web/src/types/auto-imports.d.ts`

## 4. 提交时的验证记录

已完成以下验证：

### 4.1 后端语法和单元测试

```powershell
$python = (Resolve-Path '.venv-svc\Scripts\python.exe').Path
& $python -m py_compile app/api/http_server.py app/api/bridge.py
& $python -m unittest app.tests.test_http_api -q
```

结果：

```text
Ran 15 tests in 3.269s
OK
```

测试过程中只有 Starlette/httpx 弃用警告，不影响测试通过。

### 4.2 前端类型检查

```powershell
Set-Location web
npm.cmd run type-check
```

结果：通过。

### 4.3 前端生产构建

```powershell
npm.cmd run build
```

结果：通过。

## 5. `test.juzidc.cn:8760` 手工验证步骤

1. 在 API 页面选择“局域网”模式。
2. 输入绑定域名：`test.juzidc.cn`。
3. 端口设置为：`8760`。
4. 保存配置并启动 API 服务。
5. 将 `test.juzidc.cn` 的 DNS A 记录解析到运行 XB-SVCB 的主机。
6. 放行 Windows 防火墙 TCP `8760` 入站规则。
7. 在客户端执行：

```powershell
Resolve-DnsName test.juzidc.cn
Test-NetConnection test.juzidc.cn -Port 8760
```

8. 使用启用且未过期的 Key 调用接口：

```powershell
curl.exe -H "X-API-Key: XB-SVCB-..." http://test.juzidc.cn:8760/api/v1/models
```

9. 检查文档地址：

```text
http://test.juzidc.cn:8760/docs
http://test.juzidc.cn:8760/redoc
```

如果 DNS 已生效但端口不通，需要继续检查 API 服务是否启动、Windows 防火墙、路由器端口映射，以及域名是否解析到正确主机。仅完成代码和本机检查，并不等于已经完成公网域名连通性验证。
