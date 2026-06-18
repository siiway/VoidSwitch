package tasks

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/siiway/voidswitch/internal/services"
)

type TickFn func() error

type PeriodicTask struct {
	Name        string
	Tick        TickFn
	IntervalKey string
	EnabledKey  *string
	MinInterval int
	LastRun     *time.Time
	LastError   *string
	Runs        int
	mu          sync.RWMutex
}

type TaskManager struct {
	tasks    []*PeriodicTask
	handles  []taskHandle
	stopping chan struct{}
	mu       sync.Mutex
}

type taskHandle struct {
	cancel context.CancelFunc
}

type TaskStatus struct {
	Name            string  `json:"name"`
	IntervalSeconds int     `json:"interval_seconds"`
	Enabled         bool    `json:"enabled"`
	Runs            int     `json:"runs"`
	LastRun         *string `json:"last_run"`
	LastError       *string `json:"last_error"`
}

func NewTaskManager() *TaskManager {
	return &TaskManager{
		stopping: make(chan struct{}),
	}
}

func (tm *TaskManager) Register(task *PeriodicTask) {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	tm.tasks = append(tm.tasks, task)
}

func (tm *TaskManager) Start() {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	tm.stopping = make(chan struct{})
	for _, task := range tm.tasks {
		ctx, cancel := context.WithCancel(context.Background())
		tm.handles = append(tm.handles, taskHandle{cancel: cancel})
		go tm.runTask(ctx, task)
	}
	log.Printf("tasks: started %d tasks", len(tm.handles))
}

func (tm *TaskManager) Stop() {
	tm.mu.Lock()
	close(tm.stopping)
	for _, h := range tm.handles {
		h.cancel()
	}
	tm.mu.Unlock()

	for _, h := range tm.handles {
		h.cancel()
	}
	tm.handles = nil
	log.Println("tasks: stopped")
}

func (tm *TaskManager) Status() []TaskStatus {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	result := make([]TaskStatus, 0, len(tm.tasks))
	for _, t := range tm.tasks {
		enabled := true
		if t.EnabledKey != nil {
			enabled = services.GetBool(*t.EnabledKey, true)
		}
		interval := services.GetInt(t.IntervalKey, t.MinInterval)
		if interval < t.MinInterval {
			interval = t.MinInterval
		}

		t.mu.RLock()
		var lastRunStr *string
		if t.LastRun != nil {
			s := t.LastRun.Format(time.RFC3339)
			lastRunStr = &s
		}
		result = append(result, TaskStatus{
			Name:            t.Name,
			IntervalSeconds: interval,
			Enabled:         enabled,
			Runs:            t.Runs,
			LastRun:         lastRunStr,
			LastError:       t.LastError,
		})
		t.mu.RUnlock()
	}
	return result
}

func (tm *TaskManager) runTask(ctx context.Context, task *PeriodicTask) {
	select {
	case <-ctx.Done():
		return
	case <-time.After(5 * time.Second):
	}

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		enabled := true
		if task.EnabledKey != nil {
			enabled = services.GetBool(*task.EnabledKey, true)
		}

		if enabled {
			start := time.Now()
			err := task.Tick()
			now := time.Now()

			task.mu.Lock()
			task.Runs++
			task.LastRun = &now
			if err != nil {
				errStr := err.Error()
				task.LastError = &errStr
				log.Printf("task_tick_failed task=%s error=%s", task.Name, errStr)
			} else {
				task.LastError = nil
			}
			task.mu.Unlock()

			_ = start
		}

		interval := services.GetInt(task.IntervalKey, task.MinInterval)
		if interval < task.MinInterval {
			interval = task.MinInterval
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Duration(interval) * time.Second):
		}
	}
}
