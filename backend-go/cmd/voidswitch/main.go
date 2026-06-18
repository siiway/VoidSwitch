package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/handlers"
	"github.com/siiway/voidswitch/internal/handlers/admin"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/tasks"
)

func main() {
	cfg := config.Load()

	if cfg.Server.DevMode {
		log.Println("WARNING DEV MODE enabled — OAuth bypass active. Do NOT use in production.")
	}

	db, err := database.InitDatabase(cfg.Database.URL, cfg.Database.Echo)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer db.Close()

	if err := db.AutoMigrate(); err != nil {
		log.Fatalf("Failed to migrate database: %v", err)
	}

	gormDB := db.DB
	if err := services.EnsureDefaults(gormDB); err != nil {
		log.Fatalf("Failed to seed settings: %v", err)
	}
	if _, err := services.LoadAll(gormDB); err != nil {
		log.Fatalf("Failed to load settings: %v", err)
	}
	log.Println("Database ready")

	taskManager := startTasks(gormDB, cfg)
	admin.TaskManager = taskManager

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

	// Public proxy routes (API key auth, no session required)
	handlers.RegisterProxyRoutes(&r.RouterGroup)

	// Session-authenticated API routes
	api := r.Group("/api")
	{
		// Auth routes — publicly accessible
		handlers.RegisterAuthRoutes(api.Group("/auth"))

		// Protected routes — session token required
		protected := api.Group("")
		protected.Use(core.GetCurrentUser(gormDB, cfg))
		{
			handlers.RegisterMeRoutes(protected.Group("/me"))

			// Admin routes — staff role required
			adminGroup := protected.Group("/admin")
			adminGroup.Use(core.RequireStaff())
			{
				admin.RegisterProviderRoutes(adminGroup)
				admin.RegisterKeyRoutes(adminGroup)
				admin.RegisterProxyRoutes(adminGroup)
				admin.RegisterTokenRoutes(adminGroup)
				admin.RegisterUserRoutes(adminGroup)
				admin.RegisterSettingsRoutes(adminGroup)
				admin.RegisterLogRoutes(adminGroup)
				admin.RegisterStatsRoutes(adminGroup)
				admin.RegisterSystemRoutes(adminGroup)
				handlers.RegisterAnnouncementRoutes(adminGroup)
				admin.RegisterRoleGroupRoutes(adminGroup)
			}
		}

		// Provider key-management API — auth via vsk- bearer token
		handlers.RegisterProviderAPIRoutes(api.Group("/provider-keys"))
	}

	// Documentation site — auth via cookie or query token
	handlers.RegisterDocsRoutes(r.Group("/docs"))

	addr := fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port)
	log.Printf("VoidSwitch starting on %s", addr)
	log.Printf("Base URL: %s", cfg.Server.BaseURL)

	go func() {
		if err := r.Run(addr); err != nil {
			log.Fatalf("Server failed: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Shutting down...")
	taskManager.Stop()
}

func startTasks(gormDB *gorm.DB, cfg *config.Settings) *tasks.TaskManager {
	manager := tasks.NewTaskManager()

	manager.Register(&tasks.PeriodicTask{
		Name:        "balance_probe",
		Tick:        func() error { return tasks.RunBalanceProbe(gormDB, cfg) },
		IntervalKey: "balance_probe_interval_seconds",
		EnabledKey:  strPtr("balance_probe_enabled"),
		MinInterval: 30,
	})
	manager.Register(&tasks.PeriodicTask{
		Name:        "balance_rescan",
		Tick:        func() error { return tasks.RunBalanceRescan(gormDB, cfg) },
		IntervalKey: "balance_rescan_interval_seconds",
		EnabledKey:  strPtr("balance_rescan_enabled"),
		MinInterval: 60,
	})
	manager.Register(&tasks.PeriodicTask{
		Name:        "proxy_resurrector",
		Tick:        func() error { return tasks.RunProxyResurrector(gormDB, cfg) },
		IntervalKey: "proxy_probe_interval_seconds",
		EnabledKey:  strPtr("proxy_resurrector_enabled"),
		MinInterval: 15,
	})
	tasks.RegisterLogCleanupTask(manager)

	manager.Start()
	return manager
}

func strPtr(s string) *string { return &s }

func corsMiddleware(origins []string) gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		allowed := false
		for _, o := range origins {
			if o == "*" || o == origin {
				allowed = true
				break
			}
		}
		if allowed {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Credentials", "true")
		}
		c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Authorization,Content-Type,X-API-Key")
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}
