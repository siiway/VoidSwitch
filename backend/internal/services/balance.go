package services

import (
	"context"
	"net/http"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services/providers"
)

// ApplyBalance records a balance reading on a key and, when enabled, auto-
// disables empty keys / re-enables recovered ones (mirrors Python apply_balance).
func ApplyBalance(db *gorm.DB, key *database.ApiKey, available bool, detail map[string]any, autoDisable bool) {
	now := time.Now().UTC()
	updates := map[string]any{
		"balance":         database.JSONOf(detail),
		"last_checked_at": now,
	}
	if available {
		if key.Status == string(constants.KeyStatusInsufficientBalance) {
			updates["status"] = string(constants.KeyStatusActive)
			updates["failed_count"] = 0
			updates["disabled_reason"] = nil
			updates["disabled_since"] = nil
		}
		db.Model(&database.ApiKey{}).Where("id = ?", key.ID).Updates(updates)
		return
	}
	if !autoDisable || key.Status == string(constants.KeyStatusDisabled) {
		db.Model(&database.ApiKey{}).Where("id = ?", key.ID).Updates(updates)
		return
	}
	if errStr, _ := detail["error"].(string); errStr == "authentication_error" {
		updates["status"] = string(constants.KeyStatusInvalid)
		updates["disabled_reason"] = "balance probe: authentication failed"
	} else {
		updates["status"] = string(constants.KeyStatusInsufficientBalance)
		updates["disabled_reason"] = "balance probe: insufficient balance"
	}
	if key.DisabledSince == nil {
		updates["disabled_since"] = now
	}
	db.Model(&database.ApiKey{}).Where("id = ?", key.ID).Updates(updates)
}

// RefreshKeyBalance fetches and applies one key's balance. Returns nil when the
// provider has no balance endpoint or the read cannot be parsed.
func RefreshKeyBalance(db *gorm.DB, key *database.ApiKey, provider *database.Provider, secretKey string, autoDisable bool) *bool {
	adapter := providers.GetAdapter(provider)
	if adapter.GetBalanceURL() == "" {
		return nil
	}
	plain, err := cryptoutil.DecryptSecret(key.KeyCiphertext, secretKey)
	if err != nil {
		return nil
	}
	client := &http.Client{Timeout: 30 * time.Second}
	res, err := adapter.FetchBalance(client, plain)
	if err != nil || res == nil {
		return nil
	}
	ApplyBalance(db, key, res.Available, res.Detail, autoDisable)
	available := res.Available
	return &available
}

// RunBalanceProbe checks the balance of every active key on a balance-capable
// provider and fast-fails the ones that report empty.
func RunBalanceProbe(ctx context.Context, db *gorm.DB, secretKey string) {
	autoDisable := GetBool("auto_disable_zero_balance", true)
	var providersList []database.Provider
	db.Where("enabled = ?", true).Find(&providersList)
	for i := range providersList {
		p := &providersList[i]
		adapter := providers.GetAdapter(p)
		if adapter.GetBalanceURL() == "" {
			continue
		}
		var keys []database.ApiKey
		db.Where("provider_id = ? AND status = ?", p.ID, string(constants.KeyStatusActive)).Find(&keys)
		for j := range keys {
			if ctx.Err() != nil {
				return
			}
			RefreshKeyBalance(db, &keys[j], p, secretKey, autoDisable)
		}
	}
}

// RunBalanceRescan re-checks keys disabled for insufficient balance and
// re-enables any that have been topped up.
func RunBalanceRescan(ctx context.Context, db *gorm.DB, secretKey string) {
	autoDisable := GetBool("auto_disable_zero_balance", true)
	var keys []database.ApiKey
	db.Where("status = ?", string(constants.KeyStatusInsufficientBalance)).Find(&keys)
	for i := range keys {
		if ctx.Err() != nil {
			return
		}
		k := &keys[i]
		var p database.Provider
		if err := db.First(&p, k.ProviderID).Error; err != nil {
			continue
		}
		RefreshKeyBalance(db, k, &p, secretKey, autoDisable)
	}
}
