// Command voidswitch is the VoidSwitch gateway and dashboard API server.
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/handlers"
	"github.com/siiway/voidswitch/internal/redisx"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/tasks"
)

func main() {
	cfg := config.Load()
	configureLogging(cfg)

	if err := cfg.Validate(); err != nil {
		slog.Error("invalid configuration", "err", err)
		os.Exit(1)
	}

	ctx := context.Background()

	// Database + migrations.
	db, err := database.Open(cfg.Database.URL, cfg.Database.Echo)
	if err != nil {
		slog.Error("connect database", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	res, err := db.Migrate(ctx)
	if err != nil {
		slog.Error("run migrations", "err", err)
		os.Exit(1)
	}
	slog.Info("migrations ready", "adopted_existing", res.Adopted, "version", res.Version)

	// Redis.
	rdb, err := redisx.New(ctx, redisx.Config{
		URL:       cfg.Redis.URL,
		KeyPrefix: cfg.Redis.KeyPrefix,
		MaxConns:  cfg.Redis.MaxConnections,
	})
	if err != nil {
		slog.Error("connect redis", "err", err)
		os.Exit(1)
	}
	defer rdb.Close()
	services.SetSettingsRedis(rdb)

	// Seed settings + special groups, then load into cache.
	if err := services.EnsureSettingsDefaults(db.Gorm); err != nil {
		slog.Error("seed settings", "err", err)
		os.Exit(1)
	}
	if _, err := services.LoadSettings(db.Gorm); err != nil {
		slog.Error("load settings", "err", err)
		os.Exit(1)
	}
	if err := services.EnsureSeededNodeGroups(db.Gorm); err != nil {
		slog.Error("seed node groups", "err", err)
		os.Exit(1)
	}
	if _, err := services.EnsureModeratorGroup(db.Gorm); err != nil {
		slog.Error("seed moderator group", "err", err)
		os.Exit(1)
	}
	services.StartSettingsListener(db.Gorm)
	defer services.StopSettingsListener()

	if cfg.DevAuthBypassActive() {
		slog.Warn("DEV AUTH BYPASS ACTIVE — login is disabled; a synthetic owner identity is used. NEVER run this in production.")
	}

	// Background tasks.
	taskMgr := tasks.New(db.Gorm)
	tasks.RegisterDefaults(taskMgr, db.Gorm, cfg.Server.SecretKey)
	taskMgr.Start()
	defer taskMgr.Stop()

	app := &handlers.App{DB: db, GDB: db.Gorm, Cfg: cfg, RDB: rdb, Tasks: taskMgr}
	router := buildRouter(app, cfg)

	addr := cfg.Server.Host + ":" + itoa(cfg.Server.Port)
	srv := &http.Server{
		Addr:              addr,
		Handler:           router,
		ReadHeaderTimeout: 15 * time.Second,
	}

	go func() {
		slog.Info("VoidSwitch listening", "addr", addr, "base_url", cfg.Server.BaseURL, "version", handlers.Version)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	slog.Info("shutting down")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
}

func buildRouter(app *handlers.App, cfg *config.Settings) *gin.Engine {
	if cfg.Server.Debug {
		gin.SetMode(gin.DebugMode)
	} else {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(gin.Recovery())
	if cfg.Server.Debug {
		r.Use(gin.Logger())
	}
	r.Use(corsMiddleware(cfg.Server.CorsOrigins))

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "version": handlers.Version})
	})
	r.GET("/", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"name": "VoidSwitch", "version": handlers.Version})
	})

	// Public gateway + installer.
	handlers.RegisterGatewayRoutes(r.Group("/v1"), app)
	handlers.RegisterInstallRoutes(r, app)
	handlers.RegisterProviderAPIRoutes(r, app)
	handlers.RegisterSPA(r, app)

	api := r.Group("/api")
	handlers.RegisterAuthRoutes(api.Group("/auth"), app, core.SessionAuth(app.GDB, cfg))

	authed := api.Group("")
	authed.Use(core.SessionAuth(app.GDB, cfg))
	{
		handlers.RegisterMeRoutes(authed, app)
		handlers.RegisterModelRoutes(authed, app)
		handlers.RegisterAnnouncementRoutes(authed, app)
		handlers.RegisterUsageRoutes(authed, app)
		// Logs live under /api/admin/logs but are NOT staff-gated: request logs are
		// member-visible (own traffic), audit logs are staff-or-role-group-admin.
		// The handlers enforce the row-level scope. See docs/architecture.md.
		handlers.RegisterLogRoutes(authed.Group("/admin"), app)

		admin := authed.Group("/admin")
		admin.Use(core.RequireStaff())
		{
			handlers.RegisterStatsRoutes(admin, app)
			handlers.RegisterSettingsRoutes(admin, app)
			handlers.RegisterProviderRoutes(admin, app)
			handlers.RegisterKeyRoutes(admin, app)
			handlers.RegisterNodeRoutes(admin, app)
			handlers.RegisterRoleGroupRoutes(admin, app)
			handlers.RegisterUserRoutes(admin, app)
			handlers.RegisterAdminTokenRoutes(admin, app)
		}
	}
	return r
}

func corsMiddleware(origins []string) gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		for _, o := range origins {
			if o == "*" || o == origin {
				c.Header("Access-Control-Allow-Origin", origin)
				c.Header("Access-Control-Allow-Credentials", "true")
				break
			}
		}
		c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Authorization,Content-Type,X-API-Key")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

func configureLogging(cfg *config.Settings) {
	level := slog.LevelInfo
	if cfg.Server.Debug {
		level = slog.LevelDebug
	}
	var handler slog.Handler
	if cfg.Server.LogConsole {
		handler = slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: level})
	} else {
		handler = slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})
	}
	slog.SetDefault(slog.New(handler))
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

var _ = gorm.ErrRecordNotFound
