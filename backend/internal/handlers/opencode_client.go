package handlers

import (
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
)

// opencodePluginVersion reports which VoidSwitch OpenCode plugin generation
// served a request, or "" when the request did not come through the plugin.
//
// The client hint header is the primary signal. V2 plugins also send an explicit
// version, but the undecorated hint alone predates that header, so a bare hint
// is treated as V1:
//
//	v2 -> "v2", v1 -> "v1", absent/unknown -> "" (not the plugin)
func opencodePluginVersion(c *gin.Context) string {
	if c.GetHeader(constants.ClientHintHeader) != constants.OpenCodeClientHint {
		return ""
	}
	switch strings.ToLower(strings.TrimSpace(c.GetHeader(constants.OpenCodeClientVersionHeader))) {
	case constants.OpenCodePluginV2:
		return constants.OpenCodePluginV2
	default:
		return constants.OpenCodePluginV1
	}
}
