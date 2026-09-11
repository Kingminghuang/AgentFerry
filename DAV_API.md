# Nutstore WebDAV API

本文档描述 `/Users/huangqingming/Workspace/nutstore/nutstore-server-dev/server/nutstore/fe/src/nutstore/fe/dav` 下的标准 DAV 接口，**不包含 `NsDav*` 和 `NSDav*` 扩展接口**。

接口路由由 `AppServerRequestResolver` 注册，DAV 资源路径以 `/dav/` 开头；`/` 仅对 `OPTIONS` 和 `PROPFIND` 提供兼容性入口。

## 1. 基本约定

### 1.1 服务地址和资源路径

以下文档使用占位符表示服务地址：

```text
<DAV_BASE_URL>  = WebDAV 服务的 scheme、域名和端口，例如 https://dav.example.com
<sandbox>       = 网盘/同步盘名称。名称中包含特殊字符时必须进行 URL 编码
<path>          = sandbox 内的文件或目录路径，目录分隔符为 /
```

资源路径的映射关系如下：

| URI | 含义 | 备注 |
| --- | --- | --- |
| `/` | 服务根视图 | 只用于 `OPTIONS`、`PROPFIND`；`PROPFIND` 将其视为只读虚拟资源 |
| `/dav/` | sandbox 列表视图 | `PROPFIND` 可读取；`OPTIONS` 可查询能力 |
| `/dav/<sandbox>` 或 `/dav/<sandbox>/` | sandbox 根目录 | 在 `PROPFIND` 中返回 sandbox 根资源 |
| `/dav/<sandbox>/<path>` | sandbox 内的文件或目录 | 读写操作的主要资源路径 |

建议对目录使用带末尾 `/` 的规范 URI；服务端解析资源时会去掉最后一个 `/`，但部分方法会据此判断资源是否为集合。

返回的 `href` 会进行路径转义。客户端构造请求时也应对 sandbox 名称和文件名进行 URL 编码，但不要编码路径分隔符 `/`。

### 1.2 认证

所有标准 DAV 请求都需要 HTTP Basic Authentication：

```http
Authorization: Basic <base64(username:application-specific-password)>
```

其中：

- `username` 是用户账号；
- password 必须是用户的应用专用密码（Application Specific Password，ASP），不是普通登录密码；
- 标准 DAV 接口要求用户类型为普通用户，团队管理员/团队专用凭据不用于这些接口。

认证失败时返回 `401 Unauthorized`，并带有：

```http
WWW-Authenticate: Basic realm="nutstore"
```

### 1.3 公共请求头

| Header | 适用接口 | 说明 |
| --- | --- | --- |
| `Authorization` | 全部 | 必填，见认证说明 |
| `Depth` | `PROPFIND`、`COPY` | 可取 `0`、`1` 或 `infinity`；非法值返回 `400` |
| `Destination` | `COPY`、`MOVE` | 必填，值可以是绝对 URI 或包含资源路径的 URI；目标不能是 sandbox 根目录 |
| `If-Match` | `PUT` | 如果提供，必须与当前文件 ETag 完全一致 |
| `If-None-Match` | `GET`、`HEAD` | 与当前文件 ETag 完全一致时返回 `304` |
| `Range` | `GET` | 支持单个字节范围，例如 `bytes=0-99` |
| `If-Range` | `GET` | 存在且不等于当前 ETag 时忽略 `Range`，返回完整文件 |
| `If` | `LOCK` 刷新 | 用于提取 `opaquelocktoken:` 格式的锁令牌 |
| `Lock-Token` | `UNLOCK` | 标准客户端通常会发送；当前实现不读取或校验该 Header |

`Overwrite` 虽然属于 WebDAV 常见请求头，当前 `COPY` 和 `MOVE` 实现不会读取它；目标已存在时不要依赖该 Header 改变覆盖行为。

### 1.4 公共响应和错误

XML 响应的 Content-Type 为：

```http
Content-Type: text/xml; charset=UTF-8
```

非认证类业务错误通常返回 XML：

```xml
<d:error xmlns:d="DAV:" xmlns:s="http://ns.jianguoyun.com">
  <s:exception>ObjectNotFound</s:exception>
  <s:message>The resource of this location does not exist</s:message>
</d:error>
```

常见错误码及 HTTP 状态如下。具体 message 以服务端实际返回为准。

| HTTP 状态 | `exception` 示例 | 常见场景 |
| --- | --- | --- |
| `400 Bad Request` | `IllegalArgument`、`TooBigEntity`、`TooManyASPs` | 参数、XML、请求体或请求头非法 |
| `401 Unauthorized` | `AuthenticationFailed`、`UnAuthorized`、`NoSuchUser` | Basic/ASP 认证失败；认证类错误一般没有 DAV XML 错误体 |
| `403 Forbidden` | `OperationNotAllowed`、`SandboxAccessDenied`、`StorageSpaceExhausted` | 权限不足、操作不适用、空间不足 |
| `404 Not Found` | `ObjectNotFound` | sandbox、文件或目录不存在 |
| `405 Method Not Allowed` | `ResourceExisted` | 创建目录时目标已存在等 |
| `409 Conflict` | `AncestorsNotFound`、`DuplicateName`、`FileBeingLocked`、`ConcurrentUpdate` | 父目录不存在、目标重名、锁冲突或并发更新 |
| `412 Precondition Failed` | `PreconditionFailed`、`FileUnlocked` | ETag 前置条件或锁状态不满足 |
| `416 Requested Range Not Satisfiable` | `RangeNotSatisfied` | Range 超出文件范围 |
| `503 Service Unavailable` | `ServiceUnAvailable`、`BlockedTemporarily` | 服务不可用或请求频率受限 |

## 2. 接口总览

| 方法 | URI | 默认成功状态 | 请求体 | 实现类 |
| --- | --- | --- | --- | --- |
| `OPTIONS` | `/`、`/dav/<...>` | `200 OK` | 无 | [`DavOptionsRequestHandler`](core/DavOptionsRequestHandler.java) |
| `PROPFIND` | `/`、`/dav/<...>` | `207 Multi-Status` | 可选 XML | [`DavPropFindRequestHandler`](core/DavPropFindRequestHandler.java) |
| `PROPPATCH` | `/dav/<...>` | `207 Multi-Status` | 忽略 | [`DavPropPatchRequestHandler`](core/DavPropPatchRequestHandler.java) |
| `MKCOL` | `/dav/<...>` | `201 Created` | 忽略 | [`DavMkColRequestHandler`](core/DavMkColRequestHandler.java) |
| `PUT` | `/dav/<sandbox>/<path>` | `201` 或 `204` | 文件二进制内容 | [`DavPutRequestHandler`](core/DavPutRequestHandler.java) |
| `GET` | `/dav/<sandbox>/<path>` | `200`、`206` 或 `304` | 无 | [`DavGetRequestHandler`](core/DavGetRequestHandler.java) |
| `HEAD` | `/dav/<sandbox>/<path>` | `200` 或 `304` | 无 | [`DavHeadRequestHandler`](core/DavHeadRequestHandler.java) |
| `DELETE` | `/dav/<sandbox>/<path>` | `204 No Content` | 无 | [`DavDeleteRequestHandler`](core/DavDeleteRequestHandler.java) |
| `COPY` | `/dav/<sandbox>/<path>` | `201 Created` | 无 | [`DavCopyRequestHandler`](core/DavCopyRequestHandler.java) |
| `MOVE` | `/dav/<sandbox>/<path>` | `201 Created` | 无 | [`DavMoveRequestHandler`](core/DavMoveRequestHandler.java) |
| `LOCK` | `/dav/<sandbox>/<file>` | `200 OK` | 新建锁时 XML；刷新时为空 | [`DavLockRequestHandler`](core/DavLockRequestHandler.java) |
| `UNLOCK` | `/dav/<sandbox>/<file>` | `204 No Content` | 无 | [`DavUnlockRequestHandler`](core/DavUnlockRequestHandler.java) |

### 2.1 `OPTIONS` 的 Allow 差异

`OPTIONS` 响应中的 `Allow` 是代码中固定的字符串：

```http
DAV: 2
Allow: DELETE, GET, LOCK, UNLOCK, MKCOL, MOVE, OPTIONS, PROPFIND, PUT, COPY
MS-Author-Via: DAV
```

当前路由实际上也注册了 `HEAD` 和 `PROPPATCH`，但它们没有出现在上述 `Allow` 值中。客户端如需使用这两个方法，应以实际路由为准，而不是仅依据 `Allow` 判断。

## 3. 接口详情

### 3.1 OPTIONS

查询服务器 WebDAV 能力。

#### 请求

```http
OPTIONS <DAV_BASE_URL>/dav/Work/ HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

也支持：

```http
OPTIONS <DAV_BASE_URL>/ HTTP/1.1
```

#### 成功响应

```http
HTTP/1.1 200 OK
DAV: 2
Allow: DELETE, GET, LOCK, UNLOCK, MKCOL, MOVE, OPTIONS, PROPFIND, PUT, COPY
MS-Author-Via: DAV
```

响应不包含业务数据体。

### 3.2 PROPFIND

读取服务根视图、sandbox 列表、文件或目录属性。响应为 `207 Multi-Status`。

#### 请求 URI

```text
PROPFIND <DAV_BASE_URL>/
PROPFIND <DAV_BASE_URL>/dav/
PROPFIND <DAV_BASE_URL>/dav/<sandbox>/
PROPFIND <DAV_BASE_URL>/dav/<sandbox>/<path>
```

#### 请求头

| Header | 默认值 | 说明 |
| --- | --- | --- |
| `Depth` | `infinity` | `0` 只返回目标；`1` 返回目标及其直接子项；`infinity` 在当前实现中对目录仍按直接子项列表读取 |
| `Authorization` | 无 | 必填 |

当目录列表被截断时，可使用查询参数 `mk` 继续读取。服务端会在响应中返回：

```http
Link: <<DAV_BASE_URL>/dav/Work/docs?mk=<marker>>; rel="next"
```

客户端应直接请求 `Link` 中的下一页 URI，并保留原来的 `Depth` 和属性请求体。

#### 请求体

不带请求体时，服务端按默认属性集合处理。也可以显式请求全部属性：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:allprop/>
</d:propfind>
```

只请求指定属性：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <d:getcontentlength/>
    <d:getcontenttype/>
    <d:getetag/>
    <d:getlastmodified/>
    <d:current-user-privilege-set/>
  </d:prop>
</d:propfind>
```

请求体由服务端按 XML 文本读取，大小上限为 32 KiB；超过限制或 XML 无法解析时返回 `400`。

服务端按 XML 元素的 local name 识别属性；未知或当前实现不支持的属性不会生成属性值。如果最终没有生成任何属性，该 `propstat` 的状态为 `404 Not Found`。

#### 默认属性

当前实现的默认属性集合为：

| 属性 | 文件 | 目录/集合 | 说明 |
| --- | --- | --- | --- |
| `displayname` | 文件名 | sandbox 或目录名 | 显示名称 |
| `resourcetype` | 空的默认资源类型 | `<collection/>` | 集合标识 |
| `getcontentlength` | 文件大小（字节） | `0`（虚拟/集合资源） | 字符串形式 |
| `getlastmodified` | 文件修改时间 | 目录元数据时间；虚拟资源使用当前时间 | RFC 1123 格式，例如 `Wed, 01 Jan 2025 00:00:00 GMT` |
| `owner` | sandbox owner | sandbox owner | 当前实现返回文本值 |
| `current-user-privilege-set` | 当前用户权限 | 当前用户权限 | 见下表 |
| `getcontenttype` | 根据文件名扩展名推断 | `httpd/unix-directory` | 目录固定值 |
| `getetag` | 当前实现会随 `resourcetype/getcontenttype` 一并输出 | 通常为空元素 | 文件 ETag 来自对象元数据 |

权限到 DAV privilege 的映射：

| Nutstore 权限 | 返回 privilege |
| --- | --- |
| 读 | `read` |
| 写 | `write` |
| 管理 | `read`、`write`、`all`、`read_acl`、`write_acl` |

#### 响应示例

```http
HTTP/1.1 207 Multi-Status
Content-Type: text/xml; charset=UTF-8
```

```xml
<d:multistatus xmlns:d="DAV:" xmlns:s="http://ns.jianguoyun.com">
  <d:response>
    <d:href>/dav/Work/notes/readme.txt</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>readme.txt</d:displayname>
        <d:resourcetype/>
        <d:getcontentlength>1024</d:getcontentlength>
        <d:getcontenttype>text/plain</d:getcontenttype>
        <d:getetag>"..."</d:getetag>
        <d:getlastmodified>Wed, 01 Jan 2025 00:00:00 GMT</d:getlastmodified>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
```

根视图的特殊行为：

- `PROPFIND /` 总是返回 `/`；当 `Depth > 0` 时还返回 `/dav/`；
- `PROPFIND /dav/` 返回 `/dav/` 和可访问的 sandbox 根资源；
- `PROPFIND /dav/<sandbox>/` 返回 sandbox 根资源，并按 `Depth` 返回子项；
- 只有当前用户可访问的对象会出现在列表中。

### 3.3 PROPPATCH

用于兼容部分 WebDAV 客户端的属性更新请求。

#### 请求

```http
PROPPATCH <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Content-Type: application/xml
```

请求体可以为空，也可以是客户端标准的 PROPPATCH XML；当前实现不会解析、保存或更新请求体中的属性。

#### 成功响应

```http
HTTP/1.1 207 Multi-Status
Content-Type: text/xml; charset=UTF-8
```

响应返回一个伪造的成功 `propstat`，属性名为：

- `Win32CreationTime`
- `Win32LastAccessTime`
- `Win32LastModifiedTime`
- `Win32FileAttributes`

这些属性的值为空，状态为 `HTTP/1.1 200 OK`。集合 URI（带末尾 `/`）不允许执行该操作，返回 `403`。

### 3.4 MKCOL

创建目录；当前实现还支持通过该方法创建一个新的 sandbox。

#### 创建 sandbox

当目标 URI 的第一段名称不是现有 sandbox 且没有后续路径时，服务端将其作为新 sandbox 标题：

```http
MKCOL <DAV_BASE_URL>/dav/New%20Work HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

该 sandbox 使用默认访问控制，不通知客户端同步；不能直接创建 photo bucket。

#### 创建目录

```http
MKCOL <DAV_BASE_URL>/dav/Work/projects/2025/ HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

要求父目录已经存在，且用户拥有读写权限。

#### 响应

成功：

```http
HTTP/1.1 201 Created
```

主要错误：

- 父级路径不存在：`409 Conflict`，错误码 `AncestorsNotFound`；
- 目标已有文件或目录：通常为 `405 Method Not Allowed`，错误码 `ResourceExisted`；
- 目标 sandbox 已存在时，当前实现不会按标准语义报重复资源，可能直接返回 `201`；客户端不要依赖该边界行为。

### 3.5 PUT

上传或覆盖文件。目标必须是文件路径，不能以集合形式访问。

#### 请求

```http
PUT <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Content-Length: 13
Content-Type: text/plain

Hello Nutstore
```

约束：

- `Content-Length` 必须存在，且不能超过服务端 `webUploadMaxSize` 配置；使用 chunked body 或缺失长度会失败；
- 父目录必须存在；
- 需要目标 sandbox 的写权限，sandbox 服务状态必须为在线；
- 如果目标已存在，写入会覆盖当前文件；不能用 PUT 将集合覆盖为文件；
- 可通过 `If-Match` 进行精确 ETag 校验。ETag 不匹配返回 `412 Precondition Failed`。

#### 响应

首次创建文件：

```http
HTTP/1.1 201 Created
X-File-Version: 1
```

覆盖已有文件：

```http
HTTP/1.1 204 No Content
X-File-Version: <new-version>
```

请求体只作为文件内容处理；服务端会按文件名扩展名推断后续下载时的 MIME 类型。

### 3.6 GET

下载文件内容。不能下载目录或 sandbox 根资源。

#### 基本请求

```http
GET <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

成功响应包含：

```http
HTTP/1.1 200 OK
Etag: <etag>
Cache-Control: max-age=5
Pragma: public
Content-Disposition: attachment
Content-Type: text/plain
```

实际 `Content-Type` 根据文件名推断，响应体为文件二进制内容。空文件返回 `200` 和空响应体。

#### 条件请求

当 `If-None-Match` 的值与服务端 ETag 完全一致时：

```http
HTTP/1.1 304 Not Modified
Etag: <etag>
```

当前实现按字符串精确比较 ETag，不处理弱校验、通配符或多值列表。

#### 分段下载

```http
GET <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Range: bytes=0-99
If-Range: <etag>
```

有效范围返回：

```http
HTTP/1.1 206 Partial Content
Content-Range: bytes 0-99/<file-size>
```

代码稳定支持 `bytes=start-end` 和 `bytes=start-`。`bytes=-N` 虽可被解析，但当前实现会按从文件起始位置开始的范围处理，并非 RFC 语义中的“最后 N 个字节”，客户端不应依赖该形式。范围无效或超出文件大小时返回 `416 Range Not Satisfiable`；`If-Range` 不匹配时忽略 `Range` 并返回完整文件 `200`。

### 3.7 HEAD

读取资源元数据但不返回响应体。

```http
HEAD <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

文件成功响应：

```http
HTTP/1.1 200 OK
Last-Modified: Wed, 01 Jan 2025 00:00:00 GMT
Etag: <etag>
```

说明：

- 文件和目录都可以读取元数据，但集合 URI 不能带末尾 `/`，否则返回 `403`；
- `Last-Modified` 总会返回；如果对象没有显式修改时间，则使用对象时间戳；
- 只有文件返回 ETag；
- `If-None-Match` 精确匹配时返回 `304`，不返回响应体。

### 3.8 DELETE

删除文件或目录。目录删除是递归删除。

```http
DELETE <DAV_BASE_URL>/dav/Work/archive/old.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
```

成功响应：

```http
HTTP/1.1 204 No Content
```

要求用户拥有目标路径的读写权限，sandbox 服务状态必须在线。sandbox 根目录本身不能作为删除目标。

### 3.9 COPY

复制文件或目录，可跨 sandbox 复制。

#### 请求

```http
COPY <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Destination: <DAV_BASE_URL>/dav/Backup/readme.txt
Depth: infinity
```

参数和行为：

- `Destination` 必填；目标解析后不能是 sandbox 根目录；
- `Depth` 默认 `infinity`；
- 对目录使用 `Depth: 0` 时，仅创建目标空目录；
- 对文件使用 `Depth: 0` 仍执行文件复制；
- 不能将目录复制到自身或其子目录；
- 源 sandbox 需要读权限，目标 sandbox 需要写权限；源服务状态至少为只读，目标服务状态必须在线；
- 当前实现不会处理 `Overwrite`。目标已存在时，通常返回 `409 Conflict` 和 `DuplicateName`；
- 复制任务在服务端通过后台任务执行，当前请求会等待任务状态，内部等待上限约为 35 秒；
- 成功响应固定为 `201 Created`，不返回任务 ID。

#### 响应

```http
HTTP/1.1 201 Created
```

### 3.10 MOVE

移动文件或目录，也用于同一目录下的重命名。

#### 请求

```http
MOVE <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Destination: <DAV_BASE_URL>/dav/Work/notes/README.txt
```

行为：

- `Destination` 必填，目标不能是 sandbox 根目录；
- 同一 sandbox 且源和目标父目录相同时，执行原子语义的重命名路径；
- 其他情况通过复制源对象并删除源对象实现移动，可跨 sandbox；
- 不能移动到自身或自己的子目录；
- 不读取 `Depth`，也不读取 `Overwrite`；
- 源需要读写权限，目标需要写权限，涉及的 sandbox 服务状态必须在线；
- 目标已存在、对象被锁定或发生并发更新时可能分别返回 `409` 等错误；
- 成功响应固定为 `201 Created`。

#### 响应

```http
HTTP/1.1 201 Created
```

### 3.11 LOCK

对文件创建或刷新写锁。集合资源不能加锁。

#### 创建锁

请求体必须是 DAV `lockinfo` XML；请求体为空时会被解释为刷新锁。
锁请求 XML 的大小上限为 16 KiB。

```http
LOCK <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Content-Type: application/xml
Content-Length: <length>

<?xml version="1.0" encoding="UTF-8"?>
<d:lockinfo xmlns:d="DAV:">
  <d:lockscope><d:exclusive/></d:lockscope>
  <d:locktype><d:write/></d:locktype>
  <d:owner><d:href>client@example.com</d:href></d:owner>
</d:lockinfo>
```

成功响应：

```http
HTTP/1.1 200 OK
Lock-Token: opaquelocktoken:<uuid>
Content-Type: text/xml; charset=UTF-8
```

响应体为 `d:prop/d:lockdiscovery/d:activelock`，当前实现固定返回：

- `locktype`: `write`；
- `lockscope`: `exclusive`；
- `depth`: `infinity`；
- `timeout`: `Infinite` 对应的长期锁语义；
- `locktoken`: `opaquelocktoken:<uuid>`；响应 Header 中直接返回该字符串，当前实现不额外包裹尖括号；
- `owner`: 如果请求中的 `owner` 包含 `d:href`，返回其文本；
- `lockroot`: 当前实现通常不返回值。

请求中的 lock type、lock scope、`Depth` 和 `Timeout` 不用于改变上述固定返回值。对不存在的文件加锁时，当前实现会返回一个伪造的成功锁信息，但不会创建文件。

#### 刷新锁

刷新请求使用空请求体，并在 `If` Header 中携带锁令牌：

```http
LOCK <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
If: (<opaquelocktoken:<uuid>>)
Content-Length: 0
```

成功刷新返回 `200 OK` 和锁发现 XML，但**不会返回 `Lock-Token` Header**。只有当前用户仍持有该文件锁时刷新才成功；否则返回 `412 FileUnlocked` 等错误。

### 3.12 UNLOCK

解除当前用户在目标文件上的锁。

```http
UNLOCK <DAV_BASE_URL>/dav/Work/notes/readme.txt HTTP/1.1
Host: dav.example.com
Authorization: Basic <base64(username:application-specific-password)>
Lock-Token: <opaquelocktoken:<uuid>>
```

成功响应：

```http
HTTP/1.1 204 No Content
```

实现注意：当前 handler 不读取也不校验 `Lock-Token`，实际控制条件是认证用户、目标路径和底层对象锁状态。对不存在的对象，部分场景会兼容性地返回 `204`，而不是报错。

## 4. XML 数据结构

### 4.1 Multi-Status

`PROPFIND` 和 `PROPPATCH` 使用如下结构：

```xml
<d:multistatus xmlns:d="DAV:" xmlns:s="http://ns.jianguoyun.com">
  <d:response>
    <d:href>/dav/Work/notes/readme.txt</d:href>
    <d:propstat>
      <d:prop>
        <!-- 属性集合 -->
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>
```

同一 `multistatus` 中每个 `response` 对应一个资源；目录查询的子资源会分别生成 `response`。

### 4.2 锁发现

`LOCK` 响应的主体结构如下：

```xml
<d:prop xmlns:d="DAV:">
  <d:lockdiscovery>
    <d:activelock>
      <d:locktype><d:write/></d:locktype>
      <d:lockscope><d:exclusive/></d:lockscope>
      <d:depth>infinity</d:depth>
      <d:owner>client@example.com</d:owner>
      <d:timeout>Infinite</d:timeout>
      <d:locktoken>
        <d:href>opaquelocktoken:<uuid></d:href>
      </d:locktoken>
    </d:activelock>
  </d:lockdiscovery>
</d:prop>
```

## 5. 客户端调用示例

下面示例使用环境变量保存认证信息，避免把 ASP 直接写入 shell 历史：

```bash
export DAV_BASE_URL="https://dav.example.com"
export DAV_USER="user@example.com"
export DAV_ASP="application-specific-password"
```

查询目录：

```bash
curl --user "$DAV_USER:$DAV_ASP" \
  -X PROPFIND "$DAV_BASE_URL/dav/Work/notes/" \
  -H 'Depth: 1' \
  -H 'Content-Type: application/xml' \
  --data '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:allprop/></d:propfind>'
```

上传文件：

```bash
curl --user "$DAV_USER:$DAV_ASP" \
  -T ./readme.txt \
  "$DAV_BASE_URL/dav/Work/notes/readme.txt"
```

下载文件：

```bash
curl --user "$DAV_USER:$DAV_ASP" \
  -o ./readme.txt \
  "$DAV_BASE_URL/dav/Work/notes/readme.txt"
```

复制和移动：

```bash
curl --user "$DAV_USER:$DAV_ASP" \
  -X COPY "$DAV_BASE_URL/dav/Work/notes/readme.txt" \
  -H "Destination: $DAV_BASE_URL/dav/Backup/readme.txt" \
  -H 'Depth: 0'

curl --user "$DAV_USER:$DAV_ASP" \
  -X MOVE "$DAV_BASE_URL/dav/Work/notes/readme.txt" \
  -H "Destination: $DAV_BASE_URL/dav/Work/notes/README.txt"
```

## 6. 实现范围说明

- 本文档基于当前源码中的路由注册和 handler 行为；它描述的是当前实现，不等同于完整 RFC 4918 能力声明。
- `NsDav*`、`NSDav*` 自定义接口未纳入本文档。
- `HEAD`、`PROPPATCH` 已注册并可调用，但当前 `OPTIONS` 的 `Allow` Header 未列出它们。
- `PROPPATCH` 不会持久化属性；`LOCK` 的锁类型/范围/超时时间是固定实现；`UNLOCK` 当前不校验 `Lock-Token`。
