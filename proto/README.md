# Protocol Buffers 公共定义

本目录只有一个 `common.proto`,定义跨服务复用的公共消息与枚举

## 目录结构

```bash
proto/
├── common.proto        # 公共消息与枚举定义
├── common.pb.go        # 生成的 Go 代码（包名 commonapis）
└── README.md           # 本说明文件
```

> **包名与导入路径**:生成的 Go 包名是 `commonapis`,但文件就落在 `proto/` 目录下,所以代码里按目录路径导入、用别名指向包名:
> ```go
> commonapis "github.com/HitGameAI/apex-rpc-gateway/proto"
> ```
> `common.proto` 的 `go_package` 与实际导入路径一致，通过 `;commonapis` 显式保留 Go 包名。修改模块路径时应先更新 `.proto` 再重新生成，直接替换 `.pb.go` 中的描述符字符串会破坏 protobuf 的长度编码，导致导入包时 panic。

## 公共消息定义 (common.proto)

### StatusCode - 公共状态码枚举

```protobuf
enum StatusCode {
  OK = 0;
  Canceled = 1;
  Unknown = 2;
  InvalidArgument = 3;
  DeadlineExceeded = 4;
  NotFound = 5;
  AlreadyExists = 6;
  PermissionDenied = 7;
  ResourceExhausted = 8;
  FailedPrecondition = 9;
  Aborted = 10;
  OutOfRange = 11;
  Unimplemented = 12;
  Internal = 13;
  Unavailable = 14;
  DataLoss = 15;
  Unauthenticated = 16;
  reserved 17 to 100;

  // 通用系统错误
  SYSTEM_UNKNOWN_ERROR = 101;
  SYSTEM_NETWORK_ERROR = 102;
  SYSTEM_STORAGE_ERROR = 103;
  reserved 104 to 200;
}
```

### Result - 通用处理结果

通常在 Batch 类请求中返回每个子请求的错误状态。

```protobuf
message Result {
  int32 code = 1;           // 通用服务/系统错误码
  string error = 2;          // 错误详细描述
  StatusCode status = 3;     // 业务错误码
}
```

### Paging - 通用翻页结构

```protobuf
message Paging {
  int32 page = 1;     // 页码，可选，默认值为 1
  int32 size = 2;      // 数量，取值范围 [1,100]
  int32 total = 3;     // 总数，请求无须填写，响应由系统填写
}
```

### Sorting - 通用排序结构

```protobuf
message Sorting {
  string field = 1;     // 排序字段，由对应接口解析
  bool reversed = 2;     // 可选，是否倒序
}
```

### TimeRange - 时间区间

表示一段时间区间 `[start, end)`，时间戳为 UTC 时间，JSON 表示形式为 RFC 3339 格式。

```protobuf
message TimeRange {
  google.protobuf.Timestamp start = 1;   // 开始时间，区间包含
  google.protobuf.Timestamp end = 2;     // 结束时间，区间不包含
}
```

> `TimeRange` 依赖 `import "google/protobuf/timestamp.proto";`。

## 生成代码

一条命令,在**仓库根目录**执行:

```bash
protoc -I. --go_out=. --go_opt=paths=source_relative proto/common.proto
```

也可以在仓库根目录运行 `go generate ./proto`。本次生成使用 protoc 24.3 和 protoc-gen-go v1.36.11。

四点说明:

| 点 | 说明 |
|---|---|
| `-I.` 是必须的 | 从仓库根执行,`proto/common.proto` 这个相对路径才解析得到 |
| `paths=source_relative` 是必须的 | 它让产物落在 `.proto` 旁边(即 `proto/common.pb.go`),而不是按完整导入路径创建目录 |
| **只需要 `protoc-gen-go` 一个插件** | `common.proto` 里**没有 `service`**,所以不生成 `*_grpc.pb.go`;没有 `google.api.http` 注解,所以不生成 `*.gw.go` 与 swagger;没有 `@inject_tag` 注释,所以不需要 `protoc-go-inject-tag` |
| 重新生成会改动版本注释 | 产物头部记录的是**本机**的 protoc 与插件版本,与提交时的版本不同就会产生 4 行 diff,这是正常的,不是生成出错 |

安装插件:

```bash
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11
```

`protoc` 本体按平台装(macOS `brew install protobuf`,或从 protobuf releases 下载),并确保 `$GOPATH/bin` 在 `PATH` 里,否则 `protoc` 找不到 `protoc-gen-go`

## 改动 common.proto 之后

1. 跑上面那条命令
2. `go test ./proto ./errors ./response` 验证包初始化、描述符和序列化；仅编译不能发现初始化 panic
3. `git diff proto/common.pb.go` 检查产物变化与 proto 改动一致

> 字段编号一旦发布就不要改动或复用——这是跨服务共享的契约,改编号会让旧客户端静默解析错位

