package handlers

import (
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/models"
)

func RegisterUsageRoutes(router *gin.RouterGroup) {
	router.GET("/usage", handleUsage)
}

func handleUsage(c *gin.Context) {
	user := core.GetUserFromContext(c)
	if user == nil {
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Authentication required."})
		return
	}

	scope := c.DefaultQuery("scope", "self")
	days := 30
	if d := c.Query("days"); d != "" {
		if parsed, err := strconv.Atoi(d); err == nil && parsed > 0 {
			days = parsed
		}
	}

	db := database.GetDatabase().DB
	isStaff := core.StaffRolesSet[user.Role]

	if scope == "all" && !isStaff {
		scope = "self"
	}

	since := time.Now().Add(-time.Duration(days) * 24 * time.Hour)
	var where string
	var args []interface{}
	if scope == "self" {
		where = "user_sub = ? AND ts >= ?"
		args = []interface{}{user.Sub, since}
	} else {
		where = "ts >= ?"
		args = []interface{}{since}
	}

	totals := queryTotals(db, where, args)
	daily := queryBuckets(db, where, args, `strftime('%Y-%m-%d', ts)`, "%Y-%m-%d")
	weekly := queryBuckets(db, where, args, `strftime('%Y-%W', ts)`, "%Y-%W")
	monthly := queryBuckets(db, where, args, `strftime('%Y-%m', ts)`, "%Y-%m")
	yearly := queryBuckets(db, where, args, `strftime('%Y', ts)`, "%Y")

	var byUser []models.UsageGroupRow
	var byToken []models.UsageGroupRow
	var byModel []models.UsageGroupRow

	if isStaff && scope == "all" {
		byUser = queryGroup(db, where, args, "user_sub", "user_sub")
	}
	byToken = queryTokenGroup(db, where, args)
	byModel = queryGroup(db, where, args, "model", "model")

	c.JSON(http.StatusOK, models.UsageAnalyticsOut{
		Scope:   scope,
		Totals:  totals,
		Daily:   daily,
		Weekly:  weekly,
		Monthly: monthly,
		Yearly:  yearly,
		ByUser:  byUser,
		ByToken: byToken,
		ByModel: byModel,
	})
}

func queryTotals(db *gorm.DB, where string, args []interface{}) models.UsageTotals {
	var t models.UsageTotals
	db.Model(&database.RequestLog{}).
		Where(where, args...).
		Select(`COALESCE(COUNT(*), 0) as requests,
			COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as success,
			COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failures,
			COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) as completion_tokens,
			COALESCE(SUM(total_tokens), 0) as total_tokens`).
		Scan(&t)
	return t
}

func queryBuckets(db *gorm.DB, where string, args []interface{}, groupExpr, period string) []models.UsageBucket {
	type row struct {
		models.UsageTotals
		Period string
	}
	var rows []row
	db.Model(&database.RequestLog{}).
		Where(where, args...).
		Select(groupExpr+` as period,
			COALESCE(COUNT(*), 0) as requests,
			COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as success,
			COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failures,
			COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) as completion_tokens,
			COALESCE(SUM(total_tokens), 0) as total_tokens`).
		Group(groupExpr).
		Order("period ASC").
		Scan(&rows)

	result := make([]models.UsageBucket, 0, len(rows))
	for _, r := range rows {
		result = append(result, models.UsageBucket{
			UsageTotals: r.UsageTotals,
			Period:      r.Period,
		})
	}
	return result
}

func queryGroup(db *gorm.DB, where string, args []interface{}, groupCol, keyCol string) []models.UsageGroupRow {
	type row struct {
		models.UsageTotals
		Key *string
	}
	var rows []row
	db.Model(&database.RequestLog{}).
		Where(where+" AND "+groupCol+" IS NOT NULL", args...).
		Select(groupCol+` as key,
			COALESCE(COUNT(*), 0) as requests,
			COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as success,
			COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failures,
			COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) as completion_tokens,
			COALESCE(SUM(total_tokens), 0) as total_tokens`).
		Group(groupCol).
		Order("total_tokens DESC").
		Scan(&rows)

	result := make([]models.UsageGroupRow, 0, len(rows))
	for _, r := range rows {
		label := ""
		if r.Key != nil {
			label = *r.Key
		}
		result = append(result, models.UsageGroupRow{
			UsageTotals: r.UsageTotals,
			Key:         label,
			Label:       label,
		})
	}
	return result
}

func queryTokenGroup(db *gorm.DB, where string, args []interface{}) []models.UsageGroupRow {
	type row struct {
		models.UsageTotals
		TokenID   *int
		TokenName *string
	}
	var rows []row
	db.Model(&database.RequestLog{}).
		Where(where+" AND token_id IS NOT NULL", args...).
		Select(`token_id, COALESCE(MAX(token_name), '') as token_name,
			COALESCE(COUNT(*), 0) as requests,
			COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as success,
			COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failures,
			COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
			COALESCE(SUM(completion_tokens), 0) as completion_tokens,
			COALESCE(SUM(total_tokens), 0) as total_tokens`).
		Group("token_id").
		Order("total_tokens DESC").
		Scan(&rows)

	result := make([]models.UsageGroupRow, 0, len(rows))
	for _, r := range rows {
		key := ""
		label := ""
		if r.TokenID != nil {
			key = strconv.Itoa(*r.TokenID)
		}
		if r.TokenName != nil && *r.TokenName != "" {
			label = *r.TokenName
		} else {
			label = key
		}
		result = append(result, models.UsageGroupRow{
			UsageTotals: r.UsageTotals,
			Key:         key,
			Label:       label,
		})
	}
	return result
}
