package core

import (
	"sync"
	"time"
)

type SlidingWindowLimiter struct {
	windows map[string][]time.Time
	mu      sync.Mutex
}

func NewSlidingWindowLimiter() *SlidingWindowLimiter {
	return &SlidingWindowLimiter{
		windows: make(map[string][]time.Time),
	}
}

func (l *SlidingWindowLimiter) Allow(key string, windowSeconds float64, maxRequests int) bool {
	if maxRequests <= 0 || windowSeconds <= 0 {
		return true
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-time.Duration(windowSeconds * float64(time.Second)))

	window := l.windows[key]
	var filtered []time.Time
	for _, t := range window {
		if t.After(cutoff) {
			filtered = append(filtered, t)
		}
	}

	if len(filtered) >= maxRequests {
		l.windows[key] = filtered
		return false
	}

	filtered = append(filtered, now)
	l.windows[key] = filtered
	return true
}

var OperationLimiter = NewSlidingWindowLimiter()
var CallLimiter = NewSlidingWindowLimiter()
