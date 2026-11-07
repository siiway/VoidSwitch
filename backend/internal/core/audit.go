package core

import (
	"encoding/json"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// AuditScope distinguishes management (admin) from self-service (self) actions.
type AuditScope string

const (
	AuditScopeAdmin AuditScope = "admin"
	AuditScopeSelf  AuditScope = "self"
)

// AuditInput describes one audit row.
type AuditInput struct {
	Action        string
	ActorSub      *string
	ActorName     *string
	Scope         AuditScope
	TargetType    *string
	TargetID      *string
	Detail        map[string]any
	IP            *string
	UserAgent     *string
	Sensitive     map[string]any // encrypted at rest when non-nil
	SecretKey     string
}

// RecordAudit writes an audit_logs row. Sensitive detail (if provided) is
// encrypted with the app secret using the same Fernet format as Python so
// existing owner-reveal flows keep working.
func RecordAudit(db *gorm.DB, in AuditInput) error {
	var sensitive *string
	if len(in.Sensitive) > 0 && in.SecretKey != "" {
		if plain, err := json.Marshal(in.Sensitive); err == nil {
			if enc, err := cryptoutil.EncryptSecret(string(plain), in.SecretKey); err == nil {
				sensitive = &enc
			}
		}
	}

	detail := in.Detail
	if detail == nil {
		detail = map[string]any{}
	}
	scope := in.Scope
	if scope == "" {
		scope = AuditScopeAdmin
	}

	row := database.AuditLog{
		TS:                  time.Now().UTC(),
		Action:              in.Action,
		ActorSub:            in.ActorSub,
		ActorName:           in.ActorName,
		Scope:               string(scope),
		TargetType:          in.TargetType,
		TargetID:            in.TargetID,
		Detail:              database.JSONOf(detail),
		IP:                  in.IP,
		UserAgent:           in.UserAgent,
		SensitiveCiphertext: sensitive,
	}
	return db.Create(&row).Error
}

// RevealAuditSensitive decrypts a stored sensitive payload for an owner.
func RevealAuditSensitive(ciphertext, secretKey string) (map[string]any, error) {
	plain, err := cryptoutil.DecryptSecret(ciphertext, secretKey)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(plain), &out); err != nil {
		return nil, err
	}
	return out, nil
}
