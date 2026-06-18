package services

import (
	"net/http"
	"time"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services/providers"
)

func ApplyBalance(key *database.ApiKey, isAvailable bool, detail map[string]any, autoDisable bool) {
	now := time.Now()
	key.Balance = detail
	key.LastCheckedAt = &now

	if isAvailable {
		if key.Status == string(constants.KeyStatusInsufficientBalance) {
			key.Status = string(constants.KeyStatusActive)
			key.FailedCount = 0
			key.DisabledReason = nil
			key.DisabledSince = nil
		}
		return
	}

	if !autoDisable {
		return
	}

	authError := false
	if detail != nil {
		if errStr, ok := detail["error"].(string); ok && errStr == "authentication_error" {
			authError = true
		}
	}

	reason := "balance probe: insufficient balance"
	if authError {
		key.Status = string(constants.KeyStatusInvalid)
		reason = "balance probe: authentication failed"
	} else {
		key.Status = string(constants.KeyStatusInsufficientBalance)
	}

	key.DisabledReason = &reason
	if key.DisabledSince == nil {
		key.DisabledSince = &now
	}
}

func RefreshKeyBalance(
	key *database.ApiKey,
	provider *database.Provider,
	client *http.Client,
	settings *config.Settings,
	autoDisable bool,
	adapter providers.ProviderInterface,
) (bool, error) {
	if adapter.GetBalanceURL() == "" {
		return false, nil
	}

	plaintext, _ := core.DecryptSecret(key.KeyCiphertext, settings.Server.SecretKey)
	result, err := adapter.FetchBalance(client, plaintext)
	if err != nil {
		return false, err
	}
	if result == nil {
		return false, nil
	}

	ApplyBalance(key, result.Available, result.Detail, autoDisable)
	return result.Available, nil
}
