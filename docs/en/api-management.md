[简体中文](../api-management.md) | **English** | [日本語](../ja/api-management.md)

# XB-SVCB API Management and Build Asset Changes

> Implementation record for commit `5616756` in 0.0.32. For current usage, see [FastAPI Integration](api.md).

## Scope

This records the implementation of domain binding and multiple API keys. Validation results refer only to that commit and are not current release acceptance.

## Changes

### API Service Configuration

- Default port changed from `8765` to `8760`.
- Local mode listens on `127.0.0.1`; LAN mode listens on `0.0.0.0` and permits a bound domain.
- Domain binding is available only in LAN mode. Returning to local mode clears the domain.
- Domains are normalized and validated. Swagger, ReDoc, and service status prefer the bound-domain URL.

### API Key Management

- The former single key became a list of named keys.
- Keys support automatic generation, expiration, enabled state, editing, and deletion.
- Generated keys use the `XB-SVCB-` prefix.
- Users may copy through the button or key text and toggle plaintext display.
- Authentication accepts only enabled, unexpired keys. At least one key is retained.
- Keys cannot be changed while the service is running. Legacy single-key settings migrate to a default key.

### Frontend Layout

- Keys appear as responsive cards: multiple columns on wide screens and one column on narrow screens.
- The domain input follows content width up to a maximum and is disabled with guidance in local mode.

## Modified Paths

### Backend

`app/api/http_server.py` added `DEFAULT_HTTP_PORT = 8760`, `API_KEY_PREFIX = "XB-SVCB-"`, multi-key records and CRUD, legacy migration, enabled/expiration checks, domain validation and normalization, domain status URLs, and safeguards against changing keys while running.

`app/api/bridge.py` exposes:

- `list_http_api_keys`
- `create_http_api_key`
- `update_http_api_key`
- `delete_http_api_key`

### Frontend API and Types

`web/src/api/types.ts` added `HttpApiKey` and `HttpApiKeyResult`; `HttpApiStatus` gained `domain`, `domain_url`, and `api_keys`; configuration/start arguments gained `scope`, `port`, and `domain`.

`web/src/api/index.ts` forwards domain settings and exposes `listHttpApiKeys`, `createHttpApiKey`, `updateHttpApiKey`, and `deleteHttpApiKey`.

`web/src/api/mock.ts` mirrors port `8760`, domain URLs, multiple-key CRUD, enabled/expiration behavior, and the `XB-SVCB-` prefix.

### API Page

`web/src/views/api/api.vue` added domain configuration and status, disabled domain input in local mode, responsive width, a separate API key section, create/edit/enable/disable/delete/copy/show controls, long-key truncation, responsive cards, and running-state operation guards.

`web/src/types/components.d.ts` and `web/src/types/auto-imports.d.ts` are generated declarations and contain no API-key business logic.

## Validation Recorded with the Commit

Backend syntax and unit tests:

```powershell
$python = (Resolve-Path '.venv-svc\Scripts\python.exe').Path
& $python -m py_compile app/api/http_server.py app/api/bridge.py
& $python -m unittest app.tests.test_http_api -q
```

Recorded result: `Ran 15 tests in 3.269s`, `OK`; only Starlette/httpx deprecation warnings occurred.

Frontend validation:

```powershell
Set-Location web
npm.cmd run type-check
npm.cmd run build
```

Both commands passed at that time.

## Manual `test.juzidc.cn:8760` Check

1. Select LAN mode, bind `test.juzidc.cn`, set port `8760`, save, and start the API.
2. Point the domain's DNS A record to the XB-SVCB host and allow inbound TCP `8760` in Windows Firewall.
3. Check DNS and connectivity:

```powershell
Resolve-DnsName test.juzidc.cn
Test-NetConnection test.juzidc.cn -Port 8760
```

4. Call an endpoint with an enabled, unexpired key:

```powershell
curl.exe -H "X-API-Key: XB-SVCB-..." http://test.juzidc.cn:8760/api/v1/models
```

5. Check `http://test.juzidc.cn:8760/docs` and `http://test.juzidc.cn:8760/redoc`.

If DNS resolves but the port fails, inspect service state, Windows Firewall, router port forwarding, and the resolved host. Code and local checks do not prove public-domain connectivity.
