package observability

import (
	"net/http"
	"strings"
	"testing"

	"github.com/HitGameAI/apex-toolbox/pkg/desensitize"
)

const sampleJWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlMTIzNDU2"

func TestRedactAuthorization_NeverKeepsToken(t *testing.T) {
	got := redactAuthorization("Bearer " + sampleJWT)
	if got != desensitize.RedactedText {
		t.Fatalf("authorization = %q", got)
	}
	if redactAuthorization("  ") != "" {
		t.Fatal("空白凭据不应写入日志")
	}
}

func TestScrubCredentials_PartialMaskLeavesJWT(t *testing.T) {
	in := "authorization=***REDACTED*** " + sampleJWT + " path=/v1/system/dict/entries"
	got := scrubCredentials(in)
	if strings.Contains(got, "eyJ") {
		t.Fatalf("残留 JWT: %s", got)
	}
	if !strings.Contains(got, "/v1/system/dict/entries") {
		t.Fatalf("路径被误擦: %s", got)
	}
}

func TestScrubCredentials_ShortTokenStays(t *testing.T) {
	in := `{"token":"abcd1234wxyz","trace_id":"411082f636a61806d5c302e0a5830235"}`
	got := scrubCredentials(in)
	if got != in {
		t.Fatalf("12 位 token 不应仅凭字段名在这层被擦掉: %s", got)
	}
}

func TestRedactHeaders_AuthorizationAndCookie(t *testing.T) {
	h := make(http.Header)
	h.Set("Authorization", "Bearer "+sampleJWT)
	h.Set("Cookie", "sid=abc")
	h.Set("User-Agent", "tenant-web")
	h.Set("X-Trace-Id", "0e2df759ca984bf201acc1cd4c125992")

	out := redactHeaders(h)
	if strings.Contains(out.Get("Authorization"), "eyJ") || out.Get("Authorization") == "" {
		t.Fatalf("Authorization = %q", out.Get("Authorization"))
	}
	if out.Get("Cookie") == "sid=abc" {
		t.Fatal("Cookie 未脱敏")
	}
	if out.Get("User-Agent") != "tenant-web" || out.Get("X-Trace-Id") == "" {
		t.Fatalf("非凭据头被改了: %v", out)
	}
	if h.Get("Authorization") == "" {
		t.Fatal("脱敏不应改原请求头")
	}
}

func TestRedactRequestURL_DropsCredentialQuery(t *testing.T) {
	req, err := http.NewRequest(http.MethodGet, "https://user:pw@tenant.example/v1/payment/orders?authorization="+sampleJWT+"&page=1", nil)
	if err != nil {
		t.Fatal(err)
	}
	got := redactRequestURL(req)
	if strings.Contains(got, sampleJWT) || strings.Contains(got, "user:pw") {
		t.Fatalf("URL 仍含凭据: %s", got)
	}
	if !strings.Contains(got, "/v1/payment/orders") || !strings.Contains(got, "page=1") {
		t.Fatalf("业务 URL 被破坏: %s", got)
	}
}
