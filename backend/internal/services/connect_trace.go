package services

import (
	"net/http/httptrace"
	"sync"
	"time"
)

// connectTrace measures how long the HTTP client spends obtaining a usable
// connection to the upstream: DNS, TCP, and the TLS handshake. It answers the
// log's "latency" column, which used to duplicate "duration" (the whole
// request). A reused pooled connection reports ~0, which is the honest answer:
// nothing was dialled.
type connectTrace struct {
	start time.Time

	mu        sync.Mutex
	gotConnAt time.Time
}

func (t *connectTrace) trace() *httptrace.ClientTrace {
	return &httptrace.ClientTrace{
		GotConn: func(httptrace.GotConnInfo) {
			t.mu.Lock()
			if t.gotConnAt.IsZero() {
				t.gotConnAt = time.Now()
			}
			t.mu.Unlock()
		},
	}
}

// elapsed returns the connect time measured so far. When the dial never
// completed (a failure or timeout), it reports the time spent trying, so a
// broken egress shows a duration instead of a blank cell.
func (t *connectTrace) elapsed() *float64 {
	if t == nil {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	end := t.gotConnAt
	if end.IsZero() {
		end = time.Now()
	}
	ms := float64(end.Sub(t.start).Milliseconds())
	if ms < 0 {
		ms = 0
	}
	return &ms
}
