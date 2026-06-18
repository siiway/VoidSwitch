package services

import (
	"strconv"
	"strings"
	"sync"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

var cache map[string]any
var cacheLoaded bool
var mu sync.RWMutex

func EnsureDefaults(db *gorm.DB) error {
	var existingKeys []string
	if err := db.Model(&database.Setting{}).Pluck("key", &existingKeys).Error; err != nil {
		return err
	}
	existingSet := make(map[string]bool, len(existingKeys))
	for _, k := range existingKeys {
		existingSet[k] = true
	}
	for key, value := range constants.DefaultSettings {
		if !existingSet[key] {
			if err := db.Create(&database.Setting{Key: key, Value: value}).Error; err != nil {
				return err
			}
		}
	}
	return nil
}

func LoadAll(db *gorm.DB) (map[string]any, error) {
	var rows []database.Setting
	if err := db.Find(&rows).Error; err != nil {
		return nil, err
	}
	merged := make(map[string]any, len(constants.DefaultSettings)+len(rows))
	for k, v := range constants.DefaultSettings {
		merged[k] = v
	}
	for _, row := range rows {
		merged[row.Key] = row.Value
	}

	mu.Lock()
	cache = make(map[string]any, len(merged))
	for k, v := range merged {
		cache[k] = v
	}
	cacheLoaded = true
	mu.Unlock()

	return merged, nil
}

func GetAll(db *gorm.DB) (map[string]any, error) {
	mu.RLock()
	if cacheLoaded {
		result := make(map[string]any, len(cache))
		for k, v := range cache {
			result[k] = v
		}
		mu.RUnlock()
		return result, nil
	}
	mu.RUnlock()
	return LoadAll(db)
}

func GetCached(key string, defaultVal any) any {
	mu.RLock()
	if v, ok := cache[key]; ok {
		mu.RUnlock()
		return v
	}
	mu.RUnlock()
	if v, ok := constants.DefaultSettings[key]; ok {
		return v
	}
	return defaultVal
}

func GetInt(key string, defaultVal int) int {
	value := GetCached(key, defaultVal)
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case string:
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	case bool:
		if v {
			return 1
		}
		return 0
	}
	return defaultVal
}

func GetStr(key string, defaultVal string) string {
	value := GetCached(key, defaultVal)
	if s, ok := value.(string); ok {
		return s
	}
	if value != nil {
		return strings.TrimSpace(strconv.FormatFloat(float64(toFloat(value)), 'f', -1, 64))
	}
	return defaultVal
}

func toFloat(v any) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case int:
		return float64(val)
	case int64:
		return float64(val)
	case string:
		if n, err := strconv.ParseFloat(val, 64); err == nil {
			return n
		}
	}
	return 0
}

func GetBool(key string, defaultVal bool) bool {
	value := GetCached(key, defaultVal)
	switch v := value.(type) {
	case bool:
		return v
	case string:
		lower := strings.ToLower(strings.TrimSpace(v))
		return lower == "1" || lower == "true" || lower == "yes" || lower == "on"
	case int:
		return v != 0
	case int64:
		return v != 0
	case float64:
		return v != 0
	}
	return defaultVal
}

func Update(db *gorm.DB, values map[string]any) (map[string]any, error) {
	for key, value := range values {
		var existing database.Setting
		if err := db.Where("key = ?", key).First(&existing).Error; err != nil {
			if err := db.Create(&database.Setting{Key: key, Value: value}).Error; err != nil {
				return nil, err
			}
		} else {
			existing.Value = value
			if err := db.Save(&existing).Error; err != nil {
				return nil, err
			}
		}
	}
	return LoadAll(db)
}
