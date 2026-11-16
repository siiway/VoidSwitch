package handlers

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// A passthrough exposed id may contain slashes ("openrouter/stealth/x"). With a
// single-segment :exposed the router answered 404 for exactly those ids, so
// deleting them from the model page failed while plain ids worked.
func TestPassthroughDeleteRouteAcceptsMultiSegmentIDs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	var gotSlug, gotExposed string
	g := r.Group("/api/models")
	g.DELETE("/passthrough/:slug/*exposed", func(c *gin.Context) {
		gotSlug = c.Param("slug")
		gotExposed = strings.TrimPrefix(c.Param("exposed"), "/")
		c.Status(http.StatusNoContent)
	})

	cases := []struct{ url, slug, exposed string }{
		{"/api/models/passthrough/openrouter/stealth/space-bunny-alpha", "openrouter", "stealth/space-bunny-alpha"},
		{"/api/models/passthrough/openrouter/stealth%2Fspace-bunny-alpha", "openrouter", "stealth/space-bunny-alpha"},
		{"/api/models/passthrough/openrouter/gpt-4o", "openrouter", "gpt-4o"},
	}
	for _, c := range cases {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodDelete, c.url, nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusNoContent {
			t.Fatalf("%s answered %d, want 204", c.url, w.Code)
		}
		if gotSlug != c.slug || gotExposed != c.exposed {
			t.Fatalf("%s parsed (%s, %s), want (%s, %s)",
				c.url, gotSlug, gotExposed, c.slug, c.exposed)
		}
	}
}

// The model id route must not swallow the passthrough namespace.
func TestPassthroughDeleteRouteDoesNotShadowModelDelete(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	g := r.Group("/api/models")
	g.DELETE("/passthrough/:slug/*exposed", func(c *gin.Context) { c.Status(http.StatusNoContent) })
	g.DELETE("/:id", func(c *gin.Context) {
		c.String(http.StatusOK, c.Param("id"))
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodDelete, "/api/models/42", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK || w.Body.String() != "42" {
		t.Fatalf("/api/models/42 answered %d %q, want the model-delete handler", w.Code, w.Body.String())
	}
}

// removedIDs reports only ids that existed, keeping request order, so a batch
// delete of a stale selection does not claim work it never did.
func TestRemovedIDs(t *testing.T) {
	got := removedIDs(
		[]string{"a", "b", "c", "d"},
		[]string{"c", "a"},
		map[string]bool{"d": true},
	)
	if strings.Join(got, ",") != "a,c,d" {
		t.Fatalf("removedIDs = %v, want [a c d]", got)
	}
}

// An empty selection reports nothing rather than a stale count.
func TestRemovedIDsEmpty(t *testing.T) {
	if got := removedIDs(nil, nil, nil); len(got) != 0 {
		t.Fatalf("removedIDs = %v, want empty", got)
	}
}
