package handlers

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

// RegisterSPA serves the built frontend (frontend/dist) with SPA fallback when
// a dist directory is configured and present. API/gateway paths are never
// intercepted (they are registered as explicit routes before this catch-all).
func RegisterSPA(r *gin.Engine, a *App) {
	dir := a.Cfg.Server.WebDistDir
	if dir == "" {
		for _, c := range []string{"../frontend/dist", "frontend/dist"} {
			if st, err := os.Stat(filepath.Join(c, "index.html")); err == nil && !st.IsDir() {
				dir = c
				break
			}
		}
	}
	if dir == "" {
		return
	}
	index := filepath.Join(dir, "index.html")
	if _, err := os.Stat(index); err != nil {
		return
	}
	absDir, _ := filepath.Abs(dir)

	r.NoRoute(func(c *gin.Context) {
		p := c.Request.URL.Path
		// Never shadow backend-owned prefixes.
		for _, prefix := range []string{"/api/", "/v1/", "/provider-api/", "/healthz", "/install", "/opencode/"} {
			if strings.HasPrefix(p, prefix) || p == strings.TrimSuffix(prefix, "/") {
				c.Status(404)
				return
			}
		}
		if c.Request.Method != "GET" && c.Request.Method != "HEAD" {
			c.Status(404)
			return
		}
		// Serve an existing static asset; otherwise fall back to index.html.
		candidate := filepath.Join(absDir, filepath.Clean(p))
		if strings.HasPrefix(candidate, absDir) {
			if st, err := os.Stat(candidate); err == nil && !st.IsDir() {
				c.File(candidate)
				return
			}
		}
		c.File(index)
	})
}
