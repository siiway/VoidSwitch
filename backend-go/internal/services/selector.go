package services

import (
	"path/filepath"
	"sort"
	"time"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"

	"gorm.io/gorm"
)

var epoch = time.Date(1970, 1, 1, 0, 0, 0, 0, time.UTC)

type ModelRoute struct {
	Alias    string
	Upstream string
	Pool     string
}

type RouteInfo struct {
	Route Route
	Proxy *database.Proxy
}

func lruTime(lastUsed *time.Time) time.Time {
	if lastUsed == nil {
		return epoch
	}
	return *lastUsed
}

// ---- model routing ----

func MatchModelRoute(provider *database.Provider, model string) *ModelRoute {
	for _, route := range provider.ModelRoutes {
		r, ok := route.(map[string]interface{})
		if !ok {
			continue
		}
		alias, _ := r["alias"].(string)
		if alias == model {
			upstream, _ := r["upstream"].(string)
			pool, _ := r["pool"].(string)
			return &ModelRoute{Alias: alias, Upstream: upstream, Pool: pool}
		}
	}
	return nil
}

func RoutedUpstreams(provider *database.Provider) map[string]bool {
	ups := make(map[string]bool)
	for _, route := range provider.ModelRoutes {
		r, ok := route.(map[string]interface{})
		if !ok {
			continue
		}
		upstream, _ := r["upstream"].(string)
		if upstream != "" {
			ups[upstream] = true
		}
	}
	return ups
}

func ProviderServesModel(provider *database.Provider, model string) bool {
	if MatchModelRoute(provider, model) != nil {
		return true
	}
	if RoutedUpstreams(provider)[model] {
		return false
	}
	for _, pattern := range provider.Models {
		if pattern == "*" || pattern == model {
			return true
		}
		if matched, _ := filepath.Match(pattern, model); matched {
			return true
		}
	}
	return false
}

func ResolveModel(provider *database.Provider, model string) (upstreamModel string, keyPool string) {
	route := MatchModelRoute(provider, model)
	if route != nil {
		if route.Upstream != "" {
			upstreamModel = route.Upstream
		} else {
			upstreamModel = model
		}
		return upstreamModel, route.Pool
	}
	if provider.ModelMap != nil {
		if mapped, ok := provider.ModelMap[model]; ok {
			if s, ok := mapped.(string); ok {
				return s, ""
			}
		}
	}
	return model, ""
}

// ---- provider selection ----

func SelectProviders(db *gorm.DB, model string) ([]database.Provider, error) {
	var providers []database.Provider
	if err := db.Where("enabled = ?", true).Find(&providers).Error; err != nil {
		return nil, err
	}

	var matched []database.Provider
	for i := range providers {
		if ProviderServesModel(&providers[i], model) {
			matched = append(matched, providers[i])
		}
	}

	sort.Slice(matched, func(i, j int) bool {
		if matched[i].Priority != matched[j].Priority {
			return matched[i].Priority < matched[j].Priority
		}
		if matched[i].Weight != matched[j].Weight {
			return matched[i].Weight > matched[j].Weight
		}
		return matched[i].ID < matched[j].ID
	})

	return matched, nil
}

// ---- key selection ----

func SelectKeys(keys []*database.ApiKey, pool string, rateLimitRecoverySeconds int) []*database.ApiKey {
	now := time.Now().UTC()
	candidates := make([]*database.ApiKey, 0)
	for _, k := range keys {
		if k.Status == string(constants.KeyStatusActive) {
			if pool == "" || k.Pool == pool {
				candidates = append(candidates, k)
			}
		} else if k.Status == string(constants.KeyStatusRateLimited) && rateLimitRecoverySeconds > 0 && k.DisabledSince != nil {
			ds := *k.DisabledSince
			elapsed := now.Sub(ds).Seconds()
			if elapsed >= float64(rateLimitRecoverySeconds) {
				if pool == "" || k.Pool == pool {
					candidates = append(candidates, k)
				}
			}
		}
	}

	sort.Slice(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if a.FailedCount != b.FailedCount {
			return a.FailedCount < b.FailedCount
		}
		aw := float64(a.TotalRequests) / float64(max(a.Weight, 1))
		bw := float64(b.TotalRequests) / float64(max(b.Weight, 1))
		if aw != bw {
			return aw < bw
		}
		return lruTime(a.LastUsedAt).Before(lruTime(b.LastUsedAt))
	})

	return candidates
}

// ---- proxy selection ----

func ActiveProxies(db *gorm.DB) ([]*database.Proxy, error) {
	var proxies []*database.Proxy
	if err := db.Where("enabled = ? AND status = ?", true, string(constants.ProxyStatusActive)).Find(&proxies).Error; err != nil {
		return nil, err
	}
	return proxies, nil
}

func RoutesForProvider(provider *database.Provider, proxies []*database.Proxy) []RouteInfo {
	mode := provider.ProxyMode
	if mode == "" {
		mode = string(constants.ProxyModeAll)
	}

	if mode == string(constants.ProxyModeDirect) {
		return []RouteInfo{{Route: NewRoute(nil, nil), Proxy: nil}}
	}

	if mode == string(constants.ProxyModeSelected) {
		ids := proxyIDSet(provider.ProxyIDs)
		filtered := make([]*database.Proxy, 0)
		for _, p := range proxies {
			if ids[p.ID] {
				filtered = append(filtered, p)
			}
		}
		return orderedRoutes(filtered)
	}

	// "all" mode
	if len(proxies) == 0 {
		return []RouteInfo{{Route: NewRoute(nil, nil), Proxy: nil}}
	}
	return orderedRoutes(proxies)
}

func SelectRoutes(db *gorm.DB, provider *database.Provider) ([]RouteInfo, error) {
	proxies, err := ActiveProxies(db)
	if err != nil {
		return nil, err
	}
	return RoutesForProvider(provider, proxies), nil
}

// ---- helpers ----

func proxyIDSet(proxyIDs []any) map[int]bool {
	ids := make(map[int]bool)
	for _, v := range proxyIDs {
		switch n := v.(type) {
		case float64:
			ids[int(n)] = true
		case int:
			ids[n] = true
		case int64:
			ids[int(n)] = true
		}
	}
	return ids
}

func orderedRoutes(proxies []*database.Proxy) []RouteInfo {
	sorted := make([]*database.Proxy, len(proxies))
	copy(sorted, proxies)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].FailedCount != sorted[j].FailedCount {
			return sorted[i].FailedCount < sorted[j].FailedCount
		}
		return lruTime(sorted[i].LastUsedAt).Before(lruTime(sorted[j].LastUsedAt))
	})

	routes := make([]RouteInfo, len(sorted))
	for i, p := range sorted {
		routes[i] = RouteInfo{
			Route: NewRoute(&p.URL, p.LocalAddress),
			Proxy: p,
		}
	}
	return routes
}
