package handlers

import (
	"testing"
	"time"

	"github.com/siiway/voidswitch/internal/database"
)

// TestStreamThroughput covers the two reasons a model card's throughput can lie:
// a non-stream sample's duration is a single round trip, and an accounting bug
// shows up as a five-figure rate.
func TestStreamThroughput(t *testing.T) {
	if got := streamThroughput(0, 0); got != nil {
		t.Fatalf("no duration should yield nil, got %v", *got)
	}
	got := streamThroughput(100, 2)
	if got == nil || *got != 50 {
		t.Fatalf("100 output tokens over 2s = %v, want 50", got)
	}
	// Above model_tps_display_max (1000) the figure is suppressed rather than shown.
	if got := streamThroughput(22545, 1); got != nil {
		t.Fatalf("pathological throughput should be suppressed, got %v", *got)
	}
}

// TestModelHealthThroughputUsesOutputTokens pins the aggregator's numerator: the
// card's tok/s counts generated (output) tokens only, so a prompt-heavy request
// does not inflate it.
func TestModelHealthThroughputUsesOutputTokens(t *testing.T) {
	start := time.Now().UTC()
	end := start.Add(3 * time.Second)
	m := "m"
	row := func(prompt, completion int64) database.RequestLog {
		started, finished := start, end
		r := database.RequestLog{
			TS: start, StartedAt: &started, FinishedAt: &finished,
			Model: &m, Success: true, Stream: true,
			PromptTokens: prompt, CompletionTokens: completion,
			TotalTokens: prompt + completion,
		}
		return r
	}
	// Two samples of 3s: 200 output tokens in 6s. Counting total tokens (2200)
	// would report ≈366 tok/s instead.
	rows := []database.RequestLog{row(1000, 100), row(1000, 100)}

	health := aggregateModelHealth(rows, 50, 10)["m"]
	got, ok := health["tokens_per_second"].(*float64)
	if !ok || got == nil {
		t.Fatalf("tokens_per_second = %v", health["tokens_per_second"])
	}
	if *got < 33 || *got > 34 {
		t.Fatalf("throughput = %v, want ≈33.33 (output tokens only)", *got)
	}
}

// TestModelHealthThroughputSkipsNonStream keeps non-stream samples out of both
// the numerator and the denominator.
func TestModelHealthThroughputSkipsNonStream(t *testing.T) {
	start := time.Now().UTC()
	end := start.Add(time.Second)
	m := "m"
	streamed := database.RequestLog{
		TS: start, StartedAt: &start, FinishedAt: &end, Model: &m,
		Success: true, Stream: true, CompletionTokens: 100, TotalTokens: 100,
	}
	quick := database.RequestLog{
		TS: start, StartedAt: &start, FinishedAt: &end, Model: &m,
		Success: true, Stream: false, CompletionTokens: 900, TotalTokens: 900,
	}
	health := aggregateModelHealth([]database.RequestLog{streamed, quick}, 50, 10)["m"]
	got, _ := health["tokens_per_second"].(*float64)
	if got == nil || *got != 100 {
		t.Fatalf("throughput = %v, want 100 (only the streamed sample)", got)
	}
}
