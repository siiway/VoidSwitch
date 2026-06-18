package tasks

import (
	"log"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

func RunProxyResurrector(db *gorm.DB, settings *config.Settings) error {
	probeURL := services.GetCached("proxy_probe_url", "https://api.openai.com/v1/models")
	probeURLStr, ok := probeURL.(string)
	if !ok {
		probeURLStr = "https://api.openai.com/v1/models"
	}

	var proxies []database.Proxy
	if err := db.Where("enabled = ? AND status = ?", true, string(constants.ProxyStatusDisabled)).Find(&proxies).Error; err != nil {
		return err
	}

	for _, proxy := range proxies {
		route := services.NewRoute(
			stringPtrOrNil(proxy.URL),
			proxy.LocalAddress,
		)

		ok, latencyMs, _, _ := services.ProbeRoute(route, probeURLStr, nil, 15*time.Second)

		now := time.Now()
		proxy.LastCheckedAt = &now
		proxy.LatencyMs = &latencyMs

		if ok {
			proxy.Status = string(constants.ProxyStatusActive)
			proxy.FailedCount = 0
			proxy.DisabledReason = nil
			log.Printf("proxy_resurrected proxy_id=%d latency_ms=%.0f", proxy.ID, latencyMs)
		}

		if err := db.Save(&proxy).Error; err != nil {
			log.Printf("proxy_resurrector: save proxy %d: %v", proxy.ID, err)
		}
	}

	return nil
}

func stringPtrOrNil(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
