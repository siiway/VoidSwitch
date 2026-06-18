package core

import (
	"encoding/json"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
)

func RecordAudit(
	db *gorm.DB,
	action string,
	actorSub *string,
	actorName *string,
	targetType *string,
	targetID *string,
	detail map[string]any,
	ip *string,
	sensitive map[string]any,
	secretKey *string,
	scope string,
) {
	var sensitiveCiphertext *string

	if sensitive != nil && secretKey != nil && *secretKey != "" {
		plain, err := json.Marshal(sensitive)
		if err == nil {
			encrypted, err := EncryptSecret(string(plain), *secretKey)
			if err == nil {
				sensitiveCiphertext = &encrypted
			}
		}
	}

	entry := database.AuditLog{
		Action:              action,
		ActorSub:            actorSub,
		ActorName:           actorName,
		TargetType:          targetType,
		TargetID:            targetID,
		Detail:              detail,
		IP:                  ip,
		SensitiveCiphertext: sensitiveCiphertext,
		Scope:               scope,
	}
	db.Create(&entry)
}
