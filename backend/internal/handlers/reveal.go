package handlers

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// revealKeySearch lets an owner search where a given secret appears: as an
// upstream provider key (decryptable) or a Void-Token (hash-only; matched by
// exact value or a prefix pattern like "vs-abc…" / "vs-abc*").
func (a *App) revealKeySearch(c *gin.Context) {
	var in struct {
		Key   string `json:"key"`
		Scope string `json:"scope"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	raw := strings.TrimSpace(in.Key)
	scope := strings.ToLower(strings.TrimSpace(in.Scope))
	if raw == "" {
		a.fail(c, http.StatusBadRequest, "Key is required.")
		return
	}
	if scope != "provider" && scope != "token" && scope != "all" {
		a.fail(c, http.StatusBadRequest, "Invalid reveal scope.")
		return
	}

	providerMatches := []gin.H{}
	tokenMatches := []gin.H{}

	if scope == "provider" || scope == "all" {
		var keys []database.ApiKey
		a.GDB.Order("provider_id, sort_order, id").Find(&keys)
		var providers []database.Provider
		a.GDB.Find(&providers)
		pname := map[int]string{}
		for _, p := range providers {
			pname[p.ID] = p.Name
		}
		pos := map[int]int{}
		for i := range keys {
			k := &keys[i]
			pos[k.ProviderID]++
			plain, err := cryptoutil.DecryptSecret(k.KeyCiphertext, a.Cfg.Server.SecretKey)
			if err != nil {
				continue
			}
			if strings.Contains(plain, raw) {
				providerMatches = append(providerMatches, gin.H{
					"provider_id": k.ProviderID, "provider_name": pname[k.ProviderID],
					"key_id": k.ID, "position": pos[k.ProviderID], "preview": k.KeyPreview,
					"comment": k.Note, "pool": k.Pool, "added_by_name": k.AddedByName,
				})
			}
		}
	}

	if scope == "token" || scope == "all" {
		digest := core.HashToken(raw)
		var tokens []database.VoidToken
		a.GDB.Where("token_hash = ?", digest).Order("id").Find(&tokens)
		if len(tokens) == 0 {
			// Prefix pattern: split on a trailing marker and match token_prefix.
			if prefix := revealPrefix(raw); prefix != "" {
				a.GDB.Where("token_prefix LIKE ?", prefix+"%").Order("id").Find(&tokens)
			}
		}
		for i := range tokens {
			t := &tokens[i]
			var owner database.User
			a.GDB.First(&owner, t.UserID)
			tokenMatches = append(tokenMatches, gin.H{
				"token_id": t.ID, "name": t.Name, "owner_id": owner.ID,
				"owner_name": owner.Username, "owner_nickname": owner.Name,
				"total_requests": t.TotalRequests, "total_tokens": t.TotalTokens,
				"enabled": t.Enabled, "created_at": t.CreatedAt, "deleted": t.Deleted,
			})
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"provider_matches": providerMatches, "token_matches": tokenMatches,
	})
}

// revealPrefix extracts an explicit prefix from a reveal pattern like "vs-abc…",
// "vs-abc..." or "vs-abc*" (suffix-only patterns are unsupported for tokens).
func revealPrefix(raw string) string {
	for _, marker := range []string{"…", "...", "*"} {
		if prefix, _, ok := strings.Cut(raw, marker); ok {
			return prefix
		}
	}
	return ""
}

// RegisterRevealRoutes wires the owner-only key reveal search.
func RegisterRevealRoutes(admin *gin.RouterGroup, a *App) {
	admin.POST("/reveal/key", core.RequireOwner(), a.revealKeySearch)
}
