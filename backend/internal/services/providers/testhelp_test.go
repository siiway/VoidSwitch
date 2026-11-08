package providers

import "github.com/siiway/voidswitch/internal/database"

func newProviderForTest(typ string) *database.Provider {
	return &database.Provider{Type: typ, Models: database.JSONOf([]string{}), ExtraHeaders: database.JSONOf(map[string]any{}), ModelMap: database.JSONOf(map[string]any{})}
}
