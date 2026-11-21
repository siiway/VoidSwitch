package handlers

import "testing"

// TestStreamThroughput covers the two reasons a model card's throughput can lie:
// a non-stream sample's duration is a single round trip, and an accounting bug
// shows up as a five-figure rate.
func TestStreamThroughput(t *testing.T) {
	if got := streamThroughput(0, 0); got != nil {
		t.Fatalf("no duration should yield nil, got %v", *got)
	}
	got := streamThroughput(100, 2)
	if got == nil || *got != 50 {
		t.Fatalf("100 tokens over 2s = %v, want 50", got)
	}
	// Above model_tps_display_max (1000) the figure is suppressed rather than shown.
	if got := streamThroughput(22545, 1); got != nil {
		t.Fatalf("pathological throughput should be suppressed, got %v", *got)
	}
}
