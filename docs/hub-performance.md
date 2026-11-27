# 模型站 / 工作流商城性能优化说明

本文记录「搜索慢、下载慢」的定位过程、已落地的改动、实测数据，以及为什么
当前阶段不需要引入 C++ 扩展。

## 1. 原来的瓶颈

优化前，一次搜索大致是：

1. `POST /api/v1/login` 校验令牌；
2. `PUT /api/v1/models/` 查自己的命名空间；
3. `PUT /api/v1/models/` 按标记前缀全站搜索；
4. 有关键词时再查一次；
5. 对每个候选仓库**串行**读取清单（`N` 次 GET）。

问题不只在「请求多」，而在「串行 + 限流」：

* `_AsyncRateLimiter` 在持有 `asyncio.Lock` 的情况下 `sleep`，所有请求被强制
  串行，`MODELSCOPE_QPS = 5` 意味着每个清单至少间隔 200ms；
* 每个请求都 `async with httpx.AsyncClient(...)` 新建客户端，TCP/TLS 握手
  无法复用；
* 清单读取是典型的 N+1：12 个候选就是 12 个 RTT 排队；
* 工作流下载时，缺失的 PyMSS 模型是一个接一个启动、轮询的；
* 模型下载同样每个文件新建客户端，且只有单连接。

实测（本机到 ModelScope，12 个候选仓库）：

| 场景 | 耗时 |
| --- | --- |
| 旧逻辑：串行 + 200ms 限流 | **约 10s**（仅 12 个清单阶段） |
| 新逻辑：8 路有界并发、令牌桶 | **约 1.1 ~ 1.7s** |
| 新逻辑首次完整搜索（含列表查询，网络波动） | **约 2 ~ 5s** |
| 新逻辑 15s 内重复搜索 | **< 10ms**（搜索缓存） |

## 2. 改动一览

### 2.1 共享异步 HTTP 基础设施

新增 `app/infrastructure/http_async.py`：

* **按事件循环复用 `httpx.AsyncClient`**：keep-alive、TLS 会话、连接池复用；
* **无锁令牌桶 `AsyncTokenBucket`**：等待令牌时 `sleep` 不阻塞其它协程，允许
  小突发；遇到 429 全局退避；
* **`TTLCache`**：清单 / 文件列表 / 搜索结果 / 令牌校验短 TTL 缓存；
* **`gather_bounded`**：有界并发，单个候选失败不影响整次搜索；
* **代理环境兼容**：自动清理 `no_proxy` 中的 `[::1]` 写法。httpx 0.28 会把
  它解析成非法端口，导致客户端创建直接失败（Windows 环境常见）。

### 2.2 模型站

新增 `app/infrastructure/model_hub_client.py`，并把 `ModelHubService` 的 HTTP
能力收敛到新端口 `application.ports.ModelHubGateway`：

* 三个搜索来源（令牌校验 / 标记前缀 / 关键词）并发发出；
* 候选清单有界并发读取，默认 8 路；
* 清单、文件列表、搜索结果、令牌校验全部带 TTL 缓存；
* 「检查更新」也改为并发读取清单；
* 大文件下载支持 `Range` 分片并行，并用 `.part.json` 记录已完成分片，
  失败后只补缺失分片；服务端不支持 Range 时自动退回单连接流式。

### 2.3 工作流商城

`app/infrastructure/workflow_hub_client.py` 同步改造：

* 标记搜索、自己的命名空间、关键词搜索并发；
* 候选清单并发读取；
* 自己命名空间超过 100 个仓库时，后续分页并发拉取；
* 搜索 / 清单 / 令牌校验带 TTL 缓存；
* 上传成功后主动失效缓存，避免「刚上传搜不到」。

`app/application/workflow_hub_service.py` 的 PyMSS 依赖同步改为**有界并发**：

* 默认同时下载 3 个缺失模型（每个是独立子进程 / 独立网络连接）；
* 进度按模型大小加权汇总，仍显示「已完成 N/M」；
* 单个模型失败不影响其它模型，最后统一汇总 warnings。

### 2.4 UI 分页

模型站与 PyMSS 模型站统一使用 Element Plus 分页组件（`el-pagination`），
每页可选 12 / 24 / 48：

* 模型站：先拉全本软件候选列表（列表接口有 30s 缓存），再按页切片；
  带关键词 / 框架筛选时会扫描全部候选清单（有 90s 缓存 + 扫描上限），
  保证匹配项即使排在后面也能搜到，并给出精确的筛选后总数；
* PyMSS 模型站：本地目录一次性加载，筛选后在前端分页；
* 搜索词支持「ddsp模型」「RVC 模型」这类框架词 + 通用后缀，也支持
  `sovits` / `ddsp` 等别名；搜索桶包含清单里的架构、类型和标签；
* 本地已安装检测：优先用 `source_repo_id` 快速匹配；来源元数据缺失或指向
  其它仓库时，用本地主模型文件的 SHA-256 与 ModelScope 文件摘要比对，
  结果会缓存到 `modelhub/local-model-hashes.json`，避免每次启动重算；
  删除 / 导入本地模型会主动清空搜索缓存并重新检测，不会残留「查看本地」；
* 工作流商城的本地检测：来源 `repo_id` 缺失时，对工作流图的
  `节点 id/type/params + 连线端口` 做规范化 SHA-256（不含坐标/名称），
  与远端清单图比对；本地图指纹按 `(工作流 id, updated_at)` 缓存，远端按
  `(仓库, 版本)` 缓存。图哈希只处理几十 KB JSON，不会像模型权重那样长时间
  占用 CPU；
* 搜索、框架筛选、PyMSS 分类筛选变化都会回到第 1 页。

### 2.5 配置项

全部集中在 `app/config.py` 的「模型站」段，可按网络环境调整：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `MODELSCOPE_READ_QPS` | 12 | 读取类请求平均 QPS |
| `MODELSCOPE_READ_BURST` | 10 | 令牌桶突发容量 |
| `MODELSCOPE_HTTP_MAX_CONNECTIONS` | 16 | 共享连接池上限 |
| `MODELSCOPE_MANIFEST_CONCURRENCY` | 8 | 清单并发读取数 |
| `MODELSCOPE_SEARCH_SCAN_LIMIT` | 300 | 带筛选搜索时最多扫描的候选仓库数 |
| `MODELSCOPE_MANIFEST_TTL` | 90s | 清单缓存时间 |
| `MODELSCOPE_LIST_TTL` | 30s | 列表接口（分页）缓存时间 |
| `MODELSCOPE_SEARCH_TTL` | 15s | 搜索结果缓存时间 |
| `MODELHUB_DOWNLOAD_CONNECTIONS` | 2 | 大文件分片连接数，设为 1 关闭 |
| `MODELHUB_DOWNLOAD_CHUNK_BYTES` | 4MB | 分片大小 |
| `MODELHUB_DOWNLOAD_PARALLEL_MIN_BYTES` | 16MB | 超过该大小才启用分片 |
| `WORKFLOWHUB_PYMSS_DOWNLOAD_CONCURRENCY` | 3 | PyMSS 依赖并发安装数 |

## 3. 关于 GIL：为什么 asyncio 已经够用

用户提到的 GIL 确实是 Python 并发的核心约束，但本次瓶颈不在 CPU：

* **网络 I/O 会释放 GIL**：socket / SSL 读写期间 GIL 是释放的，单线程事件
  循环可以同时等待几十个连接；并发度受连接池、服务端 QPS 和带宽限制，
  而不是 GIL；
* **磁盘 I/O 也会释放 GIL**：下载落盘使用 `os.write` / `file.write`，阻塞
  发生在系统调用期间；
* **清单解析是微秒级**：模型清单只有几百字节到几十 KB，`json` 的 C 解析器
  足够快；真正的耗时是 RTT；
* 旧代码「慢」的原因是**主动串行化**（持锁 sleep、每请求新建客户端、N+1
  顺序 await），不是 GIL。

因此，本次用「asyncio 并发 + 连接池 + 有界并发 + 短 TTL 缓存」解决网络等待，
用「独立子进程并发」解决 PyMSS 多模型安装，已经绕开了 GIL。

### 什么情况下才需要 C++ / 原生扩展

如果未来出现以下**CPU-bound** 热点，再考虑原生加速：

* 万级仓库清单的本地全文检索 / 打分；
* 大文件 SHA-256 校验成为瓶颈（当前未做逐文件哈希校验）；
* 单机带宽达到 1Gbps 以上，Python 层 HTTP/2 帧解析成为瓶颈。

届时优先选成熟的、发布 GIL 的高性能库，而不是手写 C++ 扩展：

* `orjson`（Rust，JSON 解析，可选依赖）；
* `curl_cffi` / `pycurl`（libcurl multi，原生多连接、GIL 释放）；
* 确有需要再写 C++ 扩展（pybind11），但要承担 MSVC 构建、按 Python 版本
  分发 wheel、崩溃边界等成本。

当前没有引入 C++ 辅助程序：它无法降低服务端 RTT，也不能突破服务端 QPS，
反而会增加打包与崩溃排查成本。

## 4. 下载实测与说明

55MB 模型文件，本机到 ModelScope（已预热共享客户端，排除首次建连开销）：

| 方式 | 耗时 |
| --- | --- |
| 单连接流式 | 2.68s（约 20.6MB/s） |
| 2 连接分片 | 2.82s（约 19.6MB/s） |
| 4 连接分片 | 3.47s（约 15.9MB/s） |

本机带宽/服务端出口约 20MB/s，分片并行没有收益，连接数越多反而略慢。这是
预期内的：**分片并行只在「单连接被限速、但总带宽未满」时有效**。因此：

* 默认用 2 路分片（与单连接基本持平，海外/限速线路能吃到并行收益）；
* 可配置（`MODELHUB_DOWNLOAD_CONNECTIONS=1` 关闭，或调到 4~8 再测）；
* 连接复用、断点续传、多依赖并发的收益是确定的。

> 服务启动时会在后台预热共享 HTTP 客户端（SSL / 代理解析约 0.5~0.8s），
> 正常使用中首次搜索不必再承担这部分开销；若应用刚启动就立刻点击搜索，
> 仍可能和预热重叠。

## 5. 回归测试

```powershell
app\.venv\Scripts\python.exe -m pytest app\tests\test_hub_performance.py -q
app\.venv\Scripts\python.exe -m pytest app\tests\test_architecture.py app\tests\test_workflow_hub.py app\tests\test_model_hub_ecosystem.py -q
```

`test_hub_performance.py` 覆盖：

* 8 个仓库清单并发读取（用延迟 fake 断言总耗时低于串行）；
* 重复搜索命中缓存、不再发请求；
* 3 个 PyMSS 模型并发安装；
* 本机 Range 服务器上的 4 连接分片下载，逐字节比对结果。
