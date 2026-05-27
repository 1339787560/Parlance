## 保存版本内容接口文档

### 接口概述

| 用途 | 地址 |
|------|------|
| 前端（局域网） | http://192.168.46.166:5173/ |
| 后端 API | http://192.168.46.166:8787 |

- **接口名称**：保存版本内容
- **接口说明**：在指定版本下新增或更新该版本的内容。  
  - 若该版本不存在内容 → 创建新记录  
  - 若该版本已存在内容 → 根据更新策略进行更新

---

### 请求说明

- **HTTP 方法**：`POST`
- **URL**：`/api/versions/content`
- **Content-Type**：`application/json`
- （可选）**Authorization**：`Bearer <token>`

#### 请求体（Request Body）

```json
{
  "version": "1.0.0",
  "title": "本版本功能说明",
  "content": "这里是该版本的详细描述内容，可以是 Markdown 或纯文本。",
  "metadata": {
    "author": "张三",
    "tags": ["重要更新", "性能优化"],
    "publishTime": "2026-05-27T08:00:00Z"
  },
  "updateStrategy": "overwrite"
}
```

字段说明：

- **version**（string，必填）：版本号，如 `"1.0.0"`、`"v2.3.1"`。
- **title**（string，必填）：版本内容标题，用于列表展示。
- **content**（string，必填）：该版本的正文内容，建议约定为 Markdown 或纯文本。
- **metadata**（object，可选）：扩展信息，如：
  - `author`（string）：作者/提交人。
  - `tags`（string[]）：标签列表。
  - `publishTime`（string）：发布时间（ISO 8601 格式）。
- **updateStrategy**（string，可选，默认 `"overwrite"`）：
  - `"overwrite"`：整条记录覆盖（title / content / metadata 全部以本次请求为准）。
  - `"merge-metadata"`：title / content 覆盖，metadata 做浅合并（同键以新值为准）。

---

### 业务逻辑说明

1. 根据 `version` 查询该版本内容记录。
2. 若不存在：
   - 创建新记录，写入所有字段。
3. 若已存在：
   - 若 `updateStrategy` 为 `"overwrite"`：整条记录覆盖。
   - 若 `updateStrategy` 为 `"merge-metadata"`：
     - `title`、`content` 直接覆盖；
     - `metadata` 按键做浅合并，已有键以新值为准。
4. 返回保存后的最新记录。

---

### 返回说明

#### 成功响应

- 新增成功：`201 Created`
- 更新成功：`200 OK`

响应体示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "version": "1.0.0",
    "title": "本版本功能说明",
    "content": "这里是该版本的详细描述内容，可以是 Markdown 或纯文本。",
    "metadata": {
      "author": "张三",
      "tags": ["重要更新", "性能优化"],
      "publishTime": "2026-05-27T08:00:00Z"
    },
    "createdAt": "2026-05-27T08:00:00Z",
    "updatedAt": "2026-05-27T08:10:00Z"
  }
}
```

字段说明：

- **code**：业务状态码，`0` 表示成功。
- **message**：描述信息。
- **data**：本次保存后的版本内容完整信息。

---

#### 失败响应示例

1. **参数错误**

   - HTTP 状态码：`400 Bad Request`

   ```json
   {
     "code": 1001,
     "message": "参数校验失败：version 不能为空",
     "data": null
   }
   ```

2. **未认证/无权限**

   - HTTP 状态码：`401 Unauthorized` / `403 Forbidden`

   ```json
   {
     "code": 2001,
     "message": "未授权访问",
     "data": null
   }
   ```

3. **服务端异常**

   - HTTP 状态码：`500 Internal Server Error`

   ```json
   {
     "code": 9000,
     "message": "服务器内部错误，请稍后重试",
     "data": null
   }
   ```

---

### 使用示例（curl）

```bash
curl -X POST "https://your-domain.com/api/versions/content" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "version": "1.0.0",
    "title": "1.0.0 版本说明",
    "content": "1. 修复若干 bug\n2. 提升性能",
    "metadata": {
      "author": "张三",
      "tags": ["release", "稳定版"],
      "publishTime": "2026-05-27T08:00:00Z"
    },
    "updateStrategy": "overwrite"
  }'
```

