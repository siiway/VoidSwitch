package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/siiway/voidswitch/internal/core"
)

// mcpServerOptions is shared by every per-request server instance. Tools are
// registered per request (the list depends on the key's scopes), so the schema
// cache has to be process-wide or every call would rebuild 50 JSON schemas.
var mcpSchemaCache = mcp.NewSchemaCache()

// mcpToolName turns a scope action into an MCP tool name. MCP tool names allow
// only letters, digits, "_" and "-", so "model.route.get" becomes
// "vs_model_route_get".
func mcpToolName(action string) string {
	return "vs_" + strings.NewReplacer(".", "_", ":", "_", "-", "_").Replace(action)
}

// RegisterPlatformMCPRoutes serves the MCP Streamable HTTP endpoint at
// /api/v1/mcp.
//
// The transport runs stateless: every POST carries its own Authorization header,
// no session id is minted, and the server instance is built for that one key.
// That is what lets many keys share one URL, and it is the only mode the SDK
// accepts for the current protocol revision.
func RegisterPlatformMCPRoutes(r *gin.RouterGroup, a *App) {
	handler := mcp.NewStreamableHTTPHandler(func(req *http.Request) *mcp.Server {
		cred := platformCredentialFromRequest(req)
		if cred == nil {
			return nil
		}
		return a.platformMCPServer(cred)
	}, &mcp.StreamableHTTPOptions{Stateless: true})

	group := r.Group("/v1")
	group.Use(core.PlatformKeyAuth(a.GDB, true), a.platformRateLimit())
	group.Any("/mcp", func(c *gin.Context) {
		if c.Request.Method == http.MethodOptions {
			c.Status(http.StatusNoContent)
			return
		}
		rc := &mcpRequestContext{cred: core.GetPlatformCredential(c), ip: clientIP(c), ua: c.GetHeader("User-Agent")}
		handler.ServeHTTP(c.Writer, c.Request.WithContext(withPlatformRequest(c.Request.Context(), rc)))
	})
}

// mcpRequestContext is everything a tool handler needs from the HTTP request:
// the authenticated key plus the caller's address and user agent, which the
// audit rows record.
type mcpRequestContext struct {
	cred *core.PlatformCredential
	ip   string
	ua   string
}

// platformCredentialContextKey carries the authenticated key from the gin layer
// into the SDK's getServer callback, which only sees an *http.Request.
type platformCredentialContextKey struct{}

func withPlatformRequest(ctx context.Context, rc *mcpRequestContext) context.Context {
	return context.WithValue(ctx, platformCredentialContextKey{}, rc)
}

func platformRequestFromContext(ctx context.Context) *mcpRequestContext {
	rc, _ := ctx.Value(platformCredentialContextKey{}).(*mcpRequestContext)
	return rc
}

func platformCredentialFromRequest(req *http.Request) *core.PlatformCredential {
	rc := platformRequestFromContext(req.Context())
	if rc == nil {
		return nil
	}
	return rc.cred
}

// ginContextForTool rebuilds a minimal gin context for the bridge, so handler
// helpers that read clientIP / User-Agent see the real caller. The SDK hands
// tool handlers the request context the transport created, which carries the
// values PlatformKeyAuth's gin layer derived from the HTTP request.
func ginContextForTool(ctx context.Context) (*gin.Context, bool) {
	rc := platformRequestFromContext(ctx)
	if rc == nil {
		return nil, false
	}
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/mcp", nil)
	c.Set(clientIPContextKey, rc.ip)
	c.Set(core.CtxUser, rc.cred.User)
	c.Set(core.CtxPlatformKey, rc.cred)
	c.Set(core.CtxPlatformVia, "mcp")
	return c, true
}

// errorResult builds a tool result flagged as an error.
func errorResult(msg string) *mcp.CallToolResult {
	return &mcp.CallToolResult{
		IsError: true,
		Content: []mcp.Content{&mcp.TextContent{Text: msg}},
	}
}

// resultText is the human/model-readable projection of a handler response.
func resultText(body []byte) string {
	if len(body) == 0 {
		return "ok"
	}
	return string(body)
}

// jsonValue decodes a handler's JSON response for the structured channel.
func jsonValue(body []byte) any {
	var v any
	if err := json.Unmarshal(body, &v); err != nil {
		return string(body)
	}
	return v
}

// platformMCPServer builds the MCP server for one credential: only the tools its
// scopes cover are registered, so tools/list never advertises an operation the
// call would reject.
func (a *App) platformMCPServer(cred *core.PlatformCredential) *mcp.Server {
	opts := &mcp.ServerOptions{SchemaCache: mcpSchemaCache}
	if len(cred.Scopes) == 0 {
		// An empty tool list is otherwise indistinguishable from "nothing to do";
		// say why, since an agent has no other way to ask.
		opts.Instructions = "This platform API key has no scopes its owner's current role may still grant. " +
			"Ask a platform owner to re-scope the key (Settings → Platform API Keys)."
	}
	server := mcp.NewServer(&mcp.Implementation{
		Name:    "voidswitch",
		Version: strings.TrimPrefix(Version, "v"),
	}, opts)

	for _, tool := range a.platformTools() {
		tool := tool
		if !tool.visible(cred) {
			continue
		}
		mcp.AddTool(server, &mcp.Tool{
			Name:        mcpToolName(tool.Action),
			Description: toolDescription(tool),
			Annotations: &mcp.ToolAnnotations{ReadOnlyHint: toolIsReadOnly(tool)},
		}, func(ctx context.Context, req *mcp.CallToolRequest, in map[string]any) (*mcp.CallToolResult, any, error) {
			return a.callPlatformToolByAction(ctx, tool.Action, in)
		})
	}
	return server
}

func toolIsReadOnly(tool toolSpec) bool {
	act, ok := core.ActionByName(tool.Action)
	return ok && act.Tier == core.TierRead
}

// toolDescription renders the one-line summary plus the argument list, so the
// model does not have to guess at parameter names.
func toolDescription(tool toolSpec) string {
	act, _ := core.ActionByName(tool.Action)
	var b strings.Builder
	b.WriteString(act.Summary)
	b.WriteString("\n\nScope: ")
	b.WriteString(tool.Action)
	if len(tool.Params) > 0 {
		b.WriteString("\n\nArguments:")
		for _, p := range tool.Params {
			b.WriteString("\n- ")
			b.WriteString(p.Name)
			b.WriteString(" (")
			b.WriteString(p.Type)
			b.WriteString("): ")
			b.WriteString(p.Desc)
		}
	}
	return b.String()
}

// callPlatformToolByAction runs one tool through the same bridge the REST
// surface uses, so MCP and REST cannot diverge.
func (a *App) callPlatformToolByAction(ctx context.Context, action string, in map[string]any) (*mcp.CallToolResult, any, error) {
	rc := platformRequestFromContext(ctx)
	var cred *core.PlatformCredential
	if rc != nil {
		cred = rc.cred
	}
	tool, ok := a.platformToolByAction(action)
	if !ok {
		return errorResult("unknown tool: " + action), nil, nil
	}
	if cred == nil {
		return errorResult("missing credentials"), nil, nil
	}
	if !tool.visible(cred) {
		return errorResult("this API key is missing the '" + action + "' scope"), nil, nil
	}

	// The bridge needs a gin context for clientIP/User-Agent; build the minimal
	// one from the request context so no HTTP round trip is involved.
	c, ok := ginContextForTool(ctx)
	if !ok {
		return errorResult("no request context"), nil, nil
	}
	b := a.newBridge(c)
	b.withPath(tool.fixedParams())

	if tool.ProviderScoped {
		slug, _ := in["slug"].(string)
		if slug == "" {
			return errorResult("the 'slug' argument is required for provider key operations"), nil, nil
		}
		if !cred.AllowsProviderKey(slug, action) {
			return errorResult("this API key is not permitted to manage provider '" + slug + "'"), nil, nil
		}
	}

	res := b.call(tool.Method, tool.Path, in, tool.Handler)
	if !res.ok() {
		return errorResult(res.Err), nil, nil
	}
	out := any(map[string]any{})
	if len(res.Body) > 0 {
		out = jsonValue(res.Body)
	}
	return &mcp.CallToolResult{
		Content: []mcp.Content{&mcp.TextContent{Text: resultText(res.Body)}},
	}, out, nil
}

// platformToolByAction looks a tool up by its scope name.
func (a *App) platformToolByAction(action string) (toolSpec, bool) {
	for _, t := range a.platformTools() {
		if t.Action == action {
			return t, true
		}
	}
	return toolSpec{}, false
}
