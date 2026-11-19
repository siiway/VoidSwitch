package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
)

// The platform API reuses the dashboard handlers instead of reimplementing them.
// A tool call builds a synthetic gin context that already carries the
// authenticated user and platform key, binds the arguments as the request body
// (or query string), calls the existing handler, and returns whatever JSON it
// wrote. Validation, audit rows and error messages therefore stay in one place:
// there is no second copy of the rules to drift.
//
// Because the synthetic request never passes through SessionAuth, the credential
// attribution handlers rely on (core.GetPlatformCredential) is attached here.

// bridgeResult is the outcome of one bridged handler call.
type bridgeResult struct {
	Status int
	Body   json.RawMessage
	Err    string
}

// ok reports whether the handler produced a 2xx response.
func (r bridgeResult) ok() bool { return r.Status >= 200 && r.Status < 300 }

// bridge is the synthetic request builder for one tool invocation.
type bridge struct {
	app     *App
	cred    *core.PlatformCredential
	method  string
	path    string
	query   map[string]string
	body    any
	ip      string
	ua      string
	request *http.Request
}

// newBridge builds a bridge for the authenticated caller.
func (a *App) newBridge(c *gin.Context) *bridge {
	b := &bridge{app: a, cred: core.GetPlatformCredential(c), ip: clientIP(c), ua: c.GetHeader("User-Agent")}
	b.request = c.Request
	return b
}

// args splits a tool argument map into path parameters and the request body.
// Keys named after a ":" placeholder in the path are consumed as path params;
// everything else is either the body (for writes) or the query string (for
// reads).
func (b *bridge) args(path string, in map[string]any) (string, map[string]any) {
	rest := make(map[string]any, len(in))
	for k, v := range in {
		rest[k] = v
	}
	for _, seg := range strings.Split(path, "/") {
		if !strings.HasPrefix(seg, ":") {
			continue
		}
		name := strings.TrimPrefix(seg, ":")
		v, ok := rest[name]
		if !ok {
			continue
		}
		path = strings.Replace(path, seg, fmt.Sprint(scalarString(v)), 1)
		delete(rest, name)
	}
	return path, rest
}

// scalarString renders an argument as a path segment.
func scalarString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case float64:
		if t == float64(int64(t)) {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	default:
		return fmt.Sprint(v)
	}
}

// call invokes one handler through a synthetic gin context. The handler's JSON
// response becomes the tool result; a non-2xx response is returned as an error
// so the model sees the real message.
func (b *bridge) call(method, path string, in map[string]any, fn gin.HandlerFunc) bridgeResult {
	path, rest := b.args(path, in)

	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(w)

	var bodyBytes []byte
	if method == http.MethodGet || method == http.MethodDelete {
		vals := make([]string, 0, len(rest))
		for k, v := range rest {
			vals = append(vals, k+"="+urlQueryEscape(queryString(v)))
		}
		raw := strings.Join(vals, "&")
		ctx.Request = httptest.NewRequest(method, path+"?"+raw, nil)
	} else {
		if len(rest) > 0 {
			bodyBytes, _ = json.Marshal(rest)
		}
		ctx.Request = httptest.NewRequest(method, path, bytes.NewReader(bodyBytes))
		ctx.Request.Header.Set("Content-Type", "application/json")
	}
	ctx.Request.Header.Set("User-Agent", b.ua)
	ctx.Set(core.CtxUser, b.cred.User)
	ctx.Set(core.CtxPlatformKey, b.cred)
	if b.cred.ViaMCP {
		ctx.Set(core.CtxPlatformVia, "mcp")
	} else {
		ctx.Set(core.CtxPlatformVia, "rest")
	}
	// clientIP reads the configured header; the synthetic request must carry the
	// real caller's address or the audit row would point nowhere.
	ctx.Request.Header.Set(clientIPHeader, b.ip)

	func() {
		defer func() {
			if rec := recover(); rec != nil {
				w = httptest.NewRecorder()
				w.Code = http.StatusInternalServerError
				_ = json.NewEncoder(w).Encode(gin.H{"detail": fmt.Sprint(rec)})
			}
		}()
		fn(ctx)
	}()

	res := bridgeResult{Status: w.Code}
	if res.Status == 0 {
		res.Status = http.StatusOK
	}
	raw := bytes.TrimSpace(w.Body.Bytes())
	if len(raw) > 0 && json.Valid(raw) {
		res.Body = json.RawMessage(raw)
	}
	if !res.ok() {
		var env struct {
			Detail string `json:"detail"`
		}
		if len(raw) > 0 {
			_ = json.Unmarshal(raw, &env)
		}
		if env.Detail == "" {
			env.Detail = fmt.Sprintf("handler returned status %d", res.Status)
		}
		res.Err = env.Detail
	}
	return res
}

// queryString renders a query/body value as a string.
func queryString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case bool:
		return strconv.FormatBool(t)
	case float64:
		return scalarString(t)
	case nil:
		return ""
	default:
		enc, err := json.Marshal(t)
		if err != nil {
			return fmt.Sprint(t)
		}
		return string(enc)
	}
}

// urlQueryEscape percent-encodes a query value. net/url.QueryEscape turns a
// space into "+", which Go's own query parser reads back correctly, so it is
// the right escape here.
func urlQueryEscape(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9',
			c == '-', c == '_', c == '.', c == '~':
			b.WriteByte(c)
		case c == ' ':
			b.WriteByte('+')
		default:
			fmt.Fprintf(&b, "%%%02X", c)
		}
	}
	return b.String()
}
