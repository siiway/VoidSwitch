// Package tasks runs periodic background jobs and exposes their status to the
// dashboard. This mirrors the Python TaskManager (interval + enabled keys read
// from the runtime settings store).
package tasks

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/services"
)

// Status is one task's runtime status (matches the frontend TaskStatus type).
type Status struct {
	Name            string     `json:"name"`
	IntervalSeconds int        `json:"interval_seconds"`
	Enabled         bool       `json:"enabled"`
	Runs            int        `json:"runs"`
	LastRun         *time.Time `json:"last_run"`
	LastError       *string    `json:"last_error"`
}

// Task describes a registered periodic job.
type Task struct {
	Name        string
	IntervalKey string
	EnabledKey  string
	MinInterval int
	Tick        func(ctx context.Context) error

	mu      sync.Mutex
	runs    int
	lastRun *time.Time
	lastErr *string
}

// Manager owns all registered tasks and their scheduler loop.
type Manager struct {
	db     *gorm.DB
	tasks  []*Task
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

func New(db *gorm.DB) *Manager { return &Manager{db: db} }

// Register adds a task.
func (m *Manager) Register(t *Task) { m.tasks = append(m.tasks, t) }

// Start launches one goroutine per task.
func (m *Manager) Start() {
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	for _, t := range m.tasks {
		m.wg.Add(1)
		go m.loop(ctx, t)
	}
}

func (m *Manager) loop(ctx context.Context, t *Task) {
	defer m.wg.Done()
	// Wait one interval before the first run so boot stays fast.
	for {
		interval := services.GetInt(t.IntervalKey, t.MinInterval)
		if interval < t.MinInterval {
			interval = t.MinInterval
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Duration(interval) * time.Second):
		}
		if t.EnabledKey != "" && !services.GetBool(t.EnabledKey, true) {
			continue
		}
		t.run(ctx)
	}
}

func (t *Task) run(ctx context.Context) {
	t.mu.Lock()
	t.runs++
	now := time.Now().UTC()
	t.lastRun = &now
	t.mu.Unlock()

	func() {
		defer func() {
			if r := recover(); r != nil {
				msg := "panic"
				t.mu.Lock()
				t.lastErr = &msg
				t.mu.Unlock()
				slog.Error("task panic", "task", t.Name, "panic", r)
			}
		}()
		if err := t.Tick(ctx); err != nil {
			msg := err.Error()
			t.mu.Lock()
			t.lastErr = &msg
			t.mu.Unlock()
			slog.Warn("task failed", "task", t.Name, "err", err)
			return
		}
		t.mu.Lock()
		t.lastErr = nil
		t.mu.Unlock()
	}()
}

// Status returns every task's status for the dashboard.
func (m *Manager) Status() []Status {
	out := make([]Status, 0, len(m.tasks))
	for _, t := range m.tasks {
		t.mu.Lock()
		s := Status{
			Name:            t.Name,
			IntervalSeconds: services.GetInt(t.IntervalKey, t.MinInterval),
			Enabled:         t.EnabledKey == "" || services.GetBool(t.EnabledKey, true),
			Runs:            t.runs,
			LastRun:         t.lastRun,
			LastError:       t.lastErr,
		}
		t.mu.Unlock()
		out = append(out, s)
	}
	return out
}

// Stop cancels all task loops and waits for them to finish.
func (m *Manager) Stop() {
	if m.cancel != nil {
		m.cancel()
	}
	m.wg.Wait()
}
