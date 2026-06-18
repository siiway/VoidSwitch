package tasks

import (
	"log"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
	"github.com/siiway/voidswitch/internal/services/providers"
)

func RunBalanceRescan(db *gorm.DB, settings *config.Settings) error {
	ratePerSec := services.GetInt("balance_scan_rate_per_second", 5)
	if ratePerSec < 1 {
		ratePerSec = 1
	}
	delay := time.Second / time.Duration(ratePerSec)

	pool := services.GetPool()

	var providerList []database.Provider
	if err := db.Where("enabled = ?", true).Find(&providerList).Error; err != nil {
		return err
	}

	for _, provider := range providerList {
		adapter := providers.GetAdapter(&provider)
		if adapter.GetBalanceURL() == "" {
			continue
		}

		var keys []database.ApiKey
		if err := db.Where("provider_id = ? AND status = ?", provider.ID, string(constants.KeyStatusInsufficientBalance)).Find(&keys).Error; err != nil {
			log.Printf("balance_rescan: query keys for provider %s: %v", provider.Name, err)
			continue
		}

		route := services.NewRoute(nil, nil)
		client, err := pool.Get(route, 15*time.Second, 30*time.Second)
		if err != nil {
			log.Printf("balance_rescan: get client for provider %s: %v", provider.Name, err)
			continue
		}

		for _, key := range keys {
			isAvailable, err := services.RefreshKeyBalance(&key, &provider, client, settings, true, adapter)
			if err != nil {
				log.Printf("balance_rescan: key %d provider %s: %v", key.ID, provider.Name, err)
			}
			if err := db.Save(&key).Error; err != nil {
				log.Printf("balance_rescan: save key %d: %v", key.ID, err)
			}
			if isAvailable && key.Status == string(constants.KeyStatusActive) {
				log.Printf("key_reenabled_by_balance_rescan key_id=%d", key.ID)
			}
			time.Sleep(delay)
		}
	}

	return nil
}
