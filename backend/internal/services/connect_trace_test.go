package services

import (
	"net/http/httptrace"
	"testing"
	"time"
)

// TestConnectTraceMeasuresDial covers the connect-time metric: it is reported
// once GotConn fires (a pooled or fresh connection both end there), and a dial
// that never completes still reports the time spent trying.
func TestConnectTraceMeasuresDial(t *testing.T) {
	tr := &connectTrace{start: time.Now().Add(-50 * time.Millisecond)}
	got := tr.trace().GotConn
	got(httptrace.GotConnInfo{})

	ms := tr.elapsed()
	if ms == nil {
		t.Fatal("elapsed() returned nil")
	}
	if *ms < 40 {
		t.Fatalf("connect time = %vms, want >= 40", *ms)
	}

	// Never dialled: elapsed() must still be a duration, not nil.
	none := &connectTrace{start: time.Now().Add(-5 * time.Millisecond)}
	if v := none.elapsed(); v == nil || *v < 0 {
		t.Fatalf("failed dial elapsed = %v, want a non-negative duration", v)
	}
	empty := &connectTrace{}
	if v := empty.elapsed(); v == nil || *v < 0 {
		t.Fatalf("zero-value trace elapsed = %v, want a non-negative duration", v)
	}
	var nilTrace *connectTrace
	if nilTrace.elapsed() != nil {
		t.Fatal("a nil trace should report nil, not a duration")
	}
}
