package handlers

import (
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

func RegisterDocsRoutes(router *gin.RouterGroup) {
	router.GET("/*path", handleDocs)
}

const docsCookieName = "vs_docs_session"

func resolveDocsRoot(cfg *config.Settings) string {
	if cfg.Server.DocsDir != "" {
		if info, err := os.Stat(cfg.Server.DocsDir); err == nil && info.IsDir() {
			return cfg.Server.DocsDir
		}
	}
	return ""
}

func handleDocs(c *gin.Context) {
	cfg := config.Load()
	secretKey := cfg.Server.SecretKey

	queryToken := c.Query("token")
	if queryToken != "" {
		claims, err := core.DecodeSessionToken(queryToken, secretKey)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid or expired session."})
			return
		}
		sub, _ := claims["sub"].(string)
		if sub == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid session."})
			return
		}
		db := database.GetDatabase().DB
		var user database.User
		if err := db.Where("sub = ? AND enabled = ?", sub, true).First(&user).Error; err != nil {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Account disabled."})
			return
		}
		path := c.Param("path")
		secure := len(cfg.Server.BaseURL) > 5 && cfg.Server.BaseURL[:5] == "https"
		c.SetCookie(docsCookieName, queryToken, cfg.Server.SessionTTLMinutes*60, "/docs", "", secure, true)
		c.Redirect(http.StatusFound, "/docs"+path)
		return
	}

	cookie, err := c.Cookie(docsCookieName)
	if err != nil || cookie == "" {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Sign in to view the documentation."})
		return
	}

	claims, err := core.DecodeSessionToken(cookie, secretKey)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid session."})
		return
	}
	sub, _ := claims["sub"].(string)
	if sub == "" {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Invalid session."})
		return
	}

	db := database.GetDatabase().DB
	var user database.User
	if err := db.Where("sub = ? AND enabled = ?", sub, true).First(&user).Error; err != nil {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Account disabled."})
		return
	}

	root := resolveDocsRoot(cfg)
	if root == "" {
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{"error": "Documentation has not been built yet."})
		return
	}

	rel := c.Param("path")
	rel = strings.TrimPrefix(rel, "/")
	target := filepath.Join(root, rel)
	target, _ = filepath.Abs(target)
	rootAbs, _ := filepath.Abs(root)

	if !strings.HasPrefix(target, rootAbs) {
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "Not found."})
		return
	}

	info, err := os.Stat(target)
	if err == nil && info.IsDir() {
		index := filepath.Join(target, "index.html")
		if fi, e := os.Stat(index); e == nil && !fi.IsDir() {
			serveFile(c, index)
			return
		}
	}

	if err == nil && !info.IsDir() {
		serveFile(c, target)
		return
	}

	htmlPath := filepath.Join(root, rel+".html")
	if fi, e := os.Stat(htmlPath); e == nil && !fi.IsDir() {
		serveFile(c, htmlPath)
		return
	}

	notFound := filepath.Join(root, "404.html")
	if fi, e := os.Stat(notFound); e == nil && !fi.IsDir() {
		c.Writer.WriteHeader(http.StatusNotFound)
		serveFile(c, notFound)
		return
	}

	c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "Not found."})
}

func serveFile(c *gin.Context, path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": "Not found."})
		return
	}
	contentType := mime.TypeByExtension(filepath.Ext(path))
	if contentType == "" {
		contentType = "application/octet-stream"
	}

	headers := make(map[string]string)
	if strings.Contains(path, "/assets/") {
		headers["Cache-Control"] = "public, max-age=31536000, immutable"
	} else if strings.HasSuffix(path, ".html") {
		headers["Cache-Control"] = "no-cache"
	}

	for k, v := range headers {
		c.Header(k, v)
	}
	c.Data(http.StatusOK, contentType, data)
}

func init() {
	mime.AddExtensionType(".ts", "application/typescript")
	mime.AddExtensionType(".js", "application/javascript")
	mime.AddExtensionType(".css", "text/css")
	mime.AddExtensionType(".svg", "image/svg+xml")
	mime.AddExtensionType(".woff2", "font/woff2")
}
