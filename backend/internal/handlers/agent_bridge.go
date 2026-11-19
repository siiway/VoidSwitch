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
// wrote. Validation, audit rows and error messages therefore stay in one place.
//
// The handler reads path parameters through c.Param, so the bridge must populate
// gin.Params as well as the path string — a context built by
// gin.CreateTestContext starts with an empty Params slice.

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
	ip      string
	ua      string
	viaMCP  bool
	request *http.Request
	// alias maps an argument name to the path parameter name the handler reads.
	alias map[string]string
}

func (a *App) newBridge(c *gin.Context) *bridge {
	cred := core.GetPlatformCredential(c)
	return &bridge{
		app: a, cred: cred, ip: clientIP(c), ua: c.GetHeader("User-Agent"),
		viaMCP: cred != nil && cred.ViaMCP, request: c.Request,
		alias: map[string]string{},
	}
}

// withPath records aliases from an argument name to the path parameter name the
// handler reads, so "model_id" reaches a handler that calls c.Param("id").
func (b *bridge) withPath(alias map[string]string) *bridge {
	for handlerName, argName := range alias {
		b.alias[argName] = handlerName
	}
	return b
}

// split separates path parameters from the remaining arguments. A key named
// after a ":" placeholder in the path is consumed as a path parameter;
// everything else becomes the body (writes) or the query string (reads).
func (b *bridge) split(specPath string, in map[string]any) (string, []gin.Param, map[string]any) {
	rest := make(map[string]any, len(in))
	for k, v := range in {
		rest[k] = v
	}
	ginParams := make([]gin.Param, 0, 4)
	for _, seg := range strings.Split(specPath, "/") {
		if !strings.HasPrefix(seg, ":") {
			continue
		}
		name := strings.TrimPrefix(seg, ":")
		v, ok := rest[name]
		if !ok {
			// A read-only path parameter may instead be supplied under the
			// handler's own name (see ParamAlias).
			for argName, handlerName := range b.alias {
				if handlerName != name {
					continue
				}
				if hv, found := rest[argName]; found {
					v, ok = hv, true
					delete(rest, argName)
					break
				}
			}
		}
		if !ok {
			continue
		}
		val := scalarString(v)
		specPath = strings.Replace(specPath, seg, val, 1)
		ginParams = append(ginParams, gin.Param{Key: name, Value: val})
		delete(rest, name)
	}
	return specPath, ginParams, rest
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
func (b *bridge) call(method, specPath string, in map[string]any, fn gin.HandlerFunc) bridgeResult {
	path, params, rest := b.split(specPath, in)

	w := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(w)
	ctx.Params = params

	if method == http.MethodGet || method == http.MethodDelete {
		ctx.Request = httptest.NewRequest(method, path, nil)
		q := ctx.Request.URL.Query()
		for k, v := range rest {
			q.Set(k, queryString(v))
		}
		ctx.Request.URL.RawQuery = q.Encode()
	} else {
		var bodyBytes []byte
		if len(rest) > 0 {
			bodyBytes, _ = json.Marshal(rest)
		}
		ctx.Request = httptest.NewRequest(method, path, bytes.NewReader(bodyBytes))
		ctx.Request.Header.Set("Content-Type", "application/json")
	}
	if b.ua != "" {
		ctx.Request.Header.Set("User-Agent", b.ua)
	}
	ctx.Set(core.CtxUser, b.cred.User)
	ctx.Set(core.CtxPlatformKey, b.cred)
	if b.viaMCP {
		ctx.Set(core.CtxPlatformVia, "mcp")
	} else {
		ctx.Set(core.CtxPlatformVia, "rest")
	}
	// The synthetic request has to carry the real caller's address or the audit
	// row would point nowhere.
	ctx.Set(clientIPContextKey, b.ip)
	if clientIPHeader != "" {
		ctx.Request.Header.Set(clientIPHeader, b.ip)
	}

	res := bridgeResult{Status: w.Code}
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				// Never relay a panic value to the caller: it can carry internal
				// paths or SQL from the driver.
				w = httptest.NewRecorder()
				w.Code = http.StatusInternalServerError
				_ = json.NewEncoder(w).Encode(gin.H{"detail": "Internal Server Error"})
			}
		}()
		fn(ctx)
	}()

	res = bridgeResult{Status: w.Code}
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

// queryString renders a query value as a string.
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
