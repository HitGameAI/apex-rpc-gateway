package commonapis

// 使用 protoc 24.3 和 protoc-gen-go v1.36.11，从 .proto 重新生成描述符。
//go:generate protoc --proto_path=.. --go_out=.. --go_opt=paths=source_relative proto/common.proto
