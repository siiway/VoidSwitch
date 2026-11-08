package services

import (
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services/providers"
)

// ResolveAdapter returns the provider adapter for a provider record.
func ResolveAdapter(p *database.Provider) providers.ProviderInterface {
	return providers.GetAdapter(p)
}

// ResolveCredential returns the usable upstream secret for a key: an OAuth
// access token for subscription providers (codex / grok-build / xai bundles),
// or the decrypted static key otherwise.
func ResolveCredential(db *gorm.DB, provider *database.Provider, key *database.ApiKey, secretKey string) (string, error) {
	switch provider.Type {
	case "codex":
		return CodexResolveAccessToken(db, key, secretKey, false)
	case "grok-build", "xai":
		return XAIResolveAccessToken(db, key, secretKey, false)
	default:
		return cryptoutil.DecryptSecret(key.KeyCiphertext, secretKey)
	}
}
