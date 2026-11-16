package services

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

const modelsDevRegistryURL = "https://models.dev/api.json"

// modelsDevEntry is one cached registry row: a provider id plus its raw JSON.
type modelsDevEntry struct {
	ID   string
	Data map[string]any
}

// SyncModelsDev pulls https://models.dev/api.json and upserts the local cache.
// Returns the number of registry entries (providers).
func SyncModelsDev(ctx context.Context, db *gorm.DB) (int, error) {
	client := &http.Client{Timeout: 30 * time.Second}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, modelsDevRegistryURL, nil)
	if err != nil {
		return 0, err
	}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("models_dev fetch failed", "err", err)
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, nil
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return 0, err
	}
	var registry map[string]json.RawMessage
	if err := json.Unmarshal(body, &registry); err != nil {
		return 0, err
	}
	now := time.Now().UTC()
	for id, raw := range registry {
		var probe map[string]any
		if json.Unmarshal(raw, &probe) != nil {
			continue
		}
		row := database.ModelsDevCache{ID: id, Data: database.JSON(raw), UpdatedAt: now}
		db.Where("id = ?", id).Assign(database.ModelsDevCache{Data: row.Data, UpdatedAt: now}).FirstOrCreate(&row)
	}
	return len(registry), nil
}

// ModelsDevEntry returns a cached registry entry's raw JSON.
func ModelsDevEntry(db *gorm.DB, id string) (database.JSON, bool) {
	var row database.ModelsDevCache
	if err := db.Where("id = ?", id).First(&row).Error; err != nil {
		return nil, false
	}
	return row.Data, true
}

// loadModelsDevRows reads the whole cache once per search. The registry is a few
// hundred provider blobs, so scanning them in memory keeps search off the
// network and out of the query planner.
func loadModelsDevRows(db *gorm.DB) []modelsDevEntry {
	var rows []database.ModelsDevCache
	db.Find(&rows)
	out := make([]modelsDevEntry, 0, len(rows))
	for _, r := range rows {
		var data map[string]any
		database.DecodeJSON(r.Data, &data)
		if data == nil {
			continue
		}
		out = append(out, modelsDevEntry{ID: r.ID, Data: data})
	}
	return out
}

// flattenModelsDev expands cached provider blobs into (provider, model) pairs.
// The registry maps a provider id → a provider object whose `models` map holds
// the individual model entries; the stable registry id of a model is
// "provider/model", which is what gets stored as an exposed model's
// models_dev_id. Each entry is augmented with its provider id and display name
// so the dashboard can pick a brand icon.
func flattenModelsDev(rows []modelsDevEntry) []map[string]any {
	out := []map[string]any{}
	for _, row := range rows {
		models, ok := row.Data["models"].(map[string]any)
		if !ok {
			continue
		}
		providerName, _ := row.Data["name"].(string)
		if providerName == "" {
			providerName = row.ID
		}
		for mid, raw := range models {
			model, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			entry := make(map[string]any, len(model)+2)
			for k, v := range model {
				entry[k] = v
			}
			if _, exists := entry["id"]; !exists {
				entry["id"] = mid
			}
			entry["provider"] = row.ID
			entry["provider_name"] = providerName
			out = append(out, entry)
		}
	}
	return out
}

// modelsDevOfficial reports whether a model id is the provider's own listing.
// Official listings have the model id start with the provider id
// ("deepseek/deepseek-v4-pro"); third-party aggregators namespace it further
// ("openrouter/deepseek/deepseek-v4-pro").
func modelsDevOfficial(provider, mid string) bool {
	return provider != "" && strings.HasPrefix(mid, provider)
}

// modelsDevScore is a tiered relevance score: whole-string matches outrank
// prefixes, which outrank substrings, which outrank provider/family hits. 0
// means "no match". A provider's own listing outranks third-party aggregates of
// the same model, so searching "deepseek-v4-pro" leads with
// "deepseek/deepseek-v4-pro".
func modelsDevScore(q, fullID, mid, name, provider, family string) int {
	switch {
	case fullID == q:
		return 100
	case mid == q:
		if modelsDevOfficial(provider, mid) {
			return 90
		}
		return 80
	case name == q:
		return 70
	case strings.HasPrefix(fullID, q):
		return 60
	case strings.HasPrefix(mid, q) || strings.HasPrefix(name, q):
		return 50
	}
	switch {
	case strings.Contains(mid, q):
		return 40
	case strings.Contains(name, q):
		return 30
	case provider != "" && strings.Contains(provider, q):
		return 20
	case family != "" && strings.Contains(family, q):
		return 10
	}
	return 0
}

// SearchModelsDev runs relevance search against the cached registry, reading it
// once per call. See searchModelsDevEntries for the matching rules.
func SearchModelsDev(db *gorm.DB, query string, limit int) []map[string]any {
	return searchModelsDevEntries(loadModelsDevRows(db), query, limit)
}

// searchModelsDevEntries runs relevance search over the flattened model entries
// — not over provider ids. A query may match the model id, its display name,
// the "provider/model" id, the provider id or the family. Results are ordered by
// score, then by shorter full id (official ids are the short ones), then
// alphabetically.
func searchModelsDevEntries(rows []modelsDevEntry, query string, limit int) []map[string]any {
	q := strings.ToLower(strings.TrimSpace(query))
	if q == "" {
		return []map[string]any{}
	}
	if limit <= 0 {
		limit = 50
	}
	type match struct {
		score  int
		length int
		fullID string
		entry  map[string]any
	}
	matches := []match{}
	for _, entry := range flattenModelsDev(rows) {
		str := func(key string) string {
			s, _ := entry[key].(string)
			return strings.ToLower(s)
		}
		mid, provider := str("id"), str("provider")
		fullID := mid
		if provider != "" {
			fullID = provider + "/" + mid
		}
		score := modelsDevScore(q, fullID, mid, str("name"), provider, str("family"))
		if score == 0 {
			continue
		}
		matches = append(matches, match{score: score, length: len(fullID), fullID: fullID, entry: entry})
	}
	sort.SliceStable(matches, func(i, j int) bool {
		if matches[i].score != matches[j].score {
			return matches[i].score > matches[j].score
		}
		if matches[i].length != matches[j].length {
			return matches[i].length < matches[j].length
		}
		return matches[i].fullID < matches[j].fullID
	})
	out := make([]map[string]any, 0, limit)
	for _, m := range matches {
		if len(out) == limit {
			break
		}
		out = append(out, m.entry)
	}
	return out
}
