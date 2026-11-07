package services

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

const modelsDevRegistryURL = "https://models.dev/api.json"

// SyncModelsDev pulls https://models.dev/api.json and upserts the local cache.
// Returns the number of registry entries.
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
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
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
