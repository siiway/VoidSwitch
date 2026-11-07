// Package constants holds shared enums and status values. They are stored as
// plain strings in the database so the exact Python values keep working.
package constants

// Role is a platform role.
type Role string

const (
	RoleOwner   Role = "owner"
	RoleCoOwner Role = "co-owner"
	RoleAdmin   Role = "admin"
	RoleMember  Role = "member"
)

// ModeratorGroupSlug is the built-in role group that always grants all models.
const ModeratorGroupSlug = "moderator"

// TeamRoleRank ranks a Prism *team* role for mapping evaluation.
var TeamRoleRank = map[string]int{
	"owner":    4,
	"co-owner": 3,
	"co_owner": 3,
	"coowner":  3,
	"admin":    2,
	"member":   1,
}

// KeyStatus is an upstream key's lifecycle state.
type KeyStatus string

const (
	KeyStatusActive              KeyStatus = "active"
	KeyStatusInvalid             KeyStatus = "invalid"
	KeyStatusInsufficientBalance KeyStatus = "insufficient_balance"
	KeyStatusRateLimited         KeyStatus = "rate_limited"
	KeyStatusDisabled            KeyStatus = "disabled"
)

// NodeStatus is an outbound node's health state.
type NodeStatus string

const (
	NodeStatusActive   NodeStatus = "active"
	NodeStatusDisabled NodeStatus = "disabled"
)

// NodeType selects a node's transport.
type NodeType string

const (
	NodeTypeDirect NodeType = "direct"
	NodeTypeHTTP   NodeType = "http"
	NodeTypeSocks5 NodeType = "socks5"
	NodeTypeAgent  NodeType = "agent"
)

// ApiStyle is the wire protocol family of a provider/request.
type ApiStyle string

const (
	ApiStyleOpenAI          ApiStyle = "openai"
	ApiStyleAnthropic       ApiStyle = "anthropic"
	ApiStyleOpenAIResponses ApiStyle = "openai-responses"
	ApiStyleGemini          ApiStyle = "gemini"
)

// KeySelectMode governs which key leads a request's candidate order.
type KeySelectMode string

const (
	KeySelectRoundRobin       KeySelectMode = "round_robin"
	KeySelectRandom           KeySelectMode = "random"
	KeySelectFallback         KeySelectMode = "fallback"
	KeySelectPinnedRoundRobin KeySelectMode = "pinned_round_robin"
	KeySelectPinnedRandom     KeySelectMode = "pinned_random"
)

// UpstreamSelectMode governs how health affects the first upstream pick.
type UpstreamSelectMode string

const (
	UpstreamSelectBest           UpstreamSelectMode = "best"
	UpstreamSelectBalanced       UpstreamSelectMode = "balanced"
	UpstreamSelectPinnedBest     UpstreamSelectMode = "pinned_best"
	UpstreamSelectPinnedBalanced UpstreamSelectMode = "pinned_balanced"
)

// UpstreamRankAlgorithm constrains how priority/weight interact with health.
type UpstreamRankAlgorithm string

const (
	RankWeighted UpstreamRankAlgorithm = "weighted"
	RankTiered   UpstreamRankAlgorithm = "tiered"
)

// Client hint headers.
const (
	ClientHintHeader    = "x-voidswitch-client"
	OpenCodeClientHint  = "opencode-plugin"
	SessionHeader       = "x-voidswitch-session"
	UpstreamUnavailable = 543
)

// Fixed (non-configurable) rate limits.
const (
	OperationRateLimitWindowSeconds = 20
	OperationRateLimitMaxRequests   = 30
	CallRateLimitWindowSeconds      = 30
	CallRateLimitMaxRequests        = 30
	ModeratorCallRateLimitMax       = 50
)

// DevUserSub is the deterministic identity used by the dev-only login bypass.
const DevUserSub = "dev-mode-user"
