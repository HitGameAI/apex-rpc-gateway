package commonapis_test

import (
	"bytes"
	"testing"
	"time"

	commonapis "github.com/HitGameAI/apex-rpc-gateway/proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func TestCommonDescriptor(t *testing.T) {
	descriptor := protodesc.ToFileDescriptorProto(commonapis.File_proto_common_proto)
	if got, want := descriptor.GetOptions().GetGoPackage(), "github.com/HitGameAI/apex-rpc-gateway/proto;commonapis"; got != want {
		t.Fatalf("go_package = %q, want %q", got, want)
	}
	raw, err := proto.Marshal(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	var decoded descriptorpb.FileDescriptorProto
	if err := proto.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	if _, err := protodesc.NewFile(&decoded, protoregistry.GlobalFiles); err != nil {
		t.Fatalf("rebuild descriptor: %v", err)
	}
}

func TestCommonMessagesRoundTrip(t *testing.T) {
	messages := []proto.Message{
		&commonapis.Result{Code: 7, Error: "failed", Status: commonapis.StatusCode_Unavailable},
		&commonapis.Paging{Page: 2, Size: 20, Total: 100},
		&commonapis.Sorting{Field: "created_at", Reversed: true},
		&commonapis.TimeRange{Start: timestamppb.New(time.Unix(1700000000, 0)), End: timestamppb.New(time.Unix(1700000060, 0))},
	}
	for _, message := range messages {
		t.Run(string(message.ProtoReflect().Descriptor().Name()), func(t *testing.T) {
			raw, err := proto.Marshal(message)
			if err != nil {
				t.Fatal(err)
			}
			// 固定旧协议的字段编号及枚举值，防止重新生成改变线上的编码。
			if _, ok := message.(*commonapis.Result); ok && !bytes.Equal(raw, []byte{0x08, 7, 0x12, 6, 'f', 'a', 'i', 'l', 'e', 'd', 0x18, 14}) {
				t.Fatalf("Result wire encoding changed: %x", raw)
			}
			decoded := message.ProtoReflect().Type().New().Interface()
			if err := proto.Unmarshal(raw, decoded); err != nil {
				t.Fatal(err)
			}
			if !proto.Equal(message, decoded) {
				t.Fatal("protobuf round-trip changed the message")
			}
		})
	}
}
