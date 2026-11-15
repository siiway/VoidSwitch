package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
)

// Both plugin sources must be servable and must be the file for that generation.
func TestPluginSourceServesCorrectGeneration(t *testing.T) {
	app := &App{Cfg: &config.Settings{}}
	app.Cfg.Server.BaseURL = "https://gw.example"

	cases := []struct{ route, want string }{
		{"/opencode/voidswitch.ts", "@opencode/plugin"},
		{"/opencode/voidswitch.ts?v=1", "@opencode-ai/plugin"},
		{"/opencode/voidswitch-v1.ts", "@opencode-ai/plugin"},
	}
	for _, tc := range cases {
		gin.SetMode(gin.TestMode)
		w := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(w)
		c.Request = httptest.NewRequest(http.MethodGet, tc.route, nil)
		app.pluginSource(c)
		body := w.Body.String()
		if !strings.Contains(body, tc.want) {
			t.Fatalf("%s should contain %q, got first 200: %.200s", tc.route, tc.want, body)
		}
	}
}
