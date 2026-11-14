package services

import (
	"context"
	"encoding/json"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/redisx"
)

// Renamed/removed setting keys, carried forward on boot (mirrors Python).
var renamedKeys = map[string]string{
	"log_stream_max_connections": "sse_max_connections_per_user",
	"max_retries":                "max_provider_attempts",
}

var removedKeys = map[string]bool{
	"proxy_health_check_enabled":          true,
	"proxy_probe_url":                     true,
	"operation_rate_limit_window_seconds": true,
	"operation_rate_limit_max_requests":   true,
	"call_rate_limit_window_seconds":      true,
	"call_rate_limit_max_requests":        true,
}

var (
	settingsCache  = map[string]any{}
	settingsMu     sync.RWMutex
	settingsLoaded bool
	settingsRedis  *redisx.Service
	settingsCancel context.CancelFunc
)

// SetSettingsRedis wires the Redis service used for settings propagation.
func SetSettingsRedis(r *redisx.Service) { settingsRedis = r }

// EnsureSettingsDefaults seeds missing settings rows (idempotent) at boot.
func EnsureSettingsDefaults(db *gorm.DB) error {
	var rows []database.Setting
	if err := db.Find(&rows).Error; err != nil {
		return err
	}
	byKey := make(map[string]database.Setting, len(rows))
	for _, r := range rows {
		byKey[r.Key] = r
	}

	for oldKey, newKey := range renamedKeys {
		if old, ok := byKey[oldKey]; ok {
			if _, exists := byKey[newKey]; !exists {
				if err := db.Create(&database.Setting{Key: newKey, Value: old.Value, UpdatedAt: time.Now().UTC()}).Error; err != nil {
					return err
				}
				byKey[newKey] = old
			}
			if err := db.Delete(&database.Setting{}, "key = ?", oldKey).Error; err != nil {
				return err
			}
			delete(byKey, oldKey)
		}
	}
	for k := range removedKeys {
		if _, ok := byKey[k]; ok {
			if err := db.Delete(&database.Setting{}, "key = ?", k).Error; err != nil {
				return err
			}
			delete(byKey, k)
		}
	}
	for key, raw := range constants.DefaultSettingsJSON {
		if _, ok := byKey[key]; !ok {
			if err := db.Create(&database.Setting{Key: key, Value: database.JSON(raw), UpdatedAt: time.Now().UTC()}).Error; err != nil {
				return err
			}
		}
	}
	return nil
}

// LoadSettings loads all settings into the in-process cache.
func LoadSettings(db *gorm.DB) (map[string]any, error) {
	var rows []database.Setting
	if err := db.Find(&rows).Error; err != nil {
		return nil, err
	}
	merged := constants.DefaultSettings()
	for _, r := range rows {
		if removedKeys[r.Key] {
			continue
		}
		var v any
		if err := json.Unmarshal(r.Value, &v); err == nil {
			merged[r.Key] = v
		}
	}
	settingsMu.Lock()
	settingsCache = merged
	settingsLoaded = true
	settingsMu.Unlock()
	return merged, nil
}

// GetSetting returns a cached setting value (zero if absent).
func GetSetting(key string) any {
	settingsMu.RLock()
	defer settingsMu.RUnlock()
	return settingsCache[key]
}

func GetString(key, def string) string {
	v := GetSetting(key)
	if v == nil {
		return def
	}
	if s, ok := v.(string); ok {
		return s
	}
	return def
}

func GetInt(key string, def int) int {
	v := GetSetting(key)
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case json.Number:
		if i, err := n.Int64(); err == nil {
			return int(i)
		}
	case string:
		if i, err := strconv.Atoi(strings.TrimSpace(n)); err == nil {
			return i
		}
	}
	return def
}

func GetBool(key string, def bool) bool {
	v := GetSetting(key)
	if b, ok := v.(bool); ok {
		return b
	}
	return def
}

func GetStringSlice(key string) []string {
	v := GetSetting(key)
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(arr))
	for _, x := range arr {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func GetIntSlice(key string) []int {
	v := GetSetting(key)
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]int, 0, len(arr))
	for _, x := range arr {
		if f, ok := x.(float64); ok {
			out = append(out, int(f))
		}
	}
	return out
}

// UpdateSettings persists the provided values (full replace of those keys),
// then publishes a snapshot to other workers.
func UpdateSettings(db *gorm.DB, values map[string]any) (map[string]any, error) {
	for k, v := range values {
		raw, err := json.Marshal(v)
		if err != nil {
			return nil, err
		}
		var row database.Setting
		err = db.Where("key = ?", k).First(&row).Error
		if err == gorm.ErrRecordNotFound {
			row = database.Setting{Key: k, Value: database.JSON(raw), UpdatedAt: time.Now().UTC()}
			if err := db.Create(&row).Error; err != nil {
				return nil, err
			}
			continue
		} else if err != nil {
			return nil, err
		}
		if err := db.Model(&row).Updates(map[string]any{"value": raw, "updated_at": time.Now().UTC()}).Error; err != nil {
			return nil, err
		}
	}
	merged, err := LoadSettings(db)
	if err != nil {
		return nil, err
	}
	PublishSettings(context.Background(), merged)
	return merged, nil
}

// PublishSettings writes the snapshot + bump + pubsub notify.
func PublishSettings(ctx context.Context, values map[string]any) {
	if settingsRedis == nil {
		return
	}
	payload, err := json.Marshal(values)
	if err != nil {
		return
	}
	c := settingsRedis.Client()
	pipe := c.Pipeline()
	pipe.Set(ctx, settingsRedis.Key("settings", "snapshot"), payload, 0)
	pipe.Incr(ctx, settingsRedis.Key("settings", "version"))
	_, _ = pipe.Exec(ctx)
	_ = c.Publish(ctx, settingsRedis.Key("settings", "changed"), "reload").Err()
}

// StartSettingsListener subscribes to the settings channel across workers.
func StartSettingsListener(db *gorm.DB) {
	if settingsRedis == nil {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	settingsCancel = cancel
	pubsub := settingsRedis.Client().Subscribe(ctx, settingsRedis.Key("settings", "changed"))
	go func() {
		ch := pubsub.Channel()
		for range ch {
			if _, err := LoadSettings(db); err != nil {
				slog.Warn("settings reload failed", "err", err)
			}
		}
	}()
}

func StopSettingsListener() {
	if settingsCancel != nil {
		settingsCancel()
	}
}

// GetFloat returns a numeric setting as float64.
func GetFloat(key string, def float64) float64 {
	switch v := GetSetting(key).(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case json.Number:
		if f, err := v.Float64(); err == nil {
			return f
		}
	}
	return def
}
