package observability

import (
	"net/http"
	"strings"

	"github.com/HitGameAI/apex-toolbox/pkg/desensitize"
)

// redactAuthorization 日志里只保留「带过凭据」这个事实，不保留凭据本身
// 字段名脱敏依赖日志库开关；这里在写入前就把值换掉，避免开关关闭或旧日志库原样输出
func redactAuthorization(v string) string {
	if isBlank(v) {
		return ""
	}
	return desensitize.RedactedText
}

// maskedText 先按字段名脱敏，再擦掉残留的 Bearer/Basic 与三段式 JWT
func maskedText(masker *desensitize.DataMasker, s string) string {
	if s == "" {
		return ""
	}
	if masker == nil {
		masker = activeMasker()
	}
	return scrubCredentials(masker.MaskString(s))
}

// redactHeaders 访问日志入库前去掉认证头。Body 已经脱敏时，Header 仍会把 JWT 原样落库
func redactHeaders(h http.Header) http.Header {
	if len(h) == 0 {
		return h
	}
	out := make(http.Header, len(h))
	for key, values := range h {
		if isSensitiveHeader(key) {
			masked := make([]string, len(values))
			for i, v := range values {
				if v != "" {
					masked[i] = desensitize.RedactedText
				}
			}
			out[key] = masked
			continue
		}
		copied := make([]string, len(values))
		for i, v := range values {
			copied[i] = scrubCredentials(v)
		}
		out[key] = copied
	}
	return out
}

// redactRequestURL 链路属性不记录 userinfo，查询串走与访问日志相同的脱敏
func redactRequestURL(r *http.Request) string {
	if r == nil || r.URL == nil {
		return ""
	}
	u := *r.URL
	u.User = nil
	if u.RawQuery != "" {
		u.RawQuery = maskedText(activeMasker(), u.RawQuery)
	}
	return u.String()
}

func isSensitiveHeader(name string) bool {
	switch strings.ToLower(name) {
	case "authorization", "proxy-authorization", "cookie", "set-cookie",
		"x-api-key", "x-access-key", "x-signature", "x-csrf-token":
		return true
	}
	return desensitize.ActionForKey(name) == desensitize.WipeValue
}

// scrubCredentials 擦掉认证方案后的凭据，以及没有方案名、直接出现的三段式 JWT
func scrubCredentials(s string) string {
	if s == "" || !mayContainCredential(s) {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); {
		if end, ok := consumeAuthToken(s, i); ok {
			b.WriteString(desensitize.RedactedText)
			i = end
			continue
		}
		if end, ok := consumeJWT(s, i); ok {
			b.WriteString(desensitize.RedactedText)
			i = end
			continue
		}
		b.WriteByte(s[i])
		i++
	}
	return b.String()
}

func mayContainCredential(s string) bool {
	return strings.Contains(s, "eyJ") || strings.Contains(s, "earer") || strings.Contains(s, "asic ")
}

func consumeAuthToken(s string, i int) (int, bool) {
	if i > 0 && isSchemeChar(s[i-1]) {
		return 0, false
	}
	n := authSchemeLen(s[i:])
	if n == 0 || i+n >= len(s) || !isSpaceByte(s[i+n]) {
		return 0, false
	}
	j := i + n
	for j < len(s) && isSpaceByte(s[j]) {
		j++
	}
	start := j
	for j < len(s) && !isCredentialBoundary(s[j]) {
		j++
	}
	if j == start {
		return 0, false
	}
	return j, true
}

func authSchemeLen(s string) int {
	if hasFoldPrefix(s, "bearer") {
		return len("bearer")
	}
	if hasFoldPrefix(s, "basic") {
		return len("basic")
	}
	return 0
}

func hasFoldPrefix(s, prefix string) bool {
	if len(s) < len(prefix) {
		return false
	}
	for i := 0; i < len(prefix); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		if c != prefix[i] {
			return false
		}
	}
	return true
}

const minCredentialJWTSegment = 8

func consumeJWT(s string, i int) (int, bool) {
	if i > 0 && isBase64URLByte(s[i-1]) {
		return 0, false
	}
	a, ok := base64Segment(s, i)
	if !ok || a >= len(s) || s[a] != '.' {
		return 0, false
	}
	b, ok := base64Segment(s, a+1)
	if !ok || b >= len(s) || s[b] != '.' {
		return 0, false
	}
	c, ok := base64Segment(s, b+1)
	if !ok {
		return 0, false
	}
	if c < len(s) && (isBase64URLByte(s[c]) || s[c] == '.') {
		return 0, false
	}
	return c, true
}

func base64Segment(s string, i int) (int, bool) {
	start := i
	for i < len(s) && isBase64URLByte(s[i]) {
		i++
	}
	if i-start < minCredentialJWTSegment {
		return 0, false
	}
	pad := 0
	for i < len(s) && s[i] == '=' && pad < 2 {
		i++
		pad++
	}
	return i, true
}

func isBase64URLByte(c byte) bool {
	return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_'
}

func isSchemeChar(c byte) bool {
	return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
}

func isSpaceByte(c byte) bool {
	return c == ' ' || c == '\t'
}

func isCredentialBoundary(c byte) bool {
	switch c {
	case ' ', '\t', '\n', '\r', '"', '\'', ',', ';', '&', '<', '>':
		return true
	}
	return false
}
