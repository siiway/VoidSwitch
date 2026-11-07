package services

import (
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services/providers"
)

// ResolveAdapter returns the provider adapter for a provider record.
func ResolveAdapter(p *database.Provider) providers.ProviderInterface {
	return providers.GetAdapter(p)
}
