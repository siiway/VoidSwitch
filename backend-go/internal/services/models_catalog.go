package services

import (
	"sort"
	"strings"
	"time"

	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"

	"gorm.io/gorm"
)

func servedModelIDs(providers []database.Provider) map[string]bool {
	ids := make(map[string]bool)
	for _, p := range providers {
		hidden := RoutedUpstreams(&p)
		for _, name := range p.Models {
			if name == "" || name == "*" || hidden[name] {
				continue
			}
			ids[name] = true
		}
		for _, route := range p.ModelRoutes {
			r, ok := route.(map[string]interface{})
			if !ok {
				continue
			}
			alias, _ := r["alias"].(string)
			if alias != "" {
				ids[alias] = true
			}
		}
	}
	return ids
}

func hiddenUpstreams(providers []database.Provider) map[string]bool {
	served := servedModelIDs(providers)
	hidden := make(map[string]bool)
	for _, p := range providers {
		for upstream := range RoutedUpstreams(&p) {
			if !served[upstream] {
				hidden[upstream] = true
			}
		}
	}
	return hidden
}

func providersServing(providers []database.Provider, modelID string) []string {
	var names []string
	for _, p := range providers {
		if ProviderServesModel(&p, modelID) {
			names = append(names, p.Name)
		}
	}
	return names
}

func BuildCatalog(db *gorm.DB) ([]models.ModelOut, error) {
	var providers []database.Provider
	if err := db.Where("enabled = ?", true).Find(&providers).Error; err != nil {
		return nil, err
	}

	var entries []database.ModelEntry
	if err := db.Find(&entries).Error; err != nil {
		return nil, err
	}

	entryMap := make(map[string]*database.ModelEntry, len(entries))
	for i := range entries {
		entryMap[entries[i].ModelID] = &entries[i]
	}

	served := servedModelIDs(providers)
	hidden := hiddenUpstreams(providers)

	allIDs := make(map[string]bool)
	for id := range served {
		allIDs[id] = true
	}
	for id := range entryMap {
		if !hidden[id] {
			allIDs[id] = true
		}
	}

	var result []models.ModelOut
	for modelID := range allIDs {
		entry := entryMap[modelID]
		provNames := providersServing(providers, modelID)

		if entry != nil && !entry.Enabled {
			continue
		}
		if entry == nil && len(provNames) == 0 {
			continue
		}

		var publicID string = modelID
		var mappedID *string
		var displayName *string
		var desc *string
		var opencodeConfig map[string]any
		var idPtr *int
		var addedByName *string
		var createdAt *time.Time
		var updatedAt *time.Time

		if entry != nil {
			if entry.MappedID != nil && *entry.MappedID != "" {
				mappedID = entry.MappedID
				publicID = *entry.MappedID
			}
			displayName = entry.DisplayName
			desc = entry.Description
			opencodeConfig = entry.OpenCodeConfig
			idPtr = &entry.ID
			addedByName = entry.AddedByName
			createdAt = &entry.CreatedAt
			updatedAt = &entry.UpdatedAt
		}

		result = append(result, models.ModelOut{
			ID:             idPtr,
			ModelID:        modelID,
			MappedID:       mappedID,
			PublicID:       publicID,
			DisplayName:    displayName,
			Description:    desc,
			OpenCodeConfig: opencodeConfig,
			Enabled:        entry == nil || entry.Enabled,
			Providers:      provNames,
			Served:         len(provNames) > 0,
			Registered:     entry != nil,
			AddedByName:    addedByName,
			CreatedAt:      createdAt,
			UpdatedAt:      updatedAt,
		})
	}

	sort.Slice(result, func(i, j int) bool {
		return strings.ToLower(result[i].ModelID) < strings.ToLower(result[j].ModelID)
	})

	return result, nil
}

func SyncCatalog(db *gorm.DB, actorID *int, actorName *string) (*models.ModelSyncResult, error) {
	var providers []database.Provider
	if err := db.Where("enabled = ?", true).Find(&providers).Error; err != nil {
		return nil, err
	}

	served := servedModelIDs(providers)

	var entries []database.ModelEntry
	if err := db.Find(&entries).Error; err != nil {
		return nil, err
	}

	existing := make(map[string]bool, len(entries))
	for _, e := range entries {
		existing[e.ModelID] = true
	}

	var missing []string
	for id := range served {
		if !existing[id] {
			missing = append(missing, id)
		}
	}
	sort.Strings(missing)

	for _, modelID := range missing {
		entry := database.ModelEntry{
			ModelID:     modelID,
			AddedBy:     actorID,
			AddedByName: actorName,
		}
		if err := db.Create(&entry).Error; err != nil {
			return nil, err
		}
	}

	return &models.ModelSyncResult{
		Added: len(missing),
		Total: len(existing) + len(missing),
	}, nil
}

func UpsertModel(db *gorm.DB, req models.ModelUpsert, actorID *int, actorName *string) (*database.ModelEntry, error) {
	var entry database.ModelEntry
	result := db.Where("model_id = ?", req.ModelID).First(&entry)

	if result.Error != nil {
		if result.Error == gorm.ErrRecordNotFound {
			entry = database.ModelEntry{
				ModelID:     req.ModelID,
				AddedBy:     actorID,
				AddedByName: actorName,
				Enabled:     true,
			}
			applyUpsertFields(&entry, req)
			if err := db.Create(&entry).Error; err != nil {
				return nil, err
			}
			return &entry, nil
		}
		return nil, result.Error
	}

	applyUpsertFields(&entry, req)

	updates := make(map[string]interface{})
	if req.MappedID != nil {
		if *req.MappedID == "" {
			updates["mapped_id"] = nil
		} else {
			updates["mapped_id"] = *req.MappedID
		}
	}
	if req.DisplayName != nil {
		if *req.DisplayName == "" {
			updates["display_name"] = nil
		} else {
			updates["display_name"] = *req.DisplayName
		}
	}
	if req.Description != nil {
		updates["description"] = *req.Description
	}
	if req.OpenCodeConfig != nil {
		updates["opencode_config"] = *req.OpenCodeConfig
	}
	if req.Enabled != nil {
		updates["enabled"] = *req.Enabled
	}

	if len(updates) > 0 {
		if err := db.Model(&entry).Updates(updates).Error; err != nil {
			return nil, err
		}
	}

	if err := db.Where("model_id = ?", req.ModelID).First(&entry).Error; err != nil {
		return nil, err
	}
	return &entry, nil
}

func applyUpsertFields(entry *database.ModelEntry, req models.ModelUpsert) {
	if req.MappedID != nil {
		if *req.MappedID == "" {
			entry.MappedID = nil
		} else {
			entry.MappedID = req.MappedID
		}
	}
	if req.DisplayName != nil {
		if *req.DisplayName == "" {
			entry.DisplayName = nil
		} else {
			entry.DisplayName = req.DisplayName
		}
	}
	if req.Description != nil {
		entry.Description = req.Description
	}
	if req.OpenCodeConfig != nil {
		entry.OpenCodeConfig = *req.OpenCodeConfig
	}
	if req.Enabled != nil {
		entry.Enabled = *req.Enabled
	}
}

func DeleteModel(db *gorm.DB, id int) error {
	return db.Delete(&database.ModelEntry{}, id).Error
}

func CleanUnserved(db *gorm.DB) (*models.ModelCleanResult, error) {
	var providers []database.Provider
	if err := db.Where("enabled = ?", true).Find(&providers).Error; err != nil {
		return nil, err
	}
	served := servedModelIDs(providers)

	var entries []database.ModelEntry
	if err := db.Find(&entries).Error; err != nil {
		return nil, err
	}

	var toDelete []string
	for _, e := range entries {
		if !served[e.ModelID] {
			toDelete = append(toDelete, e.ModelID)
		}
	}
	sort.Strings(toDelete)

	if len(toDelete) > 0 {
		for _, modelID := range toDelete {
			db.Where("model_id = ?", modelID).Delete(&database.ModelEntry{})
		}
	}

	return &models.ModelCleanResult{
		Deleted:  len(toDelete),
		ModelIDs: toDelete,
	}, nil
}
