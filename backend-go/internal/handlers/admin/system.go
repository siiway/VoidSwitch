package admin

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/services/providers"
	"github.com/siiway/voidswitch/internal/tasks"
)

var TaskManager *tasks.TaskManager

func getSystem(c *gin.Context) {
	user, ok := getCurrentUserGin(c)
	if !ok || !requireStaffGin(c, user) {
		return
	}

	adapterTypes := providers.AdapterTypes()

	var taskStatuses []tasks.TaskStatus
	if TaskManager != nil {
		taskStatuses = TaskManager.Status()
	} else {
		taskStatuses = []tasks.TaskStatus{}
	}

	c.JSON(http.StatusOK, gin.H{
		"version":        "1.0.0",
		"adapter_types":  adapterTypes,
		"task_statuses":  taskStatuses,
	})
}

func RegisterSystemRoutes(router *gin.RouterGroup) {
	router.GET("/system", getSystem)
}
