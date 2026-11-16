package handlers

import (
	"testing"
	"time"
)

// autoGranularity picks the bucket size for the windowed series; the
// thresholds decide whether a week of traffic renders as 168 hourly points or
// one point.
func TestAutoGranularity(t *testing.T) {
	now := time.Now()
	at := func(d time.Duration) *time.Time {
		v := now.Add(-d)
		return &v
	}
	cases := []struct {
		name  string
		start *time.Time
		end   *time.Time
		want  string
	}{
		{"unbounded is yearly", nil, nil, "year"},
		{"two days is hourly", at(48 * time.Hour), &now, "hour"},
		{"a week is daily", at(7 * 24 * time.Hour), &now, "day"},
		{"a quarter is daily", at(90 * 24 * time.Hour), &now, "day"},
		{"a year is monthly", at(365 * 24 * time.Hour), &now, "month"},
		{"several years is yearly", at(2000 * 24 * time.Hour), &now, "year"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := autoGranularity(c.start, c.end); got != c.want {
				t.Fatalf("autoGranularity = %s, want %s", got, c.want)
			}
		})
	}
}

// "All time" must remain unbounded: the Statistics page's "all" preset sends
// no bounds, and defaulting to 24h silently narrowed every total.
func TestUsageWindowUnbounded(t *testing.T) {
	w := usageWindow{}
	if w.bounded() {
		t.Fatal("an absent window must be unbounded")
	}
	where, args := w.apply("1=1", nil)
	if where != "1=1" || len(args) != 0 {
		t.Fatalf("an unbounded window must not add a predicate, got %q %v", where, args)
	}
}

func TestUsageWindowBounded(t *testing.T) {
	start := time.Date(2026, 1, 2, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 1, 3, 0, 0, 0, 0, time.UTC)
	w := usageWindow{start: &start, end: &end}
	where, args := w.apply("1=1", nil)
	// The right edge is exclusive: the window end is "next day 00:00", so an
	// inclusive bound double-counted a record at exactly midnight.
	if where != "1=1 AND ts >= ? AND ts < ?" {
		t.Fatalf("unexpected predicate: %q", where)
	}
	if len(args) != 2 {
		t.Fatalf("expected two bounds, got %v", args)
	}
}

// The trailing-overview limits are what keep an unbounded overview from
// returning every bucket since launch.
func TestPeriodExprIsBounded(t *testing.T) {
	for _, g := range []string{"hour", "day", "week", "month", "year", "unknown"} {
		label, trunc := periodExpr(g)
		if label == "" || trunc == "" {
			t.Fatalf("%s produced an empty expression", g)
		}
		if _, ok := trailingLimits[g]; !ok && g != "unknown" {
			t.Fatalf("%s has no trailing limit", g)
		}
	}
}
