package handlers

import (
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestClientIPUsesFirstXFF(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest("GET", "/", nil)
	c.Request.Header.Set("X-Forwarded-For", "120.240.94.198, 172.22.0.1")
	c.Request.RemoteAddr = "172.22.0.1:1234"
	if got := clientIP(c); got != "120.240.94.198" {
		t.Fatalf("got %q, want first XFF entry", got)
	}
}

func TestClientIPCustomHeader(t *testing.T) {
	gin.SetMode(gin.TestMode)
	SetClientIPHeader("CF-Connecting-IP")
	defer SetClientIPHeader("X-Forwarded-For")
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest("GET", "/", nil)
	c.Request.Header.Set("CF-Connecting-IP", "203.0.113.9")
	c.Request.Header.Set("X-Forwarded-For", "1.2.3.4, 5.6.7.8")
	if got := clientIP(c); got != "203.0.113.9" {
		t.Fatalf("got %q, want custom header value", got)
	}
}
